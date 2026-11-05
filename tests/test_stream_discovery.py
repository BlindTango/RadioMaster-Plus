"""Offline traversal tests: HTML is never mistaken for a working audio URL."""

import io
import json
import threading
from unittest.mock import Mock

import pytest

from radiomaster.services import stream_discovery as discovery


class Response(io.BytesIO):
    def __init__(self, url, content_type, body=b"", final_url=None):
        super().__init__(body.encode() if isinstance(body, str) else body)
        self.url = final_url or url
        self.headers = {"Content-Type": content_type}

    def geturl(self):
        return self.url


@pytest.fixture
def web(monkeypatch):
    pages = {}
    requested = []

    def open_page(request, timeout):
        requested.append(request.full_url)
        assert 0 < timeout <= 5
        assert request.get_header("User-agent") == "Test agent"
        value = pages[request.full_url]
        if isinstance(value, Exception):
            raise value
        if callable(value):
            return value()
        return Response(request.full_url, *value)

    opener = Mock()
    opener.open.side_effect = open_page
    monkeypatch.setattr(discovery.urllib.request, "build_opener", lambda *args: opener)
    monkeypatch.setattr(discovery, "get_proxies", lambda: None)
    monkeypatch.setattr(discovery, "get_user_agent", lambda fallback: "Test agent")
    monkeypatch.setattr(discovery, "get_timeout", lambda **kwargs: 5)
    return pages, requested


def test_follow_listen_iframe_playlist_and_return_final_audio_url(web):
    pages, requested = web
    pages["https://radio.test/"] = ("text/html", '<a href="/listen">Listen Live</a>')
    pages["https://radio.test/listen"] = (
        "text/html",
        '<iframe src="https://player.test/"></iframe>',
    )
    pages["https://player.test/"] = ("text/html", '<audio src="/station.pls"></audio>')
    pages["https://player.test/station.pls"] = (
        "audio/x-scpls",
        "[playlist]\nNumberOfEntries=1\nFile1=https://cdn.test/live\nVersion=2",
    )
    pages["https://cdn.test/live"] = lambda: Response(
        "", "audio/aac", final_url="https://edge.test/live?token=keep%2Bthis"
    )
    result = discovery.discover_streams("https://radio.test/", max_depth=4)
    assert [s.url for s in result.streams] == ["https://edge.test/live?token=keep%2Bthis"]
    assert result.pages_checked == len(requested) == 5
    assert not result.limited


def test_inline_json_escaped_url_and_audio_sources_are_deduplicated(web):
    pages, requested = web
    pages["https://radio.test/"] = (
        "text/html",
        r"""
        <audio><source src="https://cdn.test/live.mp3?key=one&amp;id=two"></audio>
        <script>config={"file":"https:\/\/cdn.test\/live.mp3?key=one&id=two"};</script>
        <a href="https://cdn.test/fake.mp3">Download</a>
        <a href="javascript:alert(1)">Listen</a>
    """,
    )
    pages["https://cdn.test/live.mp3?key=one&id=two"] = ("audio/mpeg", b"ID3audio")
    pages["https://cdn.test/fake.mp3"] = ("text/html", "<html>Not audio</html>")
    result = discovery.discover_streams("https://radio.test/")
    assert len(result.streams) == 1
    assert result.streams[0].url.endswith("?key=one&id=two")
    assert requested.count(result.streams[0].url) == 1


def test_hls_keeps_playlist_and_never_fetches_audio_segments(web):
    pages, requested = web
    pages["https://radio.test/live.m3u8"] = (
        "application/vnd.apple.mpegurl",
        "#EXTM3U\n#EXT-X-TARGETDURATION:8\nsegment001.ts",
    )
    result = discovery.discover_streams("https://radio.test/live.m3u8")
    assert result.streams[0].format == "HLS"
    assert requested == ["https://radio.test/live.m3u8"]


def test_direct_audio_does_not_read_live_response(web):
    pages, _ = web

    def audio():
        response = Response("https://radio.test/live", "audio/mpeg")
        response.read = Mock(side_effect=AssertionError("Must not download a live broadcast"))
        response.read1 = response.read
        return response

    pages["https://radio.test/live"] = audio
    assert discovery.discover_streams("https://radio.test/live").streams


def test_iono_player_json_finds_variants_without_fetching_metadata_strings(web):
    pages, requested = web
    pages["https://iframe.iono.fm/playlists/s/207"] = (
        "application/json",
        json.dumps(
            {
                "metadata": {"title": "Unisa Radio", "url": "https://iono.fm/s/207"},
                "audio": [
                    {
                        "url": "https://edge.iono.fm/xice/207_high.aac?ref=<referer>&key=real",
                        "quality": "high",
                        "mime": "audio/aac",
                        "bitrate": 160000,
                    }
                ],
            }
        ),
    )
    pages["https://edge.iono.fm/xice/207_high.aac?key=real"] = ("audio/aac", b"audio")
    result = discovery.discover_streams("https://iono.fm/s/207")
    assert len(result.streams) == 1
    assert len(requested) == 2
    assert result.streams[0].url.endswith("?key=real")


def test_external_player_script_can_supply_extensionless_stream(web):
    pages, _ = web
    pages["https://radio.test/"] = ("text/html", '<script src="/player.js"></script>')
    pages["https://radio.test/player.js"] = (
        "application/javascript",
        'const config = {streamUrl: "https://cdn.test/live"};',
    )
    pages["https://cdn.test/live"] = ("audio/ogg", b"OggS")
    assert discovery.discover_streams("https://radio.test/").streams[0].format == "ogg"


def test_relative_playlist_entry_and_html_base_url(web):
    pages, _ = web
    pages["https://radio.test/"] = (
        "text/html",
        '<base href="https://cdn.test/radio/"><a href="listen.m3u">Listen</a>',
    )
    pages["https://cdn.test/radio/listen.m3u"] = ("audio/x-mpegurl", "#EXTM3U\n/live")
    pages["https://cdn.test/live"] = ("audio/mpeg", b"audio")
    assert (
        discovery.discover_streams("https://radio.test/").streams[0].url == "https://cdn.test/live"
    )


@pytest.mark.parametrize(
    "entry,expected",
    [
        ("/live?token=abc&quality=high", "https://radio.test/live?token=abc&quality=high"),
        ("file.mp3?token=abc", "https://radio.test/file.mp3?token=abc"),
        ("files/live?token=abc", "https://radio.test/files/live?token=abc"),
    ],
)
def test_relative_m3u_url_keeps_query_parameters(web, entry, expected):
    pages, _ = web
    pages["https://radio.test/listen.m3u"] = (
        "audio/x-mpegurl",
        "#EXTM3U\n" + entry,
    )
    pages[expected] = ("audio/mpeg", b"audio")
    result = discovery.discover_streams("https://radio.test/listen.m3u")
    assert result.streams[0].url == expected


def test_cyclic_listen_links_and_request_limits(web):
    pages, requested = web
    pages["https://radio.test/"] = ("text/html", '<a href="/listen">Listen</a>')
    pages["https://radio.test/listen"] = (
        "text/html",
        '<a href="/">Listen</a><a href="/player">Player</a>',
    )
    result = discovery.discover_streams("https://radio.test/", max_requests=2)
    assert result.limited
    assert requested == ["https://radio.test/", "https://radio.test/listen"]


def test_cancelled_scan_never_starts_a_request(web):
    _, requested = web
    cancel = threading.Event()
    cancel.set()
    result = discovery.discover_streams("https://radio.test/", cancel=cancel)
    assert result.cancelled
    assert not requested


def test_error_and_no_results_are_reported_without_raising(web):
    pages, _ = web
    pages["https://radio.test/"] = OSError("Connection refused")
    result = discovery.discover_streams("https://radio.test/")
    assert not result.streams
    assert result.error == "Connection refused"


@pytest.mark.parametrize(
    "url",
    [
        "",
        "radio.test",
        "file:///C:/secret",
        "javascript:play()",
        "https://user:password@radio.test/",
        "http://[bad",
    ],
)
def test_invalid_or_unsupported_urls_are_rejected(web, url):
    with pytest.raises(ValueError, match="HTTP or HTTPS"):
        discovery.discover_streams(url)
