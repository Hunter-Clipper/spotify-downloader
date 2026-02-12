import asyncio
import os
import re
import shutil
import tempfile
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="Spotify Downloader")

DOWNLOAD_DIR = Path(tempfile.gettempdir()) / "spotdl_downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")

# --- Configuration ---
JOB_TTL_SECONDS = 30 * 60          # 30 minutes before auto-purge
PURGE_CHECK_INTERVAL = 60           # Check for stale jobs every 60s
MAX_CONCURRENT_JOBS = 5             # Max simultaneous downloads
RATE_LIMIT_WINDOW = 60              # Rate limit window in seconds
RATE_LIMIT_MAX_REQUESTS = 10        # Max download requests per window per IP

ALLOWED_FORMATS = {"mp3", "flac", "wav", "ogg"}
ALLOWED_BITRATES = {"128k", "192k", "256k", "320k"}


# --- Job state ---
@dataclass
class Job:
    job_id: str
    urls: list[str]
    format: str = "mp3"
    bitrate: str = "320k"
    structured: bool = False
    client_id: str = ""
    client_secret: str = ""
    zip_filename: str = ""
    created_at: float = field(default_factory=time.time)


_jobs: dict[str, Job] = {}
_active_jobs: int = 0
_active_jobs_lock = asyncio.Lock()
_rate_limits: dict[str, list[float]] = {}


@app.on_event("startup")
async def _startup():
    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        import logging
        logging.warning(
            "SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET are not set. "
            "Using default shared credentials which are heavily rate-limited. "
            "Get your own free credentials at https://developer.spotify.com/dashboard"
        )
    asyncio.create_task(_purge_loop())


async def _purge_loop():
    """Background task that purges expired jobs every PURGE_CHECK_INTERVAL seconds."""
    while True:
        await asyncio.sleep(PURGE_CHECK_INTERVAL)
        now = time.time()
        expired = [jid for jid, job in _jobs.items() if now - job.created_at > JOB_TTL_SECONDS]
        for jid in expired:
            _cleanup_job(jid)


def _cleanup_job(job_id: str):
    """Remove all files and state for a job."""
    job_dir = DOWNLOAD_DIR / job_id
    if job_dir.exists():
        shutil.rmtree(job_dir, ignore_errors=True)
    _jobs.pop(job_id, None)


def _check_rate_limit(ip: str):
    """Enforce per-IP rate limiting. Raises HTTPException if exceeded."""
    now = time.time()
    timestamps = _rate_limits.get(ip, [])
    timestamps = [t for t in timestamps if now - t < RATE_LIMIT_WINDOW]
    if len(timestamps) >= RATE_LIMIT_MAX_REQUESTS:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Max {RATE_LIMIT_MAX_REQUESTS} requests per {RATE_LIMIT_WINDOW}s.",
        )
    timestamps.append(now)
    _rate_limits[ip] = timestamps


# Serve the frontend
app.mount("/static", StaticFiles(directory=Path(__file__).parent.parent / "static"), name="static")


class DownloadRequest(BaseModel):
    url: str = ""
    urls: list[str] = []
    client_id: str = ""
    client_secret: str = ""
    format: str = "mp3"
    bitrate: str = "320k"
    structured: bool = False


class PreviewRequest(BaseModel):
    url: str


def _validate_spotify_url(url: str) -> str:
    """Validate that the URL is a Spotify link."""
    url = url.strip()
    if not any(
        pattern in url
        for pattern in ["open.spotify.com/track", "open.spotify.com/album", "open.spotify.com/playlist"]
    ):
        raise ValueError("Invalid Spotify URL. Must be a track, album, or playlist link.")
    return url


def _extract_name_from_url(url: str) -> str:
    """Try to extract a human-readable name hint from the Spotify URL type."""
    if "/track/" in url:
        return "track"
    elif "/album/" in url:
        return "album"
    elif "/playlist/" in url:
        return "playlist"
    return "download"


def _sanitize_filename(name: str) -> str:
    """Remove characters that are unsafe in filenames."""
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = name.strip('. ')
    return name[:100] if name else "download"


async def _run_spotdl(
    urls: list[str],
    output_dir: Path,
    fmt: str = "mp3",
    bitrate: str = "320k",
    structured: bool = False,
    client_id: str = "",
    client_secret: str = "",
):
    """Run spotdl and yield progress lines with structured event prefixes."""
    output_template = "{artist}/{album}/{title}" if structured else "{title}"

    cmd = [
        "spotdl",
        "download", *urls,
        "--output", str(output_dir / output_template),
        "--format", fmt,
        "--threads", "4",
    ]

    # Only pass bitrate for lossy formats
    if fmt not in ("flac", "wav"):
        cmd += ["--bitrate", bitrate]

    cid = client_id or SPOTIFY_CLIENT_ID
    csec = client_secret or SPOTIFY_CLIENT_SECRET
    if cid and csec:
        cmd += ["--client-id", cid, "--client-secret", csec]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    track_count = 0
    tracks_done = 0

    async for line in process.stdout:
        decoded = line.decode("utf-8", errors="replace").strip()
        if not decoded:
            continue

        # Try to detect total tracks from spotdl output
        found_match = re.search(r"Found (\d+) songs?", decoded, re.IGNORECASE)
        if found_match:
            track_count = int(found_match.group(1))
            yield f"TOTAL:{track_count}"

        # Detect track download start
        if re.search(r"Downloading\s+", decoded, re.IGNORECASE) and "song" not in decoded.lower():
            yield f"TRACK_START:{decoded}"

        # Detect track completion
        if re.search(r"Downloaded\s+\"", decoded, re.IGNORECASE) or re.search(r"Skipping.*already exists", decoded, re.IGNORECASE):
            tracks_done += 1
            yield f"TRACK_DONE:{tracks_done}/{track_count if track_count else '?'} {decoded}"

        yield f"LOG:{decoded}"

    await process.wait()

    if process.returncode != 0:
        raise RuntimeError("spotdl exited with an error")


def _build_zip_filename(job_dir: Path, urls: list[str], fmt: str, structured: bool) -> str:
    """Build a descriptive zip filename from the downloaded tracks."""
    ext = fmt if fmt != "ogg" else "ogg"
    if structured:
        music_files = sorted(job_dir.rglob(f"*.{ext}"))
    else:
        music_files = sorted(job_dir.glob(f"*.{ext}"))

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    if len(urls) == 1:
        url_type = _extract_name_from_url(urls[0])
    else:
        url_type = "batch"

    if url_type == "track" and len(music_files) == 1:
        base = music_files[0].stem
    elif url_type == "album" and music_files:
        names = [f.stem for f in music_files]
        parts = names[0].split(" - ", 1)
        base = parts[0] if len(parts) > 1 else "album"
    elif url_type == "playlist" and music_files:
        base = "playlist"
    elif url_type == "batch":
        base = f"batch_{len(music_files)}_tracks"
    else:
        base = "download"

    base = _sanitize_filename(base)
    return f"{base}_{timestamp}.zip"


def _create_zip(source_dir: Path, zip_path: Path, fmt: str, structured: bool):
    """Zip all music files in the source directory."""
    ext = fmt if fmt != "ogg" else "ogg"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        if structured:
            for f in source_dir.rglob(f"*.{ext}"):
                arcname = f.relative_to(source_dir)
                zf.write(f, arcname)
        else:
            for f in source_dir.glob(f"*.{ext}"):
                zf.write(f, f.name)


@app.get("/api/status")
async def status():
    return {"server_credentials": bool(SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET)}


@app.get("/")
async def index():
    return FileResponse(Path(__file__).parent.parent / "static" / "index.html")


@app.post("/api/download")
async def download(req: DownloadRequest, request: Request):
    """Start a download job and return the job ID."""
    client_ip = request.client.host
    _check_rate_limit(client_ip)

    # Normalize urls
    urls = list(req.urls) if req.urls else []
    if req.url and req.url.strip():
        urls.insert(0, req.url.strip())
    urls = list(dict.fromkeys(urls))  # deduplicate preserving order

    if not urls:
        raise HTTPException(status_code=400, detail="No URLs provided.")

    # Validate all URLs
    validated = []
    for u in urls:
        try:
            validated.append(_validate_spotify_url(u))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"{str(e)} — {u}")

    # Validate format and bitrate
    fmt = req.format.lower()
    if fmt not in ALLOWED_FORMATS:
        raise HTTPException(status_code=400, detail=f"Invalid format. Allowed: {', '.join(sorted(ALLOWED_FORMATS))}")
    bitrate = req.bitrate.lower()
    if bitrate not in ALLOWED_BITRATES:
        raise HTTPException(status_code=400, detail=f"Invalid bitrate. Allowed: {', '.join(sorted(ALLOWED_BITRATES))}")

    # Check concurrent job limit
    if _active_jobs >= MAX_CONCURRENT_JOBS:
        raise HTTPException(
            status_code=503,
            detail=f"Server busy — max {MAX_CONCURRENT_JOBS} concurrent downloads. Please try again shortly.",
        )

    job_id = str(uuid.uuid4())
    job_dir = DOWNLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    job = Job(
        job_id=job_id,
        urls=validated,
        format=fmt,
        bitrate=bitrate,
        structured=req.structured,
        client_id=req.client_id if req.client_id and req.client_secret else "",
        client_secret=req.client_secret if req.client_id and req.client_secret else "",
    )
    _jobs[job_id] = job

    return {"job_id": job_id}


@app.get("/api/progress/{job_id}")
async def progress(job_id: str):
    """SSE endpoint that runs spotdl and streams structured progress events."""
    global _active_jobs

    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    job_dir = DOWNLOAD_DIR / job_id
    if not job_dir.exists():
        job_dir.mkdir(parents=True, exist_ok=True)

    async def event_stream():
        global _active_jobs

        cid = job.client_id
        csec = job.client_secret
        # Clear credentials from memory after reading
        job.client_id = ""
        job.client_secret = ""

        async with _active_jobs_lock:
            _active_jobs += 1
        try:
            async for line in _run_spotdl(
                job.urls, job_dir, job.format, job.bitrate, job.structured, cid, csec
            ):
                yield f"data: {line}\n\n"

            # Create the zip
            ext = job.format
            if job.structured:
                music_files = list(job_dir.rglob(f"*.{ext}"))
            else:
                music_files = list(job_dir.glob(f"*.{ext}"))

            if not music_files:
                yield "data: ERROR: No tracks were downloaded.\n\n"
                return

            zip_filename = _build_zip_filename(job_dir, job.urls, job.format, job.structured)
            zip_path = job_dir / "tracks.zip"
            _create_zip(job_dir, zip_path, job.format, job.structured)

            job.zip_filename = zip_filename

            track_names = [f.stem for f in sorted(music_files, key=lambda x: x.name)]
            names_joined = ";;".join(track_names)
            yield f"data: DONE:{len(music_files)}|{names_joined}\n\n"
        except Exception as e:
            yield f"data: ERROR: {str(e)}\n\n"
        finally:
            async with _active_jobs_lock:
                _active_jobs -= 1

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/preview")
async def preview(req: PreviewRequest):
    """Fetch metadata from Spotify's oEmbed API (no auth needed)."""
    url = req.url.strip()
    if not url or "open.spotify.com" not in url:
        raise HTTPException(status_code=400, detail="Invalid Spotify URL.")

    oembed_url = f"https://open.spotify.com/oembed?url={url}"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(oembed_url)
            resp.raise_for_status()
            data = resp.json()

        # Determine type from URL
        url_type = "track"
        if "/album/" in url:
            url_type = "album"
        elif "/playlist/" in url:
            url_type = "playlist"

        return {
            "title": data.get("title", "Unknown"),
            "thumbnail_url": data.get("thumbnail_url", ""),
            "type": url_type,
        }
    except Exception:
        raise HTTPException(status_code=502, detail="Could not fetch preview from Spotify.")


@app.get("/api/zip/{job_id}")
async def get_zip(job_id: str):
    """Download the completed zip file."""
    zip_path = DOWNLOAD_DIR / job_id / "tracks.zip"
    if not zip_path.exists():
        raise HTTPException(status_code=404, detail="Zip not found. Download may still be in progress.")

    job = _jobs.get(job_id)
    filename = job.zip_filename if job and job.zip_filename else "spotify_tracks.zip"

    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=filename,
    )


@app.delete("/api/cleanup/{job_id}")
async def cleanup(job_id: str):
    """Clean up a finished job's files."""
    _cleanup_job(job_id)
    return {"status": "cleaned"}
