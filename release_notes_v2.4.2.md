# Release v2.4.2

## Bug fixes

- **#21 — Docker downloads volume ownership:** The `downloads` named volume is now chowned to `appuser` at container start, via a new `docker-entrypoint.sh` that runs as root, fixes ownership, then drops privileges to uid 999 before exec'ing uvicorn. Previously a pre-existing root-owned volume made the writability probe fail, so downloads silently fell back to `/tmp` and were lost on restart. The container no longer runs the app as root, and `docker-compose.yml` no longer declares `ports` and `environment` twice — that duplicate-key error stopped the file parsing at all.
- **#14 — WAV media type:** `/api/v1/jobs/{id}/file` now maps each output format to its media type through an explicit table instead of deriving it from the format name. WAV previously produced `audio/wav`, which is not a registered media type; it is now `audio/vnd.wave`. mp3, flac and ogg were already correct.
- **Web UI progress stream (regression from the v2.4.0 job-start change):** `/api/progress/{id}` returned `409 Job has already been started` for every job, because jobs are started by `/api/download` and therefore never sit in the `pending` state the endpoint required. The web UI got no progress, no completion, and no download button. The endpoint now subscribes to the already-running job instead of refusing to attach, and replays progress emitted before the client connected so no early `TOTAL:` / `TRACK_START:` event is lost.
- **`spotify:` links in the web UI:** the frontend link parser only accepted `open.spotify.com` URLs, so the `spotify:` support added in v2.4.1 was unreachable from the UI.
- **Background job lifetime:** `/api/download` started its job with an unreferenced `asyncio.create_task`, which asyncio may garbage-collect mid-download. Both the web and REST paths now use a single helper that holds a strong reference.
- **Concurrency slot accounting:** attaching to the progress stream no longer acquires a second download slot, which had halved the effective `MAX_CONCURRENT_JOBS`.

## Verification

Validated against a hardened container (`read-only` rootfs, tmpfs, all capabilities dropped except those the entrypoint needs), with a stub `spotdl` to exercise the flow without network access:

- `docker compose config` parses; container starts healthy; `/data/downloads` owned by `999:999`; pid 1 runs as uid 999 with `CapPrm`/`CapEff` both zero; `DOWNLOAD_DIR` resolves to `/data/downloads` instead of falling back to `/tmp`.
- SSE: full frame sequence (`TOTAL`, `TRACK_START`, `TRACK_DONE`, `LOG`, `DONE`) both when attaching immediately and when attaching after the job finished (backlog replay).
- REST API: create → poll → fetch file; ZIP delivered as `application/zip`; missing API key rejected with `401`.
- Media types per format: `audio/vnd.wave`, `audio/mpeg`, `audio/flac`, `audio/ogg`, `application/zip`.
- Concurrency: 7 simultaneous downloads → exactly 5 accepted and 2 rejected with `503`; a fresh request succeeds after the queue drains, so no slots leak.

**Docker image:** `pbdweller/spotify-downloader:latest` / `:2.4.2` (multi-arch: linux/amd64, linux/arm64)
