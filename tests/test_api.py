"""Endpoint-level behaviour: auth, the removed cleanup route, and previews."""
import httpx
import pytest

import app.main as main

TRACK_HTTPS = "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT"


def _client():
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://test"
    )


class TestAuth:
    async def test_disabled_when_no_key_is_configured(self, monkeypatch):
        monkeypatch.setattr(main, "API_KEY", "")
        async with _client() as client:
            response = await client.post("/api/v1/jobs", json={"urls": [TRACK_HTTPS]})
        assert response.status_code == 503

    async def test_rejects_a_wrong_key(self, monkeypatch):
        monkeypatch.setattr(main, "API_KEY", "right")
        async with _client() as client:
            response = await client.post(
                "/api/v1/jobs",
                json={"urls": [TRACK_HTTPS]},
                headers={"X-API-Key": "wrong"},
            )
        assert response.status_code == 401

    async def test_rejects_a_missing_key(self, monkeypatch):
        monkeypatch.setattr(main, "API_KEY", "right")
        async with _client() as client:
            response = await client.get("/api/v1/jobs/whatever")
        assert response.status_code == 401

    async def test_accepts_x_api_key(self, monkeypatch, started_jobs):
        monkeypatch.setattr(main, "API_KEY", "right")
        monkeypatch.setattr(main, "MAX_CONCURRENT_JOBS", 50)
        async with _client() as client:
            response = await client.post(
                "/api/v1/jobs",
                json={"urls": [TRACK_HTTPS]},
                headers={"X-API-Key": "right"},
            )
        assert response.status_code == 202
        assert response.json()["status"] == "running"

    async def test_accepts_a_bearer_token(self, monkeypatch, started_jobs):
        monkeypatch.setattr(main, "API_KEY", "right")
        monkeypatch.setattr(main, "MAX_CONCURRENT_JOBS", 50)
        async with _client() as client:
            response = await client.post(
                "/api/v1/jobs",
                json={"urls": [TRACK_HTTPS]},
                headers={"Authorization": "Bearer right"},
            )
        assert response.status_code == 202


class TestRemovedCleanupRoute:
    """Issue #23: the unauthenticated destructive route is gone."""

    async def test_cleanup_route_no_longer_exists(self):
        async with _client() as client:
            response = await client.delete("/api/cleanup/anything")
        assert response.status_code == 404

    async def test_cleanup_function_is_gone(self):
        assert not hasattr(main, "cleanup")

    async def test_authenticated_v1_delete_still_covers_cleanup(
        self, monkeypatch, started_jobs
    ):
        monkeypatch.setattr(main, "API_KEY", "testkey")
        monkeypatch.setattr(main, "MAX_CONCURRENT_JOBS", 50)
        async with _client() as client:
            created = await client.post(
                "/api/v1/jobs",
                json={"urls": [TRACK_HTTPS]},
                headers={"X-API-Key": "testkey"},
            )
            job_id = created.json()["job_id"]
            main._jobs[job_id].status = "done"
            deleted = await client.delete(
                f"/api/v1/jobs/{job_id}", headers={"X-API-Key": "testkey"}
            )
        assert deleted.status_code == 200
        assert job_id not in main._jobs


class TestPreview:
    """Issue #25: previews accept the same URL forms as downloads."""

    @staticmethod
    def _stub_http(monkeypatch):
        calls = []

        class _Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {"title": "Title", "thumbnail_url": "http://img/cover.jpg"}

        class _FakeClient:
            async def get(self, url, params=None):
                calls.append(params)
                return _Response()

        monkeypatch.setattr(main, "_HTTPX_CLIENT", _FakeClient())
        return calls

    async def test_normalizes_a_spotify_uri(self, monkeypatch):
        calls = self._stub_http(monkeypatch)
        async with _client() as client:
            response = await client.post("/api/preview", json={"url": "spotify:track:abc"})

        assert response.status_code == 200
        assert calls == [{"url": "https://open.spotify.com/track/abc"}]
        assert response.json() == {
            "title": "Title",
            "thumbnail_url": "http://img/cover.jpg",
            "type": "track",
        }

    async def test_passes_an_https_url_through_unchanged(self, monkeypatch):
        calls = self._stub_http(monkeypatch)
        async with _client() as client:
            response = await client.post("/api/preview", json={"url": TRACK_HTTPS})
        assert response.status_code == 200
        assert calls == [{"url": TRACK_HTTPS}]

    @pytest.mark.parametrize(
        "url", ["", "https://example.com/track/x", "spotify:artist:abc"]
    )
    async def test_rejects_non_downloadable_urls(self, url):
        async with _client() as client:
            response = await client.post("/api/preview", json={"url": url})
        assert response.status_code == 400

    async def test_reports_an_upstream_failure(self, monkeypatch):
        class _FailingClient:
            async def get(self, *args, **kwargs):
                raise RuntimeError("spotify is down")

        monkeypatch.setattr(main, "_HTTPX_CLIENT", _FailingClient())
        async with _client() as client:
            response = await client.post("/api/preview", json={"url": TRACK_HTTPS})
        assert response.status_code == 502


class TestStatus:
    async def test_reports_missing_server_credentials(self, monkeypatch):
        monkeypatch.setattr(main, "SPOTIFY_CLIENT_ID", "")
        monkeypatch.setattr(main, "SPOTIFY_CLIENT_SECRET", "")
        async with _client() as client:
            response = await client.get("/api/status")
        assert response.json() == {"server_credentials": False}

    async def test_reports_present_server_credentials(self, monkeypatch):
        monkeypatch.setattr(main, "SPOTIFY_CLIENT_ID", "id")
        monkeypatch.setattr(main, "SPOTIFY_CLIENT_SECRET", "secret")
        async with _client() as client:
            response = await client.get("/api/status")
        assert response.json() == {"server_credentials": True}
