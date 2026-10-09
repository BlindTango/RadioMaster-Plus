"""Seek timelines, growing buffers, and native slider interaction."""
from unittest.mock import Mock, patch
from types import SimpleNamespace
import sys

import pytest
import wx

from radiomaster.engine.playback_engine import PlaybackEngine
from radiomaster.ui.now_playing_bar import NowPlayingBar
from radiomaster.ui.main_window import MainWindow


@pytest.fixture
def bar():
    app = wx.GetApp() or wx.App(False)
    frame = wx.Frame(None)
    control = NowPlayingBar(frame)
    yield control
    frame.Destroy()
    app.ProcessPendingEvents()


@pytest.fixture
def buffered(tmp_path):
    engine = PlaybackEngine()
    engine._bass_radio = Mock(duration=60.0)
    engine._bass_radio.timeshift_status.return_value = (20.0, 60.0)
    engine._using_bass_radio = True
    engine._is_live = True
    engine._playback_generation = engine._timeshift_generation = 1
    path = tmp_path / "buffer.mp3"
    path.write_bytes(b"x" * 16000 * 120)
    engine._timeshift_path = str(path)
    yield engine
    engine._timeshift_path = None
    engine.close(wait=False)


def test_finite_audio_exposes_backend_duration():
    engine = PlaybackEngine()
    engine._using_bass_radio = True
    engine._is_live = False
    engine._bass_radio = Mock(duration=180.0)
    assert engine.duration == engine.seek_duration == 180
    engine.close(wait=False)


def test_buffer_seek_range_includes_newly_recorded_audio(buffered):
    assert buffered.duration == 0
    assert buffered.seek_duration == 120
    buffered._timeshift_generation = 0
    assert buffered.seek_duration == 0


def test_seek_into_original_buffer(buffered):
    buffered.seek(15)
    buffered._bass_radio.seek.assert_called_once_with(15)
    buffered._bass_radio.timeshift_play.assert_not_called()


def test_seek_into_growing_buffer_reopens_at_requested_position(buffered):
    buffered.seek(90)
    buffered._bass_radio.timeshift_play.assert_called_once_with(
        buffered._timeshift_path, volume=buffered.volume, start_seconds=90)


def test_seek_to_live_edge_returns_to_stream(buffered):
    with patch.object(buffered, "_return_to_live") as live:
        buffered.seek(120)
    live.assert_called_once()
    buffered._bass_radio.seek.assert_not_called()


def test_plain_live_stream_cannot_seek(buffered):
    buffered._timeshift_generation = 0
    buffered.seek(30)
    buffered._bass_radio.seek.assert_not_called()


def test_slider_keyboard_steps_and_absolute_seek(bar):
    callback = Mock()
    bar.on_seek(callback)
    bar.set_seekable(True)
    bar.set_time(30, 180)
    assert bar._position_slider.GetLineSize() == 1
    assert bar._position_slider.GetPageSize() == 10
    bar._position_slider.SetValue(70)
    bar._on_slider_seek(Mock())
    callback.assert_called_once_with(70)


def test_drag_preserves_thumb_and_seeks_only_on_release(bar):
    callback = Mock()
    bar.on_seek(callback)
    bar.set_seekable(True)
    bar.set_time(20, 120, timeshift=True)
    bar._on_seek_drag(Mock())
    bar._position_slider.SetValue(80)
    bar._on_slider_seek(Mock())
    bar.set_time(21, 121, timeshift=True)
    assert bar._position_slider.GetValue() == 80
    callback.assert_not_called()
    bar._on_seek_release(Mock())
    bar._on_slider_seek(Mock())
    callback.assert_called_once_with(80)
    assert bar._position_slider.GetName() == "Time-shift Position"
    assert "behind live" in bar._time_label.GetLabel()


def test_new_live_stream_clears_stale_slider(bar):
    bar.set_time(60, 120)
    bar.set_seekable(False)
    bar.set_time(0, 0)
    assert bar._position_slider.GetValue() == 0
    assert not bar._position_slider.IsEnabled()


def test_position_updates_enable_slider_for_active_buffer(buffered):
    buffered._bass_radio.state = "playing"
    window = SimpleNamespace(_engine=buffered, _now_playing=Mock(), _status_bar=Mock(),
                             _podcast_panel=Mock(), _audiobook_panel=Mock(), _media_panel=Mock())
    MainWindow._on_engine_position(window, 20, 60)
    window._now_playing.set_time.assert_called_once_with(20, 120, timeshift=True)
    window._now_playing.set_seekable.assert_called_once_with(True)


@pytest.mark.skipif(sys.platform != 'win32', reason="Windows native slider keys")
def test_native_slider_keys_seek(bar):
    import ctypes
    send = ctypes.windll.user32.SendMessageW
    send.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
    send.restype = ctypes.c_ssize_t
    callback = Mock()
    bar.on_seek(callback)
    bar.set_seekable(True)
    bar.set_time(30, 180)
    slider = bar._position_slider
    for key, target in [(0x27, 31), (0x22, 41), (0x23, 180), (0x24, 0)]:
        send(slider.GetHandle(), 0x100, key, 0)
        send(slider.GetHandle(), 0x101, key, 0)
        wx.GetApp().ProcessPendingEvents()
        assert slider.GetValue() == target
        callback.assert_called_with(target)
