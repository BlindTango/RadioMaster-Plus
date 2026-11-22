"""Directory lookup by website, Radio Garden links and the browser-assisted finder."""

import http.server
import os
import subprocess
import threading
from types import SimpleNamespace

import pytest

from radiomaster.services import browser_discovery
from radiomaster.services.directory_lookup import lookup_by_website, matching_stations
from radiomaster.services.stream_discovery import _radio_garden_url
from radiomaster.services.stream_prober import probe_stream_format
from radiomaster.utils.tools import get_ffmpeg


def station(name, url, homepage):
    return SimpleNamespace(name=name, url=url, homepage=homepage)


# --- directory lookup ---------------------------------------------------------

def test_website_match_ignores_www_and_scheme():
    stations = [station("A", "http://s/a", "http://www.example.com/"),
                station("B", "http://s/b", "https://other.com/")]
    assert [s.name for s in matching_stations(stations, "https://example.com")] == ["A"]


def test_channel_page_does_not_fall_back_to_other_stations_on_the_site():
    stations = [station("Main", "http://s/m", "https://bc.example/"),
                station("Jazz", "http://s/j", "https://bc.example/jazz"),
                station("Rock", "http://s/r", "https://bc.example/rock")]
    assert [s.name for s in matching_stations(stations, "https://bc.example/jazz/")] == ["Jazz"]
    assert matching_stations(stations, "https://bc.example/classical") == []
    assert len(matching_stations(stations, "https://bc.example/")) == 3


def test_lookup_keeps_only_streams_that_play(monkeypatch):
    db = SimpleNamespace(
        station_count=lambda: 5,
        stations_by_website=lambda host: [station("Live", "http://s/live", "https://x.fm/"),
                                          station("Dead", "http://s/dead", "https://x.fm/"),
                                          station("Copy", "http://s/live", "https://x.fm/")])
    monkeypatch.setattr("radiomaster.services.directory_lookup.probe_stream_format",
                        lambda url: {"codec": "mp3", "sample_rate": 44100, "channels": 2,
                                     "bit_rate": 128000} if url.endswith("live") else None)
    result = lookup_by_website("https://x.fm/", db=db)
    assert [s.url for s in result.streams] == ["http://s/live"]
    assert result.candidates == 2          # the duplicate address is checked once


def test_lookup_says_when_the_catalog_has_not_been_downloaded():
    db = SimpleNamespace(station_count=lambda: 0)
    assert lookup_by_website("https://x.fm/", db=db).catalog_empty


def test_station_db_matches_homepage_host(tmp_path):
    from radiomaster.services.station_api import Station
    from radiomaster.services.station_db import StationDB
    db = StationDB(str(tmp_path / "s.db"))
    db.upsert_stations([Station("1", "A", "http://s/a", homepage="https://www.example.com/live"),
                        Station("2", "B", "http://s/b", homepage="https://elsewhere.org/")])
    assert [s.name for s in db.stations_by_website("example.com")] == ["A"]
    assert db.stations_by_website("100%_") == []


# --- Radio Garden ---------------------------------------------------------------

def test_radio_garden_listen_page_becomes_its_stream_address():
    assert _radio_garden_url("https://radio.garden/listen/bbc-radio-2/abc123XY") == \
        "https://radio.garden/api/ara/content/listen/abc123XY/channel.mp3"
    assert _radio_garden_url("https://radio.garden/visit/london/xyz") is None
    assert _radio_garden_url("https://example.com/listen/a/b") is None


# --- browser-assisted finder ---------------------------------------------------

def test_candidates_prefer_audio_and_drop_assets_and_trackers():
    requests = {
        "https://site.test/app.js": "application/javascript",
        "https://site.test/logo.png": "image/png",
        "https://www.google-analytics.com/live": "text/plain",
        "https://cdn.test/radio/live": "audio/mpeg",
        "https://cdn.test/live.m3u8": "application/vnd.apple.mpegurl",
        "https://api.test/stream/url": "application/json",
        "https://site.test/about": "text/html",
    }
    assert browser_discovery.candidate_urls(requests, "https://site.test/") == [
        "https://cdn.test/radio/live", "https://cdn.test/live.m3u8", "https://api.test/stream/url"]


def test_no_browser_gives_a_clear_message(monkeypatch):
    monkeypatch.setattr(browser_discovery, "find_browser", lambda: None)
    assert "not installed" in browser_discovery.find_with_browser("https://x.test/").error


@pytest.fixture
def player_site(tmp_path):
    """A page whose stream only starts when its Play button is pressed."""
    mp3 = tmp_path / "live.mp3"
    subprocess.run([get_ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "sine=d=5",
                    "-c:a", "libmp3lame", str(mp3)], check=True, timeout=60)

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            if self.path == "/":
                body = (b"<html><body><button id=p onclick=\"new Audio('/hidden/feed').play()\">"
                        b"Play</button></body></html>")
                kind = "text/html"
            elif self.path == "/hidden/feed":
                body, kind = mp3.read_bytes(), "audio/mpeg"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/"
    server.shutdown()


@pytest.mark.skipif(not browser_discovery.find_browser(), reason="Chrome or Edge is not installed")
def test_browser_finds_a_stream_that_only_starts_after_play(player_site):
    result = browser_discovery.find_with_browser(player_site, seconds=20)
    assert [s.url for s in result.streams] == [player_site + "hidden/feed"], result
    leftover = [d for d in os.listdir(os.environ.get("TEMP", ".")) if d.startswith("radiomaster-browser-")]
    assert not leftover
