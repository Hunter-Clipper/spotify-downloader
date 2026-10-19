"""Shared test setup.

`app.main` resolves DOWNLOAD_DIR once at import time, so the environment has to
point at a writable temporary directory *before* the module is imported.
"""
import os
import tempfile

os.environ.setdefault("DOWNLOAD_DIR", tempfile.mkdtemp(prefix="spotdl-tests-"))

import pytest  # noqa: E402

import app.main as main  # noqa: E402


@pytest.fixture(autouse=True)
def clean_state():
    """Give every test an empty job table, rate limiter and slot counter."""
    main._jobs.clear()
    main._rate_limits.clear()
    main._active_jobs = 0
    yield
    main._jobs.clear()
    main._rate_limits.clear()
    main._active_jobs = 0


@pytest.fixture
def started_jobs(monkeypatch):
    """Capture spawned jobs instead of shelling out to spotdl.

    Endpoint tests must never start a real download: the runner has no Spotify
    credentials and would hit the network.
    """
    started = []
    monkeypatch.setattr(main, "_spawn_background_job", started.append)
    return started


def make_job(job_id: str = "job-1", fmt: str = "mp3", **kwargs) -> main.Job:
    """A registered job with a real directory on disk."""
    job = main.Job(job_id=job_id, urls=["https://open.spotify.com/track/x"], format=fmt, **kwargs)
    main._register_job(job)
    return job
