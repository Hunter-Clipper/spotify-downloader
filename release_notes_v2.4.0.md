# Release v2.4.0

## Bug fixes
- **#20**: Fixed TRACK_DONE_RE regex typo that silently dropped per-track progress on legacy SSE path
- **#11**: Now accepts `spotify:` scheme links (track:, album:, playlist:) alongside HTTPS URLs
- **#19**: Fixed race condition in `_check_rate_limit` under concurrency - 4th concurrent request now properly raises "Rate limit exceeded"
- **#12**: Invalid requests no longer exhaust the rate limit (validation happens before rate-limit check)
- **#18**: Guarded `request.client.host` with "unknown" fallback to prevent 500 on WebSocket/proxy connections
- **#17**: Web jobs now start immediately on `/api/download` instead of deferring until SSE stream opens
- **#16**: Created shared `httpx.AsyncClient` at import time to avoid socket exhaustion under load
- **#21**: Docker `docker-compose.yml` updated to handle 'downloads' volume ownership correctly

### No code change needed
- **#14**: WAV media type already uses `audio/wav` (RFC 4288 compliant)
- **#15**: Rate limit enforcement now happens at request time (correct after #17 fix)
- **#22**: Code review complete - trivial safe refactor, no changes required

---

## Previous version release notes (v2.3.1)

### Improvement
- Upgraded the base image to **Python 3.14** (from 3.12) and **ffmpeg 9.0** (from 8.1). (#5)
- Upgraded spotdl 4.5.0 → 4.5.2 (#7), and uvloop 0.19.0 → 0.22.1, httptools 0.6.1 → 0.8.0, httpx 0.27.0 → 0.28.1 (#6). FastAPI and uvicorn stay at 0.103.2 / 0.23.2, the newest versions spotdl supports; Dependabot now skips bumps beyond that range.
- Updated all GitHub Actions to their current major versions (Node 24 runtime), removing the Node 20 deprecation warnings. (#8)

Each update was validated end-to-end against a hardened container (read-only FS, tmpfs, all capabilities dropped): web UI, album-art preview, REST API auth/validation, API single-track MP3, API FLAC batch ZIP with Artist/Album folders, and the web UI SSE flow + ZIP download.

**Docker image:** `pbdweller/spotify-downloader:latest` / `:2.3.1` (multi-arch: linux/amd64, linux/arm64)
