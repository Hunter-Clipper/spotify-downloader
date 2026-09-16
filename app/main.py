import asyncio
import logging
import os
import re
import shutil
import time
import uuid
import zipfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent.parent / "static"


def _resolve_download_dir() -> Path:
    """Use DOWNLOAD_DIR if it is writable, otherwise fall back to /tmp."""
    configured = Path(os.environ.get("DOWNLOAD_DIR", "/data/downloads"))
    try:
        configured.mkdir(parents=True, exist_ok=True)
        probe = configured / ".write_probe"
        probe.touch()
        probe.unlink()
        return configured
    except OSError:
        logger.warning(
            f"DOWNLOAD_DIR '{configured}' is not writable "
            f"(no volume mounted?). Falling back to /tmp/spotdl_downloads."
        )
        fallback = Path("/tmp/spotdl_downloads")
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


DOWNLOAD_DIR = _resolve_download_dir()

SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")

# --- Configuration ---
JOB_TTL_SECONDS = 30 * 60           # 30 minutes before auto-purge
PURGE_CHECK_INTERVAL = 60           # Check for stale jobs every 60s
MAX_CONCURRENT_JOBS = 5             # Max simultaneous downloads
RATE_LIMIT_WINDOW = 60              # Rate limit window in seconds
RATE_LIMIT_MAX_REQUESTS = 10        # Max download requests per window per IP

ALLOWED_FORMATS = {"mp3", "flac", "wav", "ogg"}
ALLOWED_BITRATES = {"128k", "192k", "256k", "320k"}
ALLOWED_AUDIO_PROVIDERS = {"youtube-music", "youtube", "piped"}

# Formats that ignore --bitrate
LOSSLESS_FORMATS = {"flac", "wav"}

# spotdl output patterns used to turn raw log lines into progress events
FOUND_SONGS_RE = re.compile(r"Found (\d+) songs?", re.IGNORECASE)
DOWNLOADING_RE = re.compile(r"Downloading\s+", re.IGNORECASE)
TRACK_DONE_RE = re.compile(r"Downloaded\s+\"|Skipping.*already exists", re.IGNORECASE)


# --- Job state ---
@dataclass
class Job:
    job_id: str
    urls: list[str]
    format: str = "mp3"
    bitrate: str = "320k"
    structured: bool = False
    audio_provider: str = "youtube-music"
    client_id: str = ""
    client_secret: str = ""
    zip_filename: str = ""
    created_at: float = field(default_factory=time.time)


_jobs: dict[str, Job] = {}
_active_jobs: int = 0
_active_jobs_lock = asyncio.Lock()
_rate_limits: dict[str, list[float]] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        logger.warning(
            "SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET are not set. "
            "Using default shared credentials which are heavily rate-limited. "
            "Get your own free credentials at https://developer.spotify.com/dashboard"
        )
    # Keep a reference so the task is not garbage collected mid-flight.
    purge_task = asyncio.create_task(_purge_loop())
    yield
    purge_task.cancel()


app = FastAPI(title="Spotify Downloader", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


async def _purge_loop() -> None:
    """Background task that purges expired jobs and stale rate-limit entries."""
    while True:
        await asyncio.sleep(PURGE_CHECK_INTERVAL)
        now = time.time()

        expired = [jid for jid, job in _jobs.items() if now - job.created_at > JOB_TTL_SECONDS]
        for jid in expired:
            _cleanup_job(jid)

        stale_ips = [
            ip for ip, timestamps in _rate_limits.items()
            if not any(now - t < RATE_LIMIT_WINDOW for t in timestamps)
        ]
        for ip in stale_ips:
            del _rate_limits[ip]


def _cleanup_job(job_id: str) -> None:
    """Remove all files and state for a job."""
    shutil.rmtree(DOWNLOAD_DIR / job_id, ignore_errors=True)
    _jobs.pop(job_id, None)


def _check_rate_limit(ip: str) -> None:
    """Enforce per-IP rate limiting. Raises HTTPException if exceeded."""
    now = time.time()
    timestamps = [t for t in _rate_limits.get(ip, []) if now - t < RATE_LIMIT_WINDOW]
    _rate_limits[ip] = timestamps

    if len(timestamps) >= RATE_LIMIT_MAX_REQUESTS:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Max {RATE_LIMIT_MAX_REQUESTS} requests per {RATE_LIMIT_WINDOW}s.",
        )
    timestamps.append(now)


class DownloadRequest(BaseModel):
    url: str = ""
    urls: list[str] = []
    client_id: str = ""
    client_secret: str = ""
    format: str = "mp3"
    bitrate: str = "320k"
    structured: bool = False
    audio_provider: str = "youtube-music"


class PreviewRequest(BaseModel):
    url: str


def _validate_spotify_url(url: str) -> str:
    """Validate that the URL is a Spotify track, album, or playlist link."""
    url = url.strip()
    is_spotify = url.startswith(("https://open.spotify.com/", "http://open.spotify.com/"))
    has_content = any(part in url for part in ("/track/", "/album/", "/playlist/"))
    if not is_spotify or not has_content:
        raise ValueError("Invalid Spotify URL. Must be a track, album, or playlist link.")
    return url


def _validate_choice(value: str, allowed: set[str], label: str) -> str:
    """Lowercase and check a request option against its allow-list."""
    normalized = value.lower()
    if normalized not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {label}. Allowed: {', '.join(sorted(allowed))}",
        )
    return normalized


def _spotify_url_type(url: str, default: str = "download") -> str:
    """Classify a Spotify URL as a track, album, or playlist link."""
    if "/track/" in url:
        return "track"
    if "/album/" in url:
        return "album"
    if "/playlist/" in url:
        return "playlist"
    return default


def _sanitize_filename(name: str) -> str:
    """Remove characters that are unsafe in filenames."""
    name = re.sub(r'[<>:"/\\|?*]', "", name).strip(". ")
    return name[:100] if name else "download"


def _find_music_files(job_dir: Path, fmt: str, structured: bool) -> list[Path]:
    """List the downloaded tracks, recursing when artist/album folders are used."""
    pattern = f"*.{fmt}"
    files = job_dir.rglob(pattern) if structured else job_dir.glob(pattern)
    return sorted(files)


async def _run_spotdl(
    urls: list[str],
    output_dir: Path,
    fmt: str = "mp3",
    bitrate: str = "320k",
    structured: bool = False,
    audio_provider: str = "youtube-music",
    client_id: str = "",
    client_secret: str = "",
) -> AsyncIterator[str]:
    """Run spotdl and yield progress lines with structured event prefixes."""
    output_template = "{artist}/{album}/{title}" if structured else "{title}"

    cmd = [
        "spotdl",
        "download", *urls,
        "--output", str(output_dir / output_template),
        "--format", fmt,
        "--threads", "4",
        "--audio", audio_provider,
    ]

    if fmt not in LOSSLESS_FORMATS:
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

        found_match = FOUND_SONGS_RE.search(decoded)
        if found_match:
            track_count = int(found_match.group(1))
            yield f"TOTAL:{track_count}"

        if DOWNLOADING_RE.search(decoded) and "song" not in decoded.lower():
            yield f"TRACK_START:{decoded}"

        if TRACK_DONE_RE.search(decoded):
            tracks_done += 1
            yield f"TRACK_DONE:{tracks_done}/{track_count or '?'} {decoded}"

        yield f"LOG:{decoded}"

    await process.wait()

    if process.returncode != 0:
        raise RuntimeError("spotdl exited with an error")


def _build_zip_filename(music_files: list[Path], urls: list[str]) -> str:
    """Build a descriptive zip filename from the downloaded tracks."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    url_type = _spotify_url_type(urls[0]) if len(urls) == 1 else "batch"

    if url_type == "track" and len(music_files) == 1:
        base = music_files[0].stem
    elif url_type == "album" and music_files:
        artist, separator, _ = music_files[0].stem.partition(" - ")
        base = artist if separator else "album"
    elif url_type == "playlist" and music_files:
        base = "playlist"
    elif url_type == "batch":
        base = f"batch_{len(music_files)}_tracks"
    else:
        base = "download"

    return f"{_sanitize_filename(base)}_{timestamp}.zip"


def _create_zip(music_files: list[Path], source_dir: Path, zip_path: Path) -> None:
    """Zip the given music files, preserving folders relative to source_dir."""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for music_file in music_files:
            zf.write(music_file, music_file.relative_to(source_dir))


@app.get("/api/status")
async def status():
    return {"server_credentials": bool(SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET)}


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/download")
async def download(req: DownloadRequest, request: Request):
    """Start a download job and return the job ID."""
    _check_rate_limit(request.client.host)

    urls = list(req.urls)
    if req.url.strip():
        urls.insert(0, req.url.strip())
    urls = list(dict.fromkeys(urls))  # deduplicate preserving order

    if not urls:
        raise HTTPException(status_code=400, detail="No URLs provided.")

    validated = []
    for url in urls:
        try:
            validated.append(_validate_spotify_url(url))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"{e} — {url}")

    fmt = _validate_choice(req.format, ALLOWED_FORMATS, "format")
    bitrate = _validate_choice(req.bitrate, ALLOWED_BITRATES, "bitrate")
    audio_provider = _validate_choice(req.audio_provider, ALLOWED_AUDIO_PROVIDERS, "audio provider")

    # Optimistic pre-check (not under lock — enforced atomically in the SSE stream)
    if _active_jobs >= MAX_CONCURRENT_JOBS:
        raise HTTPException(
            status_code=503,
            detail=f"Server busy — max {MAX_CONCURRENT_JOBS} concurrent downloads. Please try again shortly.",
        )

    job_id = str(uuid.uuid4())
    (DOWNLOAD_DIR / job_id).mkdir(parents=True, exist_ok=True)

    has_user_creds = bool(req.client_id and req.client_secret)
    _jobs[job_id] = Job(
        job_id=job_id,
        urls=validated,
        format=fmt,
        bitrate=bitrate,
        structured=req.structured,
        audio_provider=audio_provider,
        client_id=req.client_id if has_user_creds else "",
        client_secret=req.client_secret if has_user_creds else "",
    )

    return {"job_id": job_id}


@app.get("/api/progress/{job_id}")
async def progress(job_id: str):
    """SSE endpoint that runs spotdl and streams structured progress events."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    job_dir = DOWNLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    async def event_stream() -> AsyncIterator[str]:
        global _active_jobs

        # Read the credentials once, then clear them from memory.
        cid, csec = job.client_id, job.client_secret
        job.client_id = ""
        job.client_secret = ""

        # Atomic concurrency check + increment under the lock
        async with _active_jobs_lock:
            if _active_jobs >= MAX_CONCURRENT_JOBS:
                yield "data: ERROR: Server busy — max concurrent downloads reached. Please try again.\n\n"
                return
            _active_jobs += 1

        try:
            async for line in _run_spotdl(
                job.urls, job_dir, job.format, job.bitrate, job.structured, job.audio_provider, cid, csec
            ):
                yield f"data: {line}\n\n"

            music_files = _find_music_files(job_dir, job.format, job.structured)
            if not music_files:
                yield "data: ERROR: No tracks were downloaded.\n\n"
                return

            job.zip_filename = _build_zip_filename(music_files, job.urls)
            _create_zip(music_files, job_dir, job_dir / "tracks.zip")

            track_names = ";;".join(f.stem for f in sorted(music_files, key=lambda p: p.name))
            yield f"data: DONE:{len(music_files)}|{track_names}\n\n"
        except Exception as e:
            yield f"data: ERROR: {e}\n\n"
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

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get("https://open.spotify.com/oembed", params={"url": url})
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        raise HTTPException(status_code=502, detail="Could not fetch preview from Spotify.")

    return {
        "title": data.get("title", "Unknown"),
        "thumbnail_url": data.get("thumbnail_url", ""),
        "type": _spotify_url_type(url, default="track"),
    }


@app.get("/api/zip/{job_id}")
async def get_zip(job_id: str):
    """Download the completed zip file."""
    zip_path = DOWNLOAD_DIR / job_id / "tracks.zip"
    if not zip_path.exists():
        raise HTTPException(status_code=404, detail="Zip not found. Download may still be in progress.")

    job = _jobs.get(job_id)
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=job.zip_filename if job and job.zip_filename else "spotify_tracks.zip",
    )


@app.delete("/api/cleanup/{job_id}")
async def cleanup(job_id: str):
    """Clean up a finished job's files."""
    _cleanup_job(job_id)
    return {"status": "cleaned"}
