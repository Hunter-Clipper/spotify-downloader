import asyncio
import os
import re
import shutil
import tempfile
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

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

# --- State ---
# In-memory store for per-job credentials (never persisted to disk)
_job_credentials: dict[str, tuple[str, str]] = {}
# Track job creation times for auto-purge
_job_timestamps: dict[str, float] = {}
# Track job zip filenames
_job_filenames: dict[str, str] = {}
# Active (in-progress) job count
_active_jobs: int = 0
_active_jobs_lock = asyncio.Lock()
# Rate limiting: IP -> list of request timestamps
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
    # Start the background purge task
    asyncio.create_task(_purge_loop())


async def _purge_loop():
    """Background task that purges expired jobs every PURGE_CHECK_INTERVAL seconds."""
    while True:
        await asyncio.sleep(PURGE_CHECK_INTERVAL)
        now = time.time()
        expired = [jid for jid, ts in _job_timestamps.items() if now - ts > JOB_TTL_SECONDS]
        for jid in expired:
            _cleanup_job(jid)


def _cleanup_job(job_id: str):
    """Remove all files and state for a job."""
    job_dir = DOWNLOAD_DIR / job_id
    if job_dir.exists():
        shutil.rmtree(job_dir, ignore_errors=True)
    _job_timestamps.pop(job_id, None)
    _job_credentials.pop(job_id, None)
    _job_filenames.pop(job_id, None)


def _check_rate_limit(ip: str):
    """Enforce per-IP rate limiting. Raises HTTPException if exceeded."""
    now = time.time()
    timestamps = _rate_limits.get(ip, [])
    # Remove entries outside the window
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
    url: str
    client_id: str = ""
    client_secret: str = ""


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


async def _run_spotdl(url: str, output_dir: Path, client_id: str = "", client_secret: str = ""):
    """Run spotdl and yield progress lines."""
    cmd = [
        "spotdl",
        "download", url,
        "--output", str(output_dir),
        "--format", "mp3",
        "--bitrate", "320k",
        "--threads", "4",
    ]

    # Per-request credentials take priority over env vars
    cid = client_id or SPOTIFY_CLIENT_ID
    csec = client_secret or SPOTIFY_CLIENT_SECRET
    if cid and csec:
        cmd += ["--client-id", cid, "--client-secret", csec]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    async for line in process.stdout:
        decoded = line.decode("utf-8", errors="replace").strip()
        if decoded:
            yield decoded

    await process.wait()

    if process.returncode != 0:
        raise RuntimeError("spotdl exited with an error")


def _build_zip_filename(job_dir: Path, url: str) -> str:
    """Build a descriptive zip filename from the downloaded tracks."""
    mp3_files = sorted(job_dir.glob("*.mp3"))
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    url_type = _extract_name_from_url(url)

    if url_type == "track" and len(mp3_files) == 1:
        # Single track: use its filename
        base = mp3_files[0].stem
    elif url_type == "album" and mp3_files:
        # Album: find common prefix among track names (often "Artist - Album")
        names = [f.stem for f in mp3_files]
        # Try to extract artist from first track (spotdl format: "Artist - Title")
        parts = names[0].split(" - ", 1)
        base = parts[0] if len(parts) > 1 else "album"
    elif url_type == "playlist" and mp3_files:
        base = "playlist"
    else:
        base = "download"

    base = _sanitize_filename(base)
    return f"{base}_{timestamp}.zip"


def _create_zip(source_dir: Path, zip_path: Path):
    """Zip all mp3 files in the source directory."""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for mp3 in source_dir.glob("*.mp3"):
            zf.write(mp3, mp3.name)


@app.get("/api/status")
async def status():
    return {"server_credentials": bool(SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET)}


@app.get("/")
async def index():
    return FileResponse(Path(__file__).parent.parent / "static" / "index.html")


@app.post("/api/download")
async def download(req: DownloadRequest, request: Request):
    """Start a download job and stream progress via SSE, then return the zip file ID."""
    # Rate limiting
    client_ip = request.client.host
    _check_rate_limit(client_ip)

    try:
        url = _validate_spotify_url(req.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Check concurrent job limit
    if _active_jobs >= MAX_CONCURRENT_JOBS:
        raise HTTPException(
            status_code=503,
            detail=f"Server busy — max {MAX_CONCURRENT_JOBS} concurrent downloads. Please try again shortly.",
        )

    job_id = str(uuid.uuid4())
    job_dir = DOWNLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    # Track job for auto-purge
    _job_timestamps[job_id] = time.time()

    # Hold credentials in memory for this job only
    if req.client_id and req.client_secret:
        _job_credentials[job_id] = (req.client_id, req.client_secret)

    return {"job_id": job_id, "url": url}


@app.get("/api/progress/{job_id}")
async def progress(job_id: str, url: str):
    """SSE endpoint that runs spotdl and streams progress."""
    global _active_jobs

    job_dir = DOWNLOAD_DIR / job_id

    if not job_dir.exists():
        job_dir.mkdir(parents=True, exist_ok=True)

    async def event_stream():
        global _active_jobs

        # Retrieve and immediately discard per-job credentials
        cid, csec = _job_credentials.pop(job_id, ("", ""))

        async with _active_jobs_lock:
            _active_jobs += 1
        try:
            async for line in _run_spotdl(url, job_dir, cid, csec):
                yield f"data: {line}\n\n"

            # Create the zip with a descriptive name
            mp3_files = list(job_dir.glob("*.mp3"))
            if not mp3_files:
                yield f"data: ERROR: No tracks were downloaded.\n\n"
                return

            zip_filename = _build_zip_filename(job_dir, url)
            zip_path = job_dir / "tracks.zip"
            _create_zip(job_dir, zip_path)

            # Store the filename for the download endpoint
            _job_filenames[job_id] = zip_filename

            yield f"data: DONE:{len(mp3_files)} tracks downloaded\n\n"
        except Exception as e:
            yield f"data: ERROR: {str(e)}\n\n"
        finally:
            async with _active_jobs_lock:
                _active_jobs -= 1

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/zip/{job_id}")
async def get_zip(job_id: str):
    """Download the completed zip file."""
    zip_path = DOWNLOAD_DIR / job_id / "tracks.zip"
    if not zip_path.exists():
        raise HTTPException(status_code=404, detail="Zip not found. Download may still be in progress.")

    # Use the descriptive filename, fall back to generic
    filename = _job_filenames.get(job_id, "spotify_tracks.zip")

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
