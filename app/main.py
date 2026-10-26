import asyncio
import logging
import os
import re
import secrets
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
from fastapi import Depends, FastAPI, Header, HTTPException, Request
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
# Enables the /api/v1 API for other apps; the API is disabled when unset.
API_KEY = os.environ.get("API_KEY", "")

# --- Configuration ---
JOB_TTL_SECONDS = 30 * 60           # 30 minutes before auto-purge
PURGE_CHECK_INTERVAL = 60           # Check for stale jobs every 60s
MAX_CONCURRENT_JOBS = 5             # Max simultaneous downloads
RATE_LIMIT_WINDOW = 60              # Rate limit window in seconds
RATE_LIMIT_MAX_REQUESTS = 10        # Max download requests per window per IP
PREVIEW_RATE_LIMIT_MAX_REQUESTS = 30  # Max preview requests per window per IP

# # Rate limit buckets - define these once and use everywhere
DOWNLOAD_BUCKET = "download"
PREVIEW_BUCKET = "preview"

ALLOWED_FORMATS = {"mp3", "flac", "wav", "ogg"}
ALLOWED_BITRATES = {"128k", "192k", "256k", "320k"}
ALLOWED_AUDIO_PROVIDERS = {"youtube-music", "youtube", "piped"}

# Statuses after which a job will never emit more progress.
TERMINAL_STATUSES = {"done", "failed"}

# Issue #14: map output formats to IANA-registered media types explicitly.
# Deriving the type from the format name produced `audio/wav` for WAV, which is
# not registered — the registered type is `audio/vnd.wave`. (`audio/wav` and
# `audio/x-wav` are common de-facto aliases if a client rejects the registered
# type.) mp3/flac/ogg already matched their registrations.
FORMAT_MEDIA_TYPES = {
    "mp3": "audio/mpeg",        # RFC 3003
    "flac": "audio/flac",       # RFC 9639
    "wav": "audio/vnd.wave",
    "ogg": "audio/ogg",         # RFC 5334
}
DEFAULT_MEDIA_TYPE = "application/octet-stream"

# Formats that ignore --bitrate
LOSSLESS_FORMATS = {"flac", "wav"}

# spotdl output patterns used to turn raw log lines into progress events
FOUND_SONGS_RE = re.compile(r"Found (\d+) songs?", re.IGNORECASE)
DOWNLOADING_RE = re.compile(r"Downloading\s+", re.IGNORECASE)
TRACK_DONE_RE = re.compile(r"Downloaded\s+|Skipping.*already exists", re.IGNORECASE)


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
    # Tracked for /api/v1 status polling
    status: str = "pending"             # pending | running | done | failed
    total: int = 0
    completed: int = 0
    tracks: list[str] = field(default_factory=list)
    error: str = ""
    result_file: str = ""               # Path relative to the job dir served by /api/v1
    finished_at: float = 0.0
    # Progress fan-out for /api/progress. `events` is the replay backlog for
    # clients that attach after the job has already started emitting, and each
    # queue in `subscribers` receives subsequent lines, then None once terminal.
    events: list[str] = field(default_factory=list)
    subscribers: list[asyncio.Queue] = field(default_factory=list)


_jobs: dict[str, Job] = {}
_active_jobs: int = 0
_active_jobs_lock = asyncio.Lock()
_rate_limits_lock = asyncio.Lock()
_rate_limits: dict[str, list[float]] = {}


# --- Shared httpx client ---
# A single AsyncClient is shared across all requests so the server avoids
# repeatedly creating/destroying connections (which caused socket exhaustion
# under load). It is created at import time and closed in lifespan().
_HTTPX_CLIENT = httpx.AsyncClient(timeout=5.0)

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
    await _HTTPX_CLIENT.aclose()


app = FastAPI(title="Spotify Downloader", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _purge_once(now: float) -> None:
    """Drop expired jobs and stale rate-limit buckets.

    Split out of _purge_loop so the expiry rules can be tested without waiting.
    """
    # Never purge a running job; finished jobs expire relative to when they finished.
    expired = [
        jid for jid, job in _jobs.items()
        if job.status != "running" and now - (job.finished_at or job.created_at) > JOB_TTL_SECONDS
    ]
    for jid in expired:
        _cleanup_job(jid)

    stale_keys = [
        key for key, timestamps in _rate_limits.items()
        if not any(now - t < RATE_LIMIT_WINDOW for t in timestamps)
    ]
    for key in stale_keys:
        del _rate_limits[key]


async def _purge_loop() -> None:
    """Background task that periodically purges expired jobs and rate limits."""
    while True:
        await asyncio.sleep(PURGE_CHECK_INTERVAL)
        _purge_once(time.time())


def _cleanup_job(job_id: str) -> None:
    """Remove all files and state for a job."""
    shutil.rmtree(DOWNLOAD_DIR / job_id, ignore_errors=True)
    _jobs.pop(job_id, None)


async def _check_rate_limit(bucket: str, ip: str, max_requests: int) -> None:
    """Enforce per-IP rate limiting for one bucket. Raises HTTPException if exceeded."""
    now = time.time()
    key = f"{bucket}:{ip}"
    async with _rate_limits_lock:
        timestamps = [t for t in _rate_limits.get(key, []) if now - t < RATE_LIMIT_WINDOW]
        _rate_limits[key] = timestamps

        if len(timestamps) >= max_requests:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded. Max {max_requests} requests per {RATE_LIMIT_WINDOW}s.",
            )
        timestamps.append(now)


UNKNOWN_CLIENT = "unknown"  # Constants


def _client_host(request: Request) -> str:
    """Best-effort client address, used as the rate limit key.

    Falls back to UNKNOWN_CLIENT for connections with no client (proxies, WebSockets).
    """
    if request.client and request.client.host:
        return request.client.host
    return UNKNOWN_CLIENT


async def _try_acquire_slot() -> bool:
    """Atomically claim a download slot. Returns False if the server is at capacity."""
    global _active_jobs
    async with _active_jobs_lock:
        if _active_jobs >= MAX_CONCURRENT_JOBS:
            return False
        _active_jobs += 1
        return True


async def _release_slot() -> None:
    global _active_jobs
    async with _active_jobs_lock:
        _active_jobs -= 1


def _publish(job: Job, event: str) -> None:
    """Record a progress line and fan it out to every attached SSE subscriber."""
    job.events.append(event)
    for queue in list(job.subscribers):
        queue.put_nowait(event)


def _end_subscribers(job: Job) -> None:
    """Wake every SSE subscriber with the end-of-stream sentinel."""
    for queue in list(job.subscribers):
        queue.put_nowait(None)


def _terminal_event(job: Job) -> str:
    """The final SSE frame for a job that has already finished."""
    if job.status == "done":
        return f"data: DONE:{len(job.tracks)}|{';;'.join(job.tracks)}\n\n"
    return f"data: ERROR: {job.error or 'Download failed.'}\n\n"


def _require_api_key(
    x_api_key: str = Header(default=""),
    authorization: str | None = Header(default=None),
) -> None:
    """Authenticate /api/v1 requests via X-API-Key or Authorization header."""
    if not API_KEY:
        raise HTTPException(status_code=503, detail="API is disabled. Set the API_KEY environment variable to enable it.")
    token = x_api_key or (authorization or "").removeprefix("Bearer ").strip()
    if not secrets.compare_digest(token.encode(), API_KEY.encode()):
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")


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


SPOTIFY_CONTENT_TYPES = ("track", "album", "playlist")


def _validate_spotify_url(url: str) -> str:
    """Validate that the URL is a Spotify track, album, or playlist link.
    Accepts both https://open.spotify.com/ and spotify: scheme links.
    """
    url = url.strip()
    is_spotify = (
        url.startswith(("https://open.spotify.com/", "http://open.spotify.com/"))
        or url.startswith("spotify:")
    )
    has_content = any(
        f"/{content_type}/" in url or f"{content_type}:" in url
        for content_type in SPOTIFY_CONTENT_TYPES
    )
    if not is_spotify or not has_content:
        raise ValueError("Invalid Spotify URL. Must be a track, album, or playlist link.")
    return url


def _normalize_spotify_url(url: str) -> str:
    """Convert a `spotify:` URI to its https://open.spotify.com/ equivalent.

    Spotify's oEmbed endpoint only accepts the https form, so previews need this
    even though spotdl accepts either. Anything that is not a track, album or
    playlist URI is returned unchanged, for the caller to reject.
    """
    if url.startswith("spotify:"):
        parts = url.split(":")
        if len(parts) >= 3 and parts[1] in SPOTIFY_CONTENT_TYPES:
            return f"https://open.spotify.com/{parts[1]}/{parts[2]}"
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
    """Classify a Spotify URL as a track, album, or playlist link.
    Handles both https://open.spotify.com/ and spotify: scheme links.
    """
    for content_type in SPOTIFY_CONTENT_TYPES:
        if f"/{content_type}/" in url or f"{content_type}:" in url:
            return content_type
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
        # Issue #24: these land in the spotdl argv, so the secret is readable
        # from /proc/<pid>/cmdline. procfs only exposes that to a caller with
        # ptrace permission (same uid or root) — i.e. someone who can already
        # exec into the container — so this is a documented, accepted
        # limitation: spotdl reads credentials only from argv or a single fixed
        # ~/.spotdl/config.json, and up to MAX_CONCURRENT_JOBS jobs with
        # different credentials run concurrently, so a shared config would race.
        # See the README security section.
        cmd += ["--client-id", cid, "--client-secret", csec]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    track_count = 0
    tracks_done = 0
    last_line = ""

    try:
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

            last_line = decoded
            yield f"LOG:{decoded}"
    finally:
        await process.wait()

    if process.returncode != 0:
        error_msg = last_line or "spotdl exited with an error"
        # Handle KeyError: 'uri' from spotipyfree (Spotify API response format change)
        if "KeyError: 'uri'" in error_msg:
            raise RuntimeError(
                "Spotify API response missing 'uri' field — spotdl could not resolve the track. "
                "The Spotify API may have changed its response format. "
                "Try using a different Spotify URL (e.g. spotify:track:...) or contact support."
            ) from None
        raise RuntimeError(f"spotdl exited with an error: {error_msg}") from None


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


def _build_job(req: DownloadRequest) -> Job:
    """Validate a download request and turn it into a Job (not yet registered)."""
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

    has_user_creds = bool(req.client_id and req.client_secret)
    return Job(
        job_id=str(uuid.uuid4()),
        urls=validated,
        format=fmt,
        bitrate=bitrate,
        structured=req.structured,
        audio_provider=audio_provider,
        client_id=req.client_id if has_user_creds else "",
        client_secret=req.client_secret if has_user_creds else "",
    )


def _register_job(job: Job) -> None:
    (DOWNLOAD_DIR / job.job_id).mkdir(parents=True, exist_ok=True)
    _jobs[job.job_id] = job


# Strong references to in-flight background jobs. asyncio only keeps weak
# references to tasks, so without this a job can be garbage collected
# mid-download (the same reason lifespan() holds on to the purge task).
_background_tasks: set[asyncio.Task] = set()


def _spawn_background_job(job: Job) -> None:
    """Run a job in the background, keeping a reference so it is not GC'd."""
    task = asyncio.create_task(_run_background_job(job))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


BUSY_DETAIL = f"Server busy — max {MAX_CONCURRENT_JOBS} concurrent downloads. Please try again shortly."


async def _execute_job(job: Job) -> AsyncIterator[str]:
    """Run spotdl for a job, update its status, and zip the results.

    The caller must hold a download slot. Yields spotdl progress lines; raises on failure.
    """
    job_dir = DOWNLOAD_DIR / job.job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    # Read the credentials once, then clear them from memory.
    cid, csec = job.client_id, job.client_secret
    job.client_id = ""
    job.client_secret = ""

    job.status = "running"
    try:
        async for line in _run_spotdl(
            job.urls, job_dir, job.format, job.bitrate, job.structured, job.audio_provider, cid, csec
        ):
            if line.startswith("TOTAL:"):
                job.total = int(line.removeprefix("TOTAL:"))
            elif line.startswith("TRACK_DONE:"):
                job.completed += 1
            yield line

        music_files = _find_music_files(job_dir, job.format, job.structured)
        if not music_files:
            raise RuntimeError("No tracks were downloaded.")

        job.zip_filename = _build_zip_filename(music_files, job.urls)
        _create_zip(music_files, job_dir, job_dir / "tracks.zip")

        job.tracks = [f.stem for f in sorted(music_files, key=lambda p: p.name)]
        job.completed = len(music_files)
        job.total = max(job.total, job.completed)  # spotdl omits "Found N songs" for single tracks
        # A single track is served as-is; anything more is served as the zip.
        result = music_files[0] if len(music_files) == 1 else job_dir / "tracks.zip"
        job.result_file = str(result.relative_to(job_dir))
        job.status = "done"
    except Exception as e:
        job.status = "failed"
        job.error = str(e)
        raise
    finally:
        # e.g. the SSE client disconnected mid-download, closing this generator
        if job.status == "running":
            job.status = "failed"
            job.error = "Download was interrupted."
        job.finished_at = time.time()


@app.post("/api/download")
async def download(req: DownloadRequest, request: Request):
    """Start a download job and return the job ID."""
    # Validate first: invalid requests must NOT consume the rate limit
    job = _build_job(req)

    # Rate-limit AFTER validation so invalid requests cannot exhaust the limit.
    # /api/v1/jobs shares this bucket, so the configured "max requests per
    # window per IP" means the same thing on both surfaces.
    await _check_rate_limit(
        DOWNLOAD_BUCKET, _client_host(request), RATE_LIMIT_MAX_REQUESTS
    )

    # Acquire a slot atomically; the job starts immediately (not when the SSE
    # stream opens) so web jobs are not deferred until the client connects.
    if not await _try_acquire_slot():
        raise HTTPException(status_code=503, detail=BUSY_DETAIL)

    _register_job(job)
    job.status = "running"
    _spawn_background_job(job)
    return {"job_id": job.job_id}


@app.get("/api/progress/{job_id}")
async def progress(job_id: str):
    """SSE endpoint streaming progress for a job already started by /api/download.

    The job itself runs in the background (started by /api/download), so this
    endpoint subscribes to its progress instead of running it, and therefore
    does not acquire a download slot of its own.
    """
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    async def event_stream() -> AsyncIterator[str]:
        # Subscribe before snapshotting the backlog, with no await in between,
        # so a client that attaches mid-job can neither miss nor duplicate an
        # event: everything already emitted is replayed, then the live queue
        # takes over.
        queue: asyncio.Queue = asyncio.Queue()
        job.subscribers.append(queue)
        backlog = list(job.events)
        already_finished = job.status in TERMINAL_STATUSES

        try:
            for event in backlog:
                yield f"data: {event}\n\n"
            if already_finished:
                yield _terminal_event(job)
                return
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield f"data: {event}\n\n"
            yield _terminal_event(job)
        finally:
            if queue in job.subscribers:
                job.subscribers.remove(queue)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/preview")
async def preview(req: PreviewRequest, request: Request):
    """Fetch metadata from Spotify's oEmbed API (no auth needed)."""
    url = _normalize_spotify_url(req.url.strip())
    if not url or "open.spotify.com" not in url:
        raise HTTPException(status_code=400, detail="Invalid Spotify URL.")

    # Rate-limit AFTER validation so invalid URLs cannot exhaust the budget.
    await _check_rate_limit(
        PREVIEW_BUCKET, _client_host(request), PREVIEW_RATE_LIMIT_MAX_REQUESTS
    )

    try:
        resp = await _HTTPX_CLIENT.get("https://open.spotify.com/oembed", params={"url": url})
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


# --- External API (/api/v1) for other apps ---
# Jobs start immediately in the background; callers poll for status, then fetch the file.


def _job_status(job: Job) -> dict:
    return {
        "job_id": job.job_id,
        "status": job.status,
        "urls": job.urls,
        "format": job.format,
        "total": job.total,
        "completed": job.completed,
        "tracks": job.tracks,
        "error": job.error or None,
        "filename": _result_filename(job) if job.status == "done" else None,
        "file_url": f"/api/v1/jobs/{job.job_id}/file" if job.status == "done" else None,
    }


def _result_filename(job: Job) -> str:
    result = Path(job.result_file)
    return result.name if result.suffix != ".zip" else (job.zip_filename or "spotify_tracks.zip")


def _get_api_job(job_id: str) -> Job:
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


async def _run_background_job(job: Job) -> None:
    """Run a job to completion, fanning its progress out to SSE subscribers."""
    try:
        async for line in _execute_job(job):
            _publish(job, line)
    except Exception:
        # _execute_job records the failure on the job itself; the terminal SSE
        # frame is derived from job.status/job.error by _terminal_event.
        logger.exception(f"Job {job.job_id} failed")
    finally:
        _end_subscribers(job)
        await _release_slot()


@app.post("/api/v1/jobs", status_code=202, dependencies=[Depends(_require_api_key)])
async def api_create_job(req: DownloadRequest, request: Request):
    """Validate the request and start downloading in the background."""
    job = _build_job(req)

    # Shares the download bucket with /api/download, so the REST surface is
    # rate limited rather than relying on the 503 slot check alone.
    await _check_rate_limit(
        DOWNLOAD_BUCKET, _client_host(request), RATE_LIMIT_MAX_REQUESTS
    )

    if not await _try_acquire_slot():
        raise HTTPException(status_code=503, detail=BUSY_DETAIL)

    _register_job(job)
    job.status = "running"
    _spawn_background_job(job)
    return _job_status(job)


@app.get("/api/v1/jobs/{job_id}", dependencies=[Depends(_require_api_key)])
async def api_get_job(job_id: str):
    return _job_status(_get_api_job(job_id))


@app.get("/api/v1/jobs/{job_id}/file", dependencies=[Depends(_require_api_key)])
async def api_get_file(job_id: str):
    """Return the single audio file, or a zip when the job produced several tracks."""
    job = _get_api_job(job_id)
    if job.status != "done":
        raise HTTPException(status_code=409, detail=f"Job is not finished (status: {job.status}).")

    path = DOWNLOAD_DIR / job_id / job.result_file
    if not path.exists():
        raise HTTPException(status_code=404, detail="File no longer exists.")

    media_type = (
        "application/zip"
        if path.suffix == ".zip"
        else FORMAT_MEDIA_TYPES.get(job.format, DEFAULT_MEDIA_TYPE)
    )
    return FileResponse(path, media_type=media_type, filename=_result_filename(job))


@app.delete("/api/v1/jobs/{job_id}", dependencies=[Depends(_require_api_key)])
async def api_delete_job(job_id: str):
    job = _get_api_job(job_id)
    if job.status == "running":
        raise HTTPException(status_code=409, detail="Job is still running.")
    _cleanup_job(job_id)
    return {"status": "deleted"}
