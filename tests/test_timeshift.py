"""Tests for the live time-shift jump back/forward (engine layer).

The BASS host subprocess is not exercised here -- these tests cover the
PlaybackEngine's tee management, refusal sentences, and state cleanup,
with the BASS engine stubbed.
"""

import os
from unittest import mock

import pytest

from radiomaster.engine.playback_engine import PlaybackEngine


@pytest.fixture
def engine():
    eng = PlaybackEngine()
    yield eng
    eng.close(wait=False)


def _live_engine(engine) -> PlaybackEngine:
    """An engine that looks like it is playing a live stream."""
    engine._current_url = "https://example.com/live"
    engine._current_title = "Example FM"
    engine._is_live = True
    engine._is_video_active = False
    return engine


def test_jump_back_refuses_when_not_live(engine):
    assert engine.jump_back() is False


def test_jump_back_refuses_when_no_url(engine):
    engine._is_live = True
    engine._current_url = ""
    assert engine.jump_back() is False


def test_jump_back_refuses_when_video(engine):
    _live_engine(engine)
    engine._is_video_active = True
    assert engine.jump_back() is False


def test_jump_back_refuses_without_bass(engine):
    _live_engine(engine)
    with mock.patch.object(engine, "_ensure_bass_radio", return_value=None):
        assert engine.jump_back() is False


def test_jump_back_refuses_without_ffmpeg(engine):
    _live_engine(engine)
    with mock.patch.object(engine, "_ensure_bass_radio", return_value=mock.Mock()), \
            mock.patch("radiomaster.utils.tools.get_ffmpeg", return_value=""):
        assert engine.jump_back() is False


def test_jump_forward_refuses_when_live(engine):
    """Jump forward only makes sense behind live -- at the live edge it
    must refuse (the UI speaks its own sentence for this case)."""
    _live_engine(engine)
    engine._timeshift_path = None
    assert engine.jump_forward() is False


def test_stop_cleans_up_tee(engine, tmp_path):
    """Stop must kill the tee and schedule the buffer file's removal --
    a leftover tee would keep downloading the stream after Stop."""
    _live_engine(engine)
    engine._timeshift_path = str(tmp_path / "buffer.mp3")
    engine._timeshift_live_url = "https://example.com/live"
    fake_process = mock.Mock()
    engine._timeshift_process = fake_process
    with mock.patch.object(engine, "_bass_radio", None):
        engine.stop(wait=False)
    fake_process.terminate.assert_called_once()
    assert engine._timeshift_process is None
    assert engine._timeshift_path is None


def test_behind_seconds_zero_when_live(engine):
    assert engine.timeshift_behind_seconds() == 0.0


def test_behind_seconds_from_status(engine):
    _live_engine(engine)
    engine._timeshift_path = "C:/tmp/buffer.mp3"
    bass = mock.Mock()
    bass.timeshift_status.return_value = (40.0, 55.0)
    engine._bass_radio = bass
    assert engine.timeshift_behind_seconds() == 15.0


def test_return_to_live_replays_stream(engine):
    _live_engine(engine)
    with mock.patch.object(engine, "play") as play:
        engine._return_to_live()
    play.assert_called_once_with("https://example.com/live", "Example FM", "",
                                 is_live=True)


def test_jump_back_seeks_existing_buffer(engine):
    _live_engine(engine)
    engine._timeshift_path = "buffer.mp3"
    engine._timeshift_generation = engine._playback_generation
    bass = mock.Mock()
    bass.timeshift_seek.return_value = (True, 10.0, 55.0)
    with mock.patch.object(engine, "_ensure_bass_radio", return_value=bass), \
            mock.patch.object(engine, "_start_timeshift_tee") as start:
        assert engine.jump_back() is True
    bass.timeshift_seek.assert_called_once_with(-15.0)
    start.assert_not_called()
    engine._timeshift_path = None


def test_delayed_jump_cannot_switch_a_new_station(engine, tmp_path):
    _live_engine(engine)
    buffer = tmp_path / "buffer.mp3"
    buffer.write_bytes(b"x" * 300000)
    bass = mock.Mock()
    workers = []
    with mock.patch.object(engine, "_ensure_bass_radio", return_value=bass), \
            mock.patch.object(engine, "_start_timeshift_tee", return_value=str(buffer)), \
            mock.patch("radiomaster.engine.playback_engine.threading.Thread") as thread:
        thread.side_effect = lambda **kwargs: workers.append(kwargs["target"]) or mock.Mock()
        assert engine.jump_back()
    engine._playback_generation += 1
    workers[0]()
    bass.timeshift_play.assert_not_called()
