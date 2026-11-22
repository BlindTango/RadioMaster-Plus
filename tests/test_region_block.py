"""A station refused because of the listener's region is explained, and never counted as dead."""

import http.server
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from radiomaster.engine.playback_engine import PlaybackEngine
from radiomaster.services.region_block import region_block_message, region_block_status
from radiomaster.ui.station_health_dialog import _is_dead, _result_matches_filter


@pytest.fixture
def station_server():
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            code = {"/uk-only": 403, "/legal": 451, "/gone": 404}.get(self.path, 200)
            self.send_response(code)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", "0")
            self.end_headers()

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_refusal_codes_are_a_region_block_but_a_missing_stream_is_not(station_server):
    assert region_block_status(station_server + "/uk-only") == 403
    assert region_block_status(station_server + "/legal") == 451
    assert region_block_status(station_server + "/gone") is None
    assert region_block_status(station_server + "/ok") is None
    assert region_block_status("http://127.0.0.1:9/nothing") is None   # unreachable
    assert region_block_status("file:///x.mp3") is None


def test_message_gives_the_listener_something_to_do():
    text = region_block_message(403)
    assert "HTTP 403" in text and "VPN" in text and "Regional routing" in text


def make_engine(url="https://radio.test/live", failed_open=True):
    engine = SimpleNamespace(
        _bass_radio="bass", _using_bass_radio=True, _radio_connected=not failed_open,
        _radio_open_failed=False, _current_url=url, _playback_generation=7,
        _notify_error=MagicMock(), _on_region_blocked=None, _on_open_failed=None)
    engine._explain_open_failure = lambda *a: PlaybackEngine._explain_open_failure(engine, *a)
    return engine


def test_failed_open_of_a_blocked_station_shows_the_region_message(monkeypatch):
    engine = make_engine()
    monkeypatch.setattr("radiomaster.services.region_block.region_block_status", lambda url: 403)
    PlaybackEngine._explain_open_failure(engine, 7, engine._current_url, "BASS error 2")
    assert "licensed only for listeners" in engine._notify_error.call_args.args[0]


def test_failed_open_of_a_dead_station_keeps_the_original_error(monkeypatch):
    engine = make_engine()
    monkeypatch.setattr("radiomaster.services.region_block.region_block_status", lambda url: None)
    PlaybackEngine._explain_open_failure(engine, 7, engine._current_url, "BASS error 2")
    engine._notify_error.assert_called_once_with("BASS error 2")


def test_no_error_is_shown_once_the_listener_has_moved_on(monkeypatch):
    engine = make_engine()
    engine._playback_generation = 8
    monkeypatch.setattr("radiomaster.services.region_block.region_block_status", lambda url: 403)
    PlaybackEngine._explain_open_failure(engine, 7, engine._current_url, "BASS error 2")
    engine._notify_error.assert_not_called()


def test_blocked_station_is_not_dead():
    blocked = {"stream_ok": 0, "geo_blocked": 1}
    broken = {"stream_ok": 0, "geo_blocked": 0}
    assert not _is_dead(blocked) and _is_dead(broken)
    assert not _is_dead({"stream_ok": 1, "geo_blocked": 0})
    assert not _result_matches_filter(blocked, 1)      # Dead streams filter
    assert _result_matches_filter(blocked, 4)          # Geo-blocked filter
