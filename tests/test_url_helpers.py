"""Spotify URL validation, normalisation and classification."""
import pytest

import app.main as main

TRACK_HTTPS = "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT"
ALBUM_HTTPS = "https://open.spotify.com/album/1ATL5GLyefJaxhQzSPVrLX"
PLAYLIST_HTTPS = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"


class TestValidate:
    @pytest.mark.parametrize(
        "url",
        [
            TRACK_HTTPS,
            ALBUM_HTTPS,
            PLAYLIST_HTTPS,
            "http://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT",
            "spotify:track:4cOdK2wGLETKBW3PvgPWqT",
            "spotify:album:1ATL5GLyefJaxhQzSPVrLX",
            "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M",
        ],
    )
    def test_accepts_https_and_spotify_scheme(self, url):
        assert main._validate_spotify_url(url) == url

    def test_strips_whitespace(self):
        assert main._validate_spotify_url(f"  {TRACK_HTTPS}  ") == TRACK_HTTPS

    @pytest.mark.parametrize(
        "url",
        [
            "",
            "https://example.com/track/abc",
            "https://open.spotify.com/",
            "https://open.spotify.com/artist/abc",       # artist links are not downloadable
            "spotify:artist:abc",
            "spotify:",
            "not a url at all",
        ],
    )
    def test_rejects_everything_else(self, url):
        with pytest.raises(ValueError):
            main._validate_spotify_url(url)


class TestUrlType:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            (TRACK_HTTPS, "track"),
            (ALBUM_HTTPS, "album"),
            (PLAYLIST_HTTPS, "playlist"),
            ("spotify:track:abc", "track"),
            ("spotify:album:abc", "album"),
            ("spotify:playlist:abc", "playlist"),
        ],
    )
    def test_classifies(self, url, expected):
        assert main._spotify_url_type(url) == expected

    def test_default_when_unknown(self):
        assert main._spotify_url_type("https://open.spotify.com/", default="download") == "download"


class TestNormalize:
    """Issue #25: previews need the https form even though spotdl takes either."""

    @pytest.mark.parametrize(
        ("uri", "expected"),
        [
            ("spotify:track:abc", "https://open.spotify.com/track/abc"),
            ("spotify:album:abc", "https://open.spotify.com/album/abc"),
            ("spotify:playlist:abc", "https://open.spotify.com/playlist/abc"),
        ],
    )
    def test_converts_spotify_uris(self, uri, expected):
        assert main._normalize_spotify_url(uri) == expected

    @pytest.mark.parametrize(
        "value",
        [TRACK_HTTPS, "", "spotify:", "spotify:artist:abc", "spotify:track"],
    )
    def test_leaves_anything_else_alone(self, value):
        assert main._normalize_spotify_url(value) == value

    def test_normalized_uri_passes_preview_validation(self):
        # the exact check /api/preview performs
        assert "open.spotify.com" in main._normalize_spotify_url("spotify:track:abc")
