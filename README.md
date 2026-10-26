<div align="center">

<img src="https://cdn-icons-png.freepik.com/512/189/189249.png" width="120" alt="Spotify Downloader">

# Spotify Downloader

### Grab your favorite tracks, albums & playlists in **MP3, FLAC, WAV, or OGG**
**Maintained by**: Hunter (@Hunter-Clipper) | [GitHub](https://github.com/Hunter-Clipper/spotify-downloader)


[![Docker](https://img.shields.io/badge/Docker-Hub-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://hub.docker.com/r/pbdweller/spotify-downloader)
[![Build & Push to Docker Hub](https://github.com/Hunter-Clipper/spotify-downloader/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/Hunter-Clipper/spotify-downloader/actions/workflows/docker-publish.yml)
[![Python](https://img.shields.io/badge/Python-3.14-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)

<br>

<img src="https://img.shields.io/badge/MP3%20%7C%20FLAC%20%7C%20WAV%20%7C%20OGG-1DB954?style=flat-square" alt="Formats">
<img src="https://img.shields.io/badge/Batch_Downloads-1DB954?style=flat-square" alt="Batch">
<img src="https://img.shields.io/badge/Metadata-Included-1DB954?style=flat-square" alt="Metadata">
<img src="https://img.shields.io/badge/Album_Art-Embedded-1DB954?style=flat-square" alt="Album Art">
<img src="https://img.shields.io/badge/Lyrics-Synced-1DB954?style=flat-square" alt="Lyrics">

<br><br>

**Paste your Spotify links. Pick your format. Get a ZIP. That's it.**

<br>

---

</div>

## How It Works

```
Spotify Links  -->  spotdl (YouTube match)  -->  MP3/FLAC/WAV/OGG  -->  ZIP  -->  Your Browser
```

1. Paste any Spotify **track**, **album**, or **playlist** URLs (one per line for batch)
2. Choose your **format** (MP3, FLAC, WAV, OGG) and **bitrate** (128k–320k)
3. Watch real-time per-track progress via Server-Sent Events
4. Click download — get a timestamped ZIP with all your tracks

<br>

## Quick Start

### Docker (Recommended)

```bash
docker run -d \
  --name spotify-downloader \
  -p 8000:80 \
  -e SPOTIFY_CLIENT_ID=your_client_id \
  -e SPOTIFY_CLIENT_SECRET=your_client_secret \
  -v ./downloads:/data/downloads \
  pbdweller/spotify-downloader:latest
```

Open **http://localhost:8000** and start downloading.

> The `-v ./downloads:/data/downloads` flag persists completed ZIPs to your host. Omit it for ephemeral in-container storage (downloads still auto-purge after 30 min either way). You can also set a custom path via the `DOWNLOAD_DIR` env var.

### Docker Compose

```yaml
services:
  spotify-downloader:
    image: pbdweller/spotify-downloader:latest
    ports:
      - "8000:80"
    environment:
      - SPOTIFY_CLIENT_ID=${SPOTIFY_CLIENT_ID}
      - SPOTIFY_CLIENT_SECRET=${SPOTIFY_CLIENT_SECRET}
    volumes:
      - downloads:/data/downloads
    restart: unless-stopped

volumes:
  downloads:
```

```bash
docker compose up -d
```

<br>

## Spotify API Credentials

> **Required** to avoid rate limits on Spotify's API.

| Step | Action |
|------|--------|
| 1 | Go to [**developer.spotify.com/dashboard**](https://developer.spotify.com/dashboard) |
| 2 | Create a new app (any name works) |
| 3 | Copy the **Client ID** and **Client Secret** |
| 4 | Pass them as env vars **or** enter them in the web UI settings |

**Two ways to provide credentials:**

- **Environment variables** — set `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` on the container. When set, the settings panel displays a confirmation notice so you know downloads will work without any browser-side configuration.
- **Web UI** — click the gear icon and enter them in the browser (obfuscated with AES-256-GCM and stored in `localStorage` — see [Credential handling](#credential-handling)). Browser credentials take priority over server env vars if both are present.

<br>

## Features

<table>
<tr>
<td width="50%">

### Downloads
- Tracks, albums & playlists
- **Batch downloads** — multiple URLs at once
- **MP3, FLAC, WAV, OGG** format selection
- Configurable bitrate (128k–320k)
- Organize by **Artist/Album** folders
- Full metadata & album art
- Synced lyrics when available
- Smart ZIP naming with timestamps

</td>
<td width="50%">

### Security
- Credential storage obfuscated with AES-256-GCM (see [Credential handling](#credential-handling))
- Non-root Docker container
- Read-only filesystem
- All Linux capabilities dropped
- Credentials never persisted on server

</td>
</tr>
<tr>
<td>

### UX
- **Album art preview** on paste (Spotify oEmbed)
- **Per-track progress** with determinate progress bar
- **Drag & drop** Spotify URLs onto the page
- **Download history** with track context, re-download, per-item removal, and clear all
- **Toast notifications** + browser notifications (background tab)
- **Completion chime** (Web Audio API, mute toggle)
- **Mobile-responsive** layout with `prefers-reduced-motion` support
- Static **size estimate** per track based on format + bitrate
- **Audio source selector** — YouTube Music, YouTube, or Piped
- **Server credentials notice** — settings panel confirms when env var creds are active
- **Clear All Local Data** — wipes saved credentials, history, and settings in one click

</td>
<td>

### Performance & Protection
- Real-time SSE progress streaming
- Multi-threaded downloads (4 threads)
- Auto-purge after 30 minutes
- Max 5 concurrent downloads
- Per-IP rate limiting (10 req/min)
- Concurrent job cap
- Input validation & sanitization
- No privilege escalation (`no-new-privileges`)

</td>
</tr>
</table>

<br>

## Architecture

```
┌─────────────────────────────────────────────────┐
│  Browser                                        │
│  ┌───────────────────────────────────────────┐  │
│  │  Spotify-themed Web UI                    │  │
│  │  - Multi-URL batch input                  │  │
│  │  - Format/bitrate selection               │  │
│  │  - Album art preview (oEmbed)             │  │
│  │  - Per-track SSE progress                 │  │
│  │  - Drag & drop, toasts, sound FX          │  │
│  │  - AES-GCM obfuscated localStorage        │  │
│  └──────────────────┬────────────────────────┘  │
└─────────────────────┼───────────────────────────┘
                      │ HTTPS / HTTP
┌─────────────────────┼───────────────────────────┐
│  Docker Container   │              (port 80)    │
│  ┌──────────────────┴────────────────────────┐  │
│  │  FastAPI Backend                          │  │
│  │  - Job dataclass   - Multi-URL support    │  │
│  │  - Rate limiter    - Format/bitrate opts  │  │
│  │  - Auto-purge      - Preview (oEmbed)     │  │
│  ├───────────────────────────────────────────┤  │
│  │  spotdl + yt-dlp + ffmpeg                 │  │
│  │  - YouTube matching  - Multi-format enc   │  │
│  │  - Metadata embed    - Album art & lyrics │  │
│  └───────────────────────────────────────────┘  │
│                                                 │
│  User: appuser (non-root)                       │
│  FS:   read-only + tmpfs /tmp                   │
│         + volume  /data/downloads               │
│  Caps: all dropped + NET_BIND_SERVICE           │
└─────────────────────────────────────────────────┘
```

<br>

## REST API

Other apps can trigger downloads through `/api/v1`. Downloads run in the background — create a job, poll its status, then fetch the file.

**Enable it** by setting `API_KEY` on the container (e.g. `-e API_KEY=$(openssl rand -hex 32)`). Every request must include the key as `X-API-Key: <key>` or `Authorization: Bearer <key>`. With no `API_KEY` set, all `/api/v1` endpoints return `503`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/jobs` | Start a download. Returns `202` with the job status |
| `GET` | `/api/v1/jobs/{job_id}` | Job status: `running`, `done`, or `failed` |
| `GET` | `/api/v1/jobs/{job_id}/file` | The result — the audio file for a single track, a ZIP for multiple tracks |
| `DELETE` | `/api/v1/jobs/{job_id}` | Delete a finished job's files early |

**Request body** for `POST /api/v1/jobs` (all fields optional except a URL):

```json
{
  "url": "https://open.spotify.com/track/...",
  "urls": ["https://open.spotify.com/album/...", "https://open.spotify.com/playlist/..."],
  "format": "mp3",
  "bitrate": "320k",
  "structured": false,
  "audio_provider": "youtube-music",
  "client_id": "",
  "client_secret": ""
}
```

**Status response:**

```json
{
  "job_id": "93f38236-37fa-42ab-ba79-220117ee3046",
  "status": "done",
  "urls": ["https://open.spotify.com/track/..."],
  "format": "mp3",
  "total": 1,
  "completed": 1,
  "tracks": ["Rick Astley - Never Gonna Give You Up"],
  "error": null,
  "filename": "Rick Astley - Never Gonna Give You Up.mp3",
  "file_url": "/api/v1/jobs/93f38236-37fa-42ab-ba79-220117ee3046/file"
}
```

**Example:**

```bash
KEY=your_api_key
JOB=$(curl -s -X POST http://localhost:8000/api/v1/jobs \
  -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"url": "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT"}' | jq -r .job_id)

# Poll until done
while [ "$(curl -s -H "X-API-Key: $KEY" http://localhost:8000/api/v1/jobs/$JOB | jq -r .status)" = "running" ]; do sleep 3; done

curl -OJ -H "X-API-Key: $KEY" http://localhost:8000/api/v1/jobs/$JOB/file
```

**Errors:** `400` invalid URL/option · `401` bad API key · `404` unknown or expired job · `409` job not finished (file) or still running (delete) · `503` API disabled or server at the concurrent download limit (retry later).

Finished jobs are purged 30 minutes after they complete. API requests share the `MAX_CONCURRENT_JOBS` limit with the web UI but are not subject to the per-IP rate limit.

<br>

## Configuration

All settings are configured via environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `SPOTIFY_CLIENT_ID` | Your Spotify API Client ID | _(shared/rate-limited)_ |
| `SPOTIFY_CLIENT_SECRET` | Your Spotify API Client Secret | _(shared/rate-limited)_ |
| `DOWNLOAD_DIR` | Path inside the container where ZIPs are written | `/data/downloads` |
| `API_KEY` | Enables the [REST API](#rest-api) for other apps; callers must send this key | _(API disabled)_ |

Internal defaults (configurable in `app/main.py`):

| Setting | Value | Description |
|---------|-------|-------------|
| `JOB_TTL_SECONDS` | `1800` | Auto-delete downloads after 30 min |
| `MAX_CONCURRENT_JOBS` | `5` | Simultaneous download limit |
| `RATE_LIMIT_MAX_REQUESTS` | `10` | Max requests per IP per minute |

<br>

## Project Structure

```
spotify-downloader/
├── .github/
│   ├── dependabot.yml           # Automated dependency update PRs (yt-dlp/spotdl checked daily)
│   └── workflows/
│       └── docker-publish.yml   # CI/CD: build & push to Docker Hub, sync Hub README; build-only check on PRs
├── app/
│   ├── __init__.py
│   └── main.py              # FastAPI backend, job manager, purge loop
├── static/
│   ├── index.html           # Spotify-themed SPA with obfuscated storage
│   └── favicon.png
├── Dockerfile               # Multi-stage, hardened, non-root
├── docker-compose.yml       # Production-ready with security opts
├── requirements.txt
└── .dockerignore
```

<br>

## Security Hardening

This image follows Docker security best practices:

```dockerfile
USER appuser                          # Non-root user
```
```yaml
security_opt: [no-new-privileges]     # No privilege escalation
read_only: true                       # Immutable root filesystem
cap_drop: [ALL]                       # All capabilities dropped
cap_add: [NET_BIND_SERVICE]           # Bind :80
cap_add: [CHOWN, SETUID, SETGID]      # Entrypoint: chown the downloads volume,
                                      # then drop to appuser (cleared on that switch)
tmpfs: [/tmp:noexec,size=2G]          # Ephemeral, non-executable temp
tmpfs: [/home/appuser:uid=999,...]    # Writable home for spotdl config + yt-dlp/Deno caches
```

### Credential handling

Two things are worth stating plainly, because the UI and earlier versions of this
README overstated them:

- **Browser storage is obfuscation, not encryption.** Credentials entered in the
  web UI are AES-256-GCM encrypted before being written to `localStorage`, but
  the key is generated and stored in `localStorage` right next to the ciphertext
  (`sp_creds_key` alongside `sp_creds_enc`). Anything that can read
  `localStorage` — XSS, a malicious extension, or anyone with access to the
  browser profile — can therefore decrypt them; the layer only defeats casual
  inspection. Deriving the key from a passphrase would make it real protection,
  at the cost of prompting on every use.
- **The Spotify client secret is visible inside the container.** Credentials are
  passed to spotdl as `--client-id` / `--client-secret` arguments, so the secret
  appears in `/proc/<pid>/cmdline` while a download runs. procfs only exposes
  another process's cmdline to a caller with ptrace permission (same uid, or
  root) — in practice someone who can already `docker exec` into the container,
  and who therefore already has full access to it. spotdl reads credentials only
  from argv or a single fixed `~/.spotdl/config.json`, and up to
  `MAX_CONCURRENT_JOBS` jobs with *different* credentials run concurrently, so a
  shared config file would race. This is accepted rather than fixed.

Credentials are still never persisted server-side: they are read from the
request, passed to spotdl, and cleared from the job immediately afterwards.

<br>

## Roadmap

> Possible future features — no guarantees, no timelines. Ideas from various user personas.

| Category | Feature Idea |
|----------|-------------|
| **DJ / Producer** | BPM & key detection, cue point export, waveform preview, stems separation |
| **Privacy** | Tor/proxy support, no-analytics mode, ephemeral mode (auto-delete on download) |
| **Sysadmin** | Prometheus metrics endpoint, admin dashboard, configurable quotas per user, LDAP/SSO auth |
| **Power User** | CLI mode (API-only, no UI), custom output templates, ffmpeg post-processing hooks, queue priority |
| **Sharer** | Shareable download links (time-limited), collaborative playlists, QR code for mobile download |
| **Accessibility** | Full keyboard navigation, screen reader ARIA labels, high contrast theme |
| **Integration** | Webhook on completion, Telegram/Discord bot, Plex/Jellyfin auto-import |

<br>

## Changelog

### Unreleased

- **Fix (#23):** Removed the unauthenticated `DELETE /api/cleanup/{job_id}` endpoint — it was undocumented, unused by the web UI, and deleted a running job's files out from under spotdl. `DELETE /api/v1/jobs/{job_id}` covers cleanup and refuses while a job is running.
- **Fix (#25):** `/api/preview` normalises `spotify:` URIs to their `https://open.spotify.com/` form before calling oEmbed, so previews now work for the same links downloads accept.
- **Fix (#15):** Rate limiting is no longer limited to `/api/download`. The limiter now takes a bucket and a ceiling: `/api/v1/jobs` shares the download bucket, so "max requests per window per IP" means the same thing on both surfaces, and `/api/preview` gets its own ceiling (30/min per IP) since the UI calls it from a debounced handler.
- **Fix (#26):** The README and the in-app security panel now describe browser credential storage honestly — the AES-256-GCM key is stored beside the ciphertext, so it is obfuscation, not protection against local access.
- **Fix (#24):** Documented the residual credential exposure in the README: the Spotify client secret is visible in the spotdl argv inside the container. Accepted rather than fixed, for the reasons given in [Credential handling](#credential-handling).
- **New (#27):** Added a pytest suite covering the URL helpers, job building, the media-type table, the rate limiter and the SSE progress path, plus a CI job that gates the image build on it.
- **Docs (#28):** Collapsed the duplicated `v2.4.1` changelog entry.
- **Docs (#29):** Added an MIT `LICENSE` file matching the existing SPDX headers.

### v2.4.2

- **Fix (#21):** The `downloads` named volume is now chowned to `appuser` at container start. A pre-existing root-owned volume made the writability probe fail, so downloads silently fell back to `/tmp` and were lost on restart. `docker-compose.yml` also declared `ports` and `environment` twice, which stopped the file parsing at all.
- **Fix (#14):** `/api/v1/jobs/{id}/file` maps each output format to its media type explicitly instead of deriving it from the format name. WAV previously produced the unregistered `audio/wav`; it is now `audio/vnd.wave`.
- **Fix:** The web UI progress stream was broken — `/api/progress/{id}` always returned `409` because jobs are started by `/api/download` and so are never `pending`. It now subscribes to the running job and replays progress emitted before the client attached.
- **Fix:** `spotify:` URIs are no longer filtered out by the frontend link parser, so the `spotify:` support added in v2.4.1 now works from the web UI.
- **Fix:** Background jobs are held by a strong reference, so asyncio can no longer garbage-collect a download mid-flight.
- **Fix:** Attaching to the progress stream no longer consumes a second concurrency slot, which had halved the effective `MAX_CONCURRENT_JOBS`.

### v2.4.1

- Re-release of the v2.4.0 fixes — cut from the same commit, no code differences.

### v2.4.0

- **Fix:** `_check_rate_limit` race condition under concurrency — now properly raises "Rate limit exceeded" on the 4th concurrent request.
- **Fix:** Now accepts `spotify:` scheme links (`track:`, `album:`, `playlist:`) alongside HTTPS URLs.
- **Fix:** Fixed `TRACK_DONE_RE` regex typo that silently dropped per-track progress on the legacy SSE path.
- **Fix:** Guarded `request.client.host` with an "unknown" fallback to prevent 500 on WebSocket/proxy connections.
- **Fix:** Web jobs now start immediately on `/api/download` instead of deferring until the SSE stream opens.
- **Fix:** Invalid requests no longer exhaust the rate limit — validation happens before the rate-limit check.
- **Fix:** Created shared `httpx.AsyncClient` at import time to avoid socket exhaustion under load.
- **Fix:** Docker `docker-compose.yml` updated to handle the `downloads` volume ownership correctly.

### v2.3.1
- **Improvement:** Upgraded the base image to Python 3.14 (from 3.12) and ffmpeg to 9.0 (from 8.1).
- **Improvement:** Upgraded spotdl 4.5.0 → 4.5.2, uvloop 0.19.0 → 0.22.1, httptools 0.6.1 → 0.8.0, and httpx 0.27.0 → 0.28.1. FastAPI and uvicorn stay at 0.103.2 / 0.23.2, the newest versions spotdl supports; Dependabot now skips bumps beyond that range.
- **Improvement:** Updated all GitHub Actions to their current major versions (Node 24 runtime), removing the Node 20 deprecation warnings.

### v2.3.0
- **New:** REST API (`/api/v1/jobs`) so other apps can trigger downloads — background jobs with status polling, direct audio file (single track) or ZIP delivery, protected by the `API_KEY` env var. See [REST API](#rest-api).
- **Fix:** Long-running downloads are no longer purged mid-download; jobs now expire 30 minutes after they finish.
- **Improvement:** spotdl failures now report spotdl's last output line instead of a generic error.
- **Fix:** Downloads failing with `YT-DLP download error` / `HTTP Error 403` — added the Deno JS runtime (2.9.7) to the image, which yt-dlp now requires to solve YouTube challenges, and upgraded yt-dlp 2026.3.17 → 2026.8.19.
- **Fix:** `docker-compose.yml` with `read_only: true` crashed spotdl on first run (`Read-only file system: .../config.json`). `/home/appuser` is now a tmpfs owned by `appuser`, whose UID/GID is pinned to 999.
- **New:** Dependabot opens PRs for new dependency versions — Python packages daily (yt-dlp and spotdl in their own PRs), Docker base images and GitHub Actions weekly. Pull requests now get a build-only CI check before merging.
- **New:** Release tags publish versioned Docker images (e.g. `pbdweller/spotify-downloader:2.3.0`), and the Docker Hub overview now syncs automatically from this README.

### v2.2.2
- **Improvement:** Simplified backend and frontend code — deduplicated repeated validation, file-globbing, and log-parsing logic in `app/main.py`, and collapsed duplicated fetch/status and SSE-handling blocks in the frontend into named helpers. No behavior changes.

### v2.2.1
- **Fix:** Upgraded spotdl 4.4.3 → 4.5.0. In 4.4.3 the YouTube Music connectivity check was a hard error that blocked all downloads regardless of audio provider. In 4.5.0 it is a warning only — downloads continue.
- **Fix:** Pinned yt-dlp to 2026.3.17 (latest). The version bundled with spotdl 4.4.3 was ~2 years old and failed against current YouTube.

### v2.2.0
- **New:** Audio source selector — choose between **YouTube Music** (default), **YouTube**, or **Piped** directly in the UI. Fixes "blocked by YouTube Music" errors by switching to an alternative source without needing a VPN.

### v2.1.1
- **Improvement:** Replaced apt-installed `ffmpeg` with static binaries from `mwader/static-ffmpeg:8.1` — eliminates the entire apt layer and all shared codec libraries, significantly reducing image size. Also upgrades ffmpeg to 8.1.
- **Improvement:** Replaced `uvicorn[standard]` with explicit `uvicorn` + `uvloop` + `httptools`, dropping unused `websockets` and `watchfiles` dependencies.

### v2.1.0
- **New:** `DOWNLOAD_DIR` environment variable — map downloads to any host path via `-v ./downloads:/data/downloads` (default `/data/downloads`, no longer stored in RAM)
- **New:** Server credentials notice — settings panel shows a confirmation banner when `SPOTIFY_CLIENT_ID`/`SECRET` are configured via Docker env vars
- **New:** Clear All Local Data button — wipes saved credentials, download history, and all browser settings in one click
- **New:** GitHub Actions CI/CD — image automatically built and pushed to Docker Hub on every push to `main` (multi-arch: `linux/amd64` + `linux/arm64`)
- **Fix:** Race condition where more than `MAX_CONCURRENT_JOBS` downloads could start simultaneously
- **Fix:** `_rate_limits` memory leak — stale IP entries now pruned every 60 s
- **Fix:** Deprecated FastAPI startup event replaced with `lifespan` context manager
- **Fix:** Spotify URL validation now rejects non-`https://` schemes

### v2.0.2
- **Fix:** Download history now shows track names, album/playlist titles, and track counts instead of just "N tracks downloaded"
- **New:** Per-item remove button on each history entry
- **New:** Clear All button to wipe download history

### v2.0.0
- Multi-format downloads (MP3, FLAC, WAV, OGG) with configurable bitrate
- Batch URL support (multiple links at once)
- Album art preview via Spotify oEmbed
- Per-track SSE progress with determinate progress bar
- Drag & drop, toast notifications, browser notifications, completion chime
- AES-256-GCM encrypted credential storage in browser
- Session download history with re-download
- Mobile-responsive layout with `prefers-reduced-motion` support

### v1.0.0
- Initial release — single-track MP3 downloads with basic web UI

<br>

## Tech Stack

| Component | Technology |
|-----------|-----------|
| **Backend** | Python 3.14 + FastAPI |
| **Download Engine** | spotdl + yt-dlp + Deno + ffmpeg |
| **Frontend** | Vanilla HTML/CSS/JS |
| **Progress** | Server-Sent Events (SSE) |
| **Credential storage** | Web Crypto API (AES-256-GCM) in `localStorage` |
| **Container** | Docker (multi-stage, slim) |

<br>

---

<div align="center">

**Built with [spotdl](https://github.com/spotDL/spotify-downloader) & [FastAPI](https://fastapi.tiangolo.com)**

<sub>For personal use only. Respect copyright and Spotify's Terms of Service.</sub>

</div>
