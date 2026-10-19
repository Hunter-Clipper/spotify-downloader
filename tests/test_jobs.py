"""Job construction, file discovery and result naming."""
import time
from pathlib import Path

import pytest
from fastapi import HTTPException

import app.main as main
from conftest import make_job

TRACK_HTTPS = "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT"


class TestBuildJob:
    def test_defaults(self):
        job = main._build_job(main.DownloadRequest(url=TRACK_HTTPS))
        assert job.urls == [TRACK_HTTPS]
        assert job.format == "mp3"
        assert job.bitrate == "320k"
        assert job.status == "pending"
        assert job.audio_provider == "youtube-music"

    def test_merges_url_and_urls_and_deduplicates(self):
        job = main._build_job(
            main.DownloadRequest(url=TRACK_HTTPS, urls=[TRACK_HTTPS, "spotify:album:abc"])
        )
        assert job.urls == [TRACK_HTTPS, "spotify:album:abc"]

    def test_rejects_no_urls(self):
        with pytest.raises(HTTPException) as exc:
            main._build_job(main.DownloadRequest())
        assert exc.value.status_code == 400

    def test_rejects_bad_url(self):
        with pytest.raises(HTTPException) as exc:
            main._build_job(main.DownloadRequest(url="https://example.com/track/x"))
        assert exc.value.status_code == 400

    @pytest.mark.parametrize("fmt", ["aac", "m4a", ""])
    def test_rejects_unknown_format(self, fmt):
        with pytest.raises(HTTPException) as exc:
            main._build_job(main.DownloadRequest(url=TRACK_HTTPS, format=fmt))
        assert exc.value.status_code == 400

    def test_rejects_unknown_bitrate_and_provider(self):
        with pytest.raises(HTTPException):
            main._build_job(main.DownloadRequest(url=TRACK_HTTPS, bitrate="999k"))
        with pytest.raises(HTTPException):
            main._build_job(main.DownloadRequest(url=TRACK_HTTPS, audio_provider="napster"))

    def test_lowercases_choices(self):
        job = main._build_job(
            main.DownloadRequest(url=TRACK_HTTPS, format="FLAC", audio_provider="YouTube")
        )
        assert (job.format, job.audio_provider) == ("flac", "youtube")

    def test_credentials_require_both_halves(self):
        assert main._build_job(
            main.DownloadRequest(url=TRACK_HTTPS, client_id="id")
        ).client_id == ""
        job = main._build_job(
            main.DownloadRequest(url=TRACK_HTTPS, client_id="id", client_secret="secret")
        )
        assert (job.client_id, job.client_secret) == ("id", "secret")


class TestSanitizeFilename:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Artist - Title", "Artist - Title"),
            ('a/b\\c:d*e?f"g<h>i|j', "abcdefghij"),
            ("  .dotted.  ", "dotted"),
            ("", "download"),
        ],
    )
    def test_sanitizes(self, raw, expected):
        assert main._sanitize_filename(raw) == expected

    def test_truncates_to_100_chars(self):
        assert len(main._sanitize_filename("x" * 250)) == 100


class TestFindMusicFiles:
    def test_flat_layout(self):
        job = make_job()
        job_dir = main.DOWNLOAD_DIR / job.job_id
        (job_dir / "a.mp3").write_bytes(b"x")
        (job_dir / "b.mp3").write_bytes(b"x")
        (job_dir / "notes.txt").write_text("x")
        assert [f.name for f in main._find_music_files(job_dir, "mp3", structured=False)] == [
            "a.mp3",
            "b.mp3",
        ]

    def test_structured_layout_recurses(self):
        job = make_job()
        job_dir = main.DOWNLOAD_DIR / job.job_id
        (job_dir / "Artist" / "Album").mkdir(parents=True)
        (job_dir / "Artist" / "Album" / "track.flac").write_bytes(b"x")
        (job_dir / "loose.flac").write_bytes(b"x")
        found = main._find_music_files(job_dir, "flac", structured=True)
        # sorted() compares full paths, so "Artist/..." sorts before "loose.flac"
        assert [f.name for f in found] == ["track.flac", "loose.flac"]


class TestResultFilename:
    def test_audio_file_uses_its_own_name(self):
        job = make_job()
        job.result_file = "Artist - Title.mp3"
        assert main._result_filename(job) == "Artist - Title.mp3"

    def test_zip_uses_the_descriptive_zip_name(self):
        job = make_job()
        job.result_file = "tracks.zip"
        job.zip_filename = "album_20260101_000000.zip"
        assert main._result_filename(job) == "album_20260101_000000.zip"

    def test_zip_falls_back_when_unnamed(self):
        job = make_job()
        job.result_file = "tracks.zip"
        assert main._result_filename(job) == "spotify_tracks.zip"


class TestZip:
    def test_zip_filename_describes_the_job(self):
        job = make_job()
        job_dir = main.DOWNLOAD_DIR / job.job_id
        single = job_dir / "Artist - Title.mp3"
        single.write_bytes(b"x")
        assert main._build_zip_filename([single], job.urls).startswith("Artist - Title_")

    def test_batch_naming(self):
        job = make_job()
        job_dir = main.DOWNLOAD_DIR / job.job_id
        files = []
        for i in range(3):
            path = job_dir / f"track{i}.mp3"
            path.write_bytes(b"x")
            files.append(path)
        assert main._build_zip_filename(files, ["a", "b"]).startswith("batch_3_tracks_")

    def test_create_zip_preserves_folders(self, tmp_path: Path):
        source = tmp_path / "src"
        (source / "Artist" / "Album").mkdir(parents=True)
        track = source / "Artist" / "Album" / "t.mp3"
        track.write_bytes(b"audio")
        zip_path = tmp_path / "out.zip"
        main._create_zip([track], source, zip_path)

        import zipfile

        with zipfile.ZipFile(zip_path) as archive:
            assert archive.namelist() == ["Artist/Album/t.mp3"]
            assert archive.read("Artist/Album/t.mp3") == b"audio"


class TestPurge:
    """Job expiry, exercised without waiting for the purge loop to tick."""

    def test_expires_finished_jobs(self):
        job = make_job(job_id="job-old")
        job.status = "done"
        job.finished_at = time.time()

        main._purge_once(time.time() + main.JOB_TTL_SECONDS + 1)

        assert "job-old" not in main._jobs
        assert not (main.DOWNLOAD_DIR / "job-old").exists()

    def test_keeps_jobs_inside_the_ttl(self):
        job = make_job(job_id="job-fresh")
        job.status = "done"
        job.finished_at = time.time()

        main._purge_once(time.time())

        assert "job-fresh" in main._jobs

    def test_never_expires_a_running_job(self):
        job = make_job(job_id="job-running")
        job.status = "running"
        job.created_at = time.time() - main.JOB_TTL_SECONDS * 10

        main._purge_once(time.time())

        assert "job-running" in main._jobs

    def test_expiry_is_measured_from_when_the_job_finished(self):
        """A long download must not be purged the instant it completes."""
        job = make_job(job_id="job-long")
        job.status = "done"
        job.created_at = time.time() - main.JOB_TTL_SECONDS * 5
        job.finished_at = time.time()

        main._purge_once(time.time())

        assert "job-long" in main._jobs
