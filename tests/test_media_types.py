"""Issue #14: the media type served by /api/v1/jobs/{id}/file."""
import pytest
from fastapi import HTTPException

import app.main as main
from conftest import make_job

EXPECTED = {
    "mp3": "audio/mpeg",
    "flac": "audio/flac",
    "wav": "audio/vnd.wave",
    "ogg": "audio/ogg",
}


def test_table_covers_every_allowed_format():
    """A format the app accepts must have a media type, and vice versa."""
    assert set(main.FORMAT_MEDIA_TYPES) == main.ALLOWED_FORMATS


@pytest.mark.parametrize(("fmt", "expected"), sorted(EXPECTED.items()))
def test_mapped_types(fmt, expected):
    assert main.FORMAT_MEDIA_TYPES[fmt] == expected


@pytest.mark.parametrize(("fmt", "expected"), sorted(EXPECTED.items()))
async def test_file_endpoint_serves_the_mapped_type(fmt, expected):
    job = make_job(job_id=f"job-{fmt}", fmt=fmt)
    (main.DOWNLOAD_DIR / job.job_id / f"track.{fmt}").write_bytes(b"payload")
    job.status = "done"
    job.result_file = f"track.{fmt}"

    response = await main.api_get_file(job.job_id)
    assert response.media_type == expected


async def test_multi_track_job_is_served_as_zip():
    job = make_job(job_id="job-zip")
    (main.DOWNLOAD_DIR / job.job_id / "tracks.zip").write_bytes(b"PK\x03\x04")
    job.status = "done"
    job.result_file = "tracks.zip"
    job.zip_filename = "album_20260101_000000.zip"

    response = await main.api_get_file(job.job_id)
    assert response.media_type == "application/zip"
    assert response.filename == "album_20260101_000000.zip"


async def test_unmapped_format_falls_back():
    job = make_job(job_id="job-opus", fmt="opus")
    (main.DOWNLOAD_DIR / job.job_id / "track.opus").write_bytes(b"x")
    job.status = "done"
    job.result_file = "track.opus"

    response = await main.api_get_file(job.job_id)
    assert response.media_type == main.DEFAULT_MEDIA_TYPE


async def test_unfinished_job_is_rejected():
    job = make_job(job_id="job-running")
    job.status = "running"
    with pytest.raises(HTTPException) as exc:
        await main.api_get_file(job.job_id)
    assert exc.value.status_code == 409


async def test_unknown_job_is_404():
    with pytest.raises(HTTPException) as exc:
        await main.api_get_file("does-not-exist")
    assert exc.value.status_code == 404


async def test_missing_file_is_404():
    job = make_job(job_id="job-gone")
    job.status = "done"
    job.result_file = "never-written.mp3"
    with pytest.raises(HTTPException) as exc:
        await main.api_get_file(job.job_id)
    assert exc.value.status_code == 404
