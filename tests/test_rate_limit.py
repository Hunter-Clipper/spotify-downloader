"""Per-IP rate limiting, bucketed (issues #12, #15, #19)."""
import time

import httpx
import pytest
from fastapi import HTTPException

import app.main as main

TRACK_HTTPS = "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT"


def _client():
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://test"
    )


class TestLimiter:
    async def test_allows_up_to_the_ceiling_then_429s(self):
        for _ in range(3):
            await main._check_rate_limit("download", "1.2.3.4", 3)
        with pytest.raises(HTTPException) as exc:
            await main._check_rate_limit("download", "1.2.3.4", 3)
        assert exc.value.status_code == 429

    async def test_buckets_are_independent(self):
        for _ in range(3):
            await main._check_rate_limit("download", "1.2.3.4", 3)
        # the same IP still has its full preview budget
        await main._check_rate_limit("preview", "1.2.3.4", 3)

    async def test_ips_are_independent(self):
        for _ in range(3):
            await main._check_rate_limit("download", "1.2.3.4", 3)
        await main._check_rate_limit("download", "5.6.7.8", 3)

    async def test_entries_expire_with_the_window(self, monkeypatch):
        monkeypatch.setattr(main, "RATE_LIMIT_WINDOW", 0)
        for _ in range(5):
            await main._check_rate_limit("download", "1.2.3.4", 2)

    async def test_stale_buckets_are_purged(self):
        await main._check_rate_limit("download", "1.2.3.4", 5)
        assert main._rate_limits

        main._purge_once(time.time() + main.RATE_LIMIT_WINDOW + 1)

        assert main._rate_limits == {}

    async def test_live_buckets_survive_a_purge(self):
        await main._check_rate_limit("download", "1.2.3.4", 5)
        main._purge_once(time.time())
        assert main._rate_limits


class TestEndpointCoverage:
    """Issue #15: the limit used to apply to /api/download and nothing else."""

    async def test_web_download_is_rate_limited(self, monkeypatch, started_jobs):
        monkeypatch.setattr(main, "MAX_CONCURRENT_JOBS", 50)
        monkeypatch.setattr(main, "RATE_LIMIT_MAX_REQUESTS", 2)
        async with _client() as client:
            payload = {"urls": [TRACK_HTTPS]}
            codes = [
                (await client.post("/api/download", json=payload)).status_code
                for _ in range(3)
            ]
        assert codes == [200, 200, 429]

    async def test_api_is_rate_limited(self, monkeypatch, started_jobs):
        monkeypatch.setattr(main, "API_KEY", "testkey")
        monkeypatch.setattr(main, "MAX_CONCURRENT_JOBS", 50)
        monkeypatch.setattr(main, "RATE_LIMIT_MAX_REQUESTS", 2)
        async with _client() as client:
            payload = {"urls": [TRACK_HTTPS]}
            headers = {"X-API-Key": "testkey"}
            codes = [
                (await client.post("/api/v1/jobs", json=payload, headers=headers)).status_code
                for _ in range(3)
            ]
        assert codes == [202, 202, 429]

    async def test_web_and_api_share_one_download_budget(self, monkeypatch, started_jobs):
        monkeypatch.setattr(main, "API_KEY", "testkey")
        monkeypatch.setattr(main, "MAX_CONCURRENT_JOBS", 50)
        monkeypatch.setattr(main, "RATE_LIMIT_MAX_REQUESTS", 2)
        async with _client() as client:
            payload = {"urls": [TRACK_HTTPS]}
            web = await client.post("/api/download", json=payload)
            api = await client.post(
                "/api/v1/jobs", json=payload, headers={"X-API-Key": "testkey"}
            )
            over = await client.post("/api/download", json=payload)
        assert (web.status_code, api.status_code, over.status_code) == (200, 202, 429)

    async def test_preview_has_its_own_ceiling(self, monkeypatch):
        monkeypatch.setattr(main, "RATE_LIMIT_MAX_REQUESTS", 1)
        monkeypatch.setattr(main, "PREVIEW_RATE_LIMIT_MAX_REQUESTS", 2)

        class _Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {"title": "T", "thumbnail_url": "http://img"}

        class _FakeClient:
            async def get(self, *args, **kwargs):
                return _Response()

        monkeypatch.setattr(main, "_HTTPX_CLIENT", _FakeClient())

        async with _client() as client:
            payload = {"url": TRACK_HTTPS}
            codes = [
                (await client.post("/api/preview", json=payload)).status_code
                for _ in range(3)
            ]
            # the download bucket is untouched by preview traffic
            download = await client.post("/api/download", json={"urls": [TRACK_HTTPS]})
        assert codes == [200, 200, 429]
        assert download.status_code == 200

    async def test_invalid_requests_do_not_consume_the_budget(self, monkeypatch, started_jobs):
        """Issue #12: validation happens before the limit is charged."""
        monkeypatch.setattr(main, "MAX_CONCURRENT_JOBS", 50)
        monkeypatch.setattr(main, "RATE_LIMIT_MAX_REQUESTS", 1)
        async with _client() as client:
            bad = [
                (await client.post("/api/download", json={"urls": ["https://example.com/x"]})).status_code
                for _ in range(5)
            ]
            good = await client.post("/api/download", json={"urls": [TRACK_HTTPS]})
        assert bad == [400] * 5
        assert good.status_code == 200
