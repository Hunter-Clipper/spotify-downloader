<div align="center">

<img src="https://cdn-icons-png.freepik.com/512/189/189249.png" width="120" alt="Spotify Downloader">

# Spotify Downloader

### Grab your favorite tracks, albums & playlists in **MP3, FLAC, WAV, or OGG**

[![Docker](https://img.shields.io/badge/Docker-Hub-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://hub.docker.com/r/pbdweller/spotify-downloader)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/Private-Repo-181818?style=for-the-badge&logo=github&logoColor=white)]()

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
- **Web UI** — click the gear icon and enter them in the browser (encrypted with AES-256-GCM, stored locally). Browser credentials take priority over server env vars if both are present.

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
- AES-256-GCM encrypted credential storage
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
│  │  - AES-256-GCM encrypted localStorage     │  │
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

## Configuration

All settings are configured via environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `SPOTIFY_CLIENT_ID` | Your Spotify API Client ID | _(shared/rate-limited)_ |
| `SPOTIFY_CLIENT_SECRET` | Your Spotify API Client Secret | _(shared/rate-limited)_ |
| `DOWNLOAD_DIR` | Path inside the container where ZIPs are written | `/data/downloads` |

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
│   └── workflows/
│       └── docker-publish.yml   # CI/CD: build & push to Docker Hub on push to main
├── app/
│   ├── __init__.py
│   └── main.py              # FastAPI backend, job manager, purge loop
├── static/
│   ├── index.html           # Spotify-themed SPA with encrypted storage
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
cap_add: [NET_BIND_SERVICE]           # Only what's needed
tmpfs: [/tmp:noexec,size=2G]          # Ephemeral, non-executable temp
```

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
| **Backend** | Python 3.12 + FastAPI |
| **Download Engine** | spotdl + yt-dlp + ffmpeg |
| **Frontend** | Vanilla HTML/CSS/JS |
| **Progress** | Server-Sent Events (SSE) |
| **Encryption** | Web Crypto API (AES-256-GCM) |
| **Container** | Docker (multi-stage, slim) |

<br>

---

<div align="center">

**Built with [spotdl](https://github.com/spotDL/spotify-downloader) & [FastAPI](https://fastapi.tiangolo.com)**

<sub>For personal use only. Respect copyright and Spotify's Terms of Service.</sub>

</div>
