"""Regressions found in the October 2026 runtime log."""

import io
import threading
from unittest.mock import MagicMock, patch

import pytest

from radiomaster.engine.playback_engine import PlaybackEngine
from radiomaster.engine.bass_radio_engine import BassRadioEngine
from radiomaster.engine.stream_reader import StreamReader
from radiomaster.services.station_api import StationAPI
from radiomaster.ui.radio_panel import RadioPanel


def test_concurrent_playback_requests_share_one_host():
    player = PlaybackEngine()
    entered = threading.Event()
    release = threading.Event()
    second_started = threading.Event()
    backend = MagicMock()
    backend.available = True

    def create():
        entered.set()
        assert release.wait(3)
        return backend

    def second_play():
        second_started.set()
        player.play("second.mp3")

    with patch("radiomaster.engine.bass_radio_engine.BassRadioEngine.create_if_available",
               side_effect=create) as factory:
        first = threading.Thread(target=player.play, args=("first.mp3",))
        second = threading.Thread(target=second_play)
        first.start()
        try:
            assert entered.wait(3)
            second.start()
            assert second_started.wait(3)
        finally:
            release.set()
            first.join(3)
            if second.ident is not None:
                second.join(3)
        assert not first.is_alive() and not second.is_alive()
        factory.assert_called_once()
        assert [call.args[0] for call in backend.play.call_args_list] == [
            "first.mp3", "second.mp3",
        ]


def test_click_tracking_drops_overlapping_requests_and_closes_response():
    client = StationAPI(base_urls=["https://example.test"])
    with patch.object(client._session, "get") as get:
        client._click_lock.acquire()
        try:
            client.click("busy")
            get.assert_not_called()
        finally:
            client._click_lock.release()
        client.click("next")
        get.return_value.__exit__.assert_called_once()


def test_stream_without_icy_framing_is_not_retried():
    response = MagicMock(status_code=200)
    with patch.object(StreamReader, "open_icy_stream", return_value=(response, 0)) as open_stream:
        assert list(RadioPanel._iter_icy_songs(MagicMock(), "https://radio/playlist.m3u8",
                                             lambda: True)) == []
    open_stream.assert_called_once()
    response.close.assert_called_once()


@pytest.mark.parametrize("payload", [b"", b"abcd", b"abcd\x01short"])
def test_icy_eof_raises_instead_of_spinning(payload):
    response = MagicMock(raw=io.BytesIO(payload))
    with pytest.raises(EOFError):
        StreamReader.read_next_icy_song(response, 4)


def test_empty_metadata_block_is_not_eof():
    response = MagicMock(raw=io.BytesIO(b"abcd\x00"))
    assert StreamReader.read_next_icy_song(response, 4) is None


def test_invalid_host_ready_response_terminates_child():
    process = MagicMock()
    process.poll.return_value = None
    process.stdout.readline.return_value = "invalid JSON\n"
    with patch("radiomaster.engine.bass_radio_engine.subprocess.Popen", return_value=process):
        with pytest.raises(ValueError):
            BassRadioEngine(["unused"], {})
    process.terminate.assert_called_once()
    process.wait.assert_called_once()
