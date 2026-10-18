# Release v2.4.1

## Bug fixes

- **TRACK_DONE_RE regex fix:** Fixed regex typo that was silently dropping per-track progress on the legacy SSE path
- **Spotify URL scheme:** Now accepts `spotify:` scheme links (`track:`, `album:`, `playlist:`) alongside HTTPS URLs
- **Rate limit enforcement:** Fixed race condition under concurrency - 4th concurrent request now properly raises "Rate limit exceeded"
- **Request validation:** Invalid requests no longer exhaust the rate limit (validation happens before rate-limit check)
- **Client host guard:** Guarded `request.client.host` with "unknown" fallback to prevent 500 on WebSocket/proxy connections
- **Shared httpx client:** Created shared `httpx.AsyncClient` at import time to avoid socket exhaustion under load
- **Docker volume ownership:** Updated `docker-compose.yml` to handle the `downloads` volume ownership correctly

### Previous version release notes (v2.4.0)

- **Fix:** `_check_rate_limit` race condition under concurrency — now properly raises "Rate limit exceeded" on the 4th concurrent request.
- **Fix:** Now accepts `spotify:` scheme links (`track:`, `album:`, `playlist:`) alongside HTTPS URLs.
- **Fix:** Fixed `TRACK_DONE_RE` regex typo that silently dropped per-track progress on the legacy SSE path.
- **Fix:** Guarded `request.client.host` with an "unknown" fallback to prevent 500 on WebSocket/proxy connections.
- **Fix:** Web jobs now start immediately on `/api/download` instead of deferring until the SSE stream opens.
- **Fix:** Invalid requests no longer exhaust the rate limit — validation happens before the rate-limit check.
- **Fix:** Created shared `httpx.AsyncClient` at import time to avoid socket exhaustion under load.
- **Fix:** Docker `docker-compose.yml` updated to handle the `downloads` volume ownership correctly.

