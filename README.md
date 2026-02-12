<div align="center">

<img src="https://cdn-icons-png.freepik.com/512/189/189249.png" width="120" alt="Spotify Downloader">

# Spotify Downloader

### Grab your favorite tracks, albums & playlists at **320kbps**

[![Docker](https://img.shields.io/badge/Docker-Hub-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://hub.docker.com/r/pbdweller/spotify-downloader)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/Private-Repo-181818?style=for-the-badge&logo=github&logoColor=white)]()

<br>

<img src="https://img.shields.io/badge/MP3-320kbps-1DB954?style=flat-square" alt="320kbps">
<img src="https://img.shields.io/badge/Metadata-Included-1DB954?style=flat-square" alt="Metadata">
<img src="https://img.shields.io/badge/Album_Art-Embedded-1DB954?style=flat-square" alt="Album Art">
<img src="https://img.shields.io/badge/Lyrics-Synced-1DB954?style=flat-square" alt="Lyrics">

<br><br>

**Paste a Spotify link. Get a ZIP. That's it.**

<br>

---

</div>

## How It Works

```
Spotify Link  -->  spotdl (YouTube match)  -->  320kbps MP3  -->  ZIP  -->  Your Browser
```

1. Paste any Spotify **track**, **album**, or **playlist** URL
2. Watch real-time download progress via Server-Sent Events
3. Click download — get a timestamped ZIP with all your tracks

<br>

## Quick Start

### Docker (Recommended)

```bash
docker run -d \
  --name spotify-downloader \
  -p 8000:80 \
  -e SPOTIFY_CLIENT_ID=your_client_id \
  -e SPOTIFY_CLIENT_SECRET=your_client_secret \
  pbdweller/spotify-downloader:latest
```

Open **http://localhost:8000** and start downloading.

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
    restart: unless-stopped
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

- **Environment variables** — set `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` on the container
- **Web UI** — click the gear icon and enter them in the browser (encrypted with AES-256-GCM, stored locally)

<br>

## Features

<table>
<tr>
<td width="50%">

### Downloads
- Tracks, albums & playlists
- **320kbps** MP3 format
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

### Performance
- Real-time SSE progress streaming
- Multi-threaded downloads (4 threads)
- Auto-purge after 30 minutes
- Max 5 concurrent downloads

</td>
<td>

### Protection
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
│  │  - AES-256-GCM encrypted localStorage     │  │
│  │  - SSE real-time progress                 │  │
│  │  - One-click ZIP download                 │  │
│  └──────────────────┬────────────────────────┘  │
└─────────────────────┼───────────────────────────┘
                      │ HTTPS / HTTP
┌─────────────────────┼───────────────────────────┐
│  Docker Container   │              (port 80)    │
│  ┌──────────────────┴────────────────────────┐  │
│  │  FastAPI Backend                          │  │
│  │  - Rate limiter    - Job manager          │  │
│  │  - Auto-purge      - ZIP builder          │  │
│  ├───────────────────────────────────────────┤  │
│  │  spotdl + yt-dlp + ffmpeg                 │  │
│  │  - YouTube matching  - 320kbps encoding   │  │
│  │  - Metadata embed    - Album art          │  │
│  └───────────────────────────────────────────┘  │
│                                                 │
│  User: appuser (non-root)                       │
│  FS:   read-only + tmpfs /tmp                   │
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
