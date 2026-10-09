"""Exercise audio-process hangs and cancellation without using a soundcard."""

import os
import sys
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from radiomaster.engine.bass_host import BassHost
from radiomaster.engine.bass_radio_engine import BassRadioEngine
from radiomaster.engine.playback_engine import PlaybackEngine


def hung_backend():
    # A real pipe and child process: ready succeeds, every command then hangs.
    script = (
        "import json, sys, time; "
        "print(json.dumps({'ok': True, 'ready': True}), flush=True); "
        "sys.stdin.readline(); time.sleep(60)"
    )
    return BassRadioEngine([sys.executable, "-u", "-c", script], os.environ.copy())


def test_hung_native_command_is_terminated_and_pipe_read_unblocks():
    backend = hung_backend()
    backend.REQUEST_TIMEOUT = 0.15
    started = time.monotonic()
    try:
        with pytest.raises(RuntimeError, match="stopped responding"):
            backend._request({"cmd": "status"})
        assert time.monotonic() - started < 3
        assert not backend.available
    finally:
        backend.close()


def test_stop_interrupts_open_even_while_monitor_owns_io_lock():
    backend = hung_backend()
    backend.REQUEST_TIMEOUT = 0.15
    backend._generation = 1
    backend._seekable = True
    finished = []
    backend.on_track_finished(lambda: finished.append(True))
    worker = threading.Thread(
        target=backend._play_and_monitor, args=("episode.mp3", "Episode", "", 1)
    )
    worker.start()
    try:
        # Establish that play owns the lock before sending Stop.
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if not backend._io_lock.acquire(blocking=False):
                break
            backend._io_lock.release()
            time.sleep(0.01)
        else:
            pytest.fail("play did not acquire the command lock")
        backend.stop()
        worker.join(timeout=2)
        assert not worker.is_alive()
        assert not backend.available
        assert backend.state == "stopped"
        assert not finished  # a timeout must not auto-advance
    finally:
        backend.close()


def test_cancelled_episode_never_sends_a_play_command():
    backend = hung_backend()
    backend._generation = 2
    try:
        assert backend._request({"cmd": "play"}, generation=1)["cancelled"]
        assert backend.available
    finally:
        backend.stop(wait=False)


def test_shutdown_does_not_wait_for_a_native_quit_reply():
    backend = hung_backend()
    started = time.monotonic()
    backend.stop(wait=False)
    assert time.monotonic() - started < 3
    assert not backend.available


def test_next_play_replaces_dead_host_and_restores_settings():
    player = PlaybackEngine()
    dead, fresh = MagicMock(), MagicMock()
    dead.available = False
    player._bass_radio = dead
    player._rate = 1.4
    player._pan = -0.2
    player._output_device = "Speakers"
    with patch.object(BassRadioEngine, "create_if_available", return_value=fresh):
        player.play("next-episode.mp3", duration=100)
    dead.close.assert_called_once()
    fresh.set_rate.assert_called_with(1.4)
    fresh.set_pan.assert_called_with(-0.2)
    fresh.set_output_device.assert_called_with("Speakers")
    fresh.play.assert_called_once_with("next-episode.mp3", "", "", 100, seekable=True)


def test_timed_out_metadata_worker_keeps_its_own_cancellation_event():
    host = BassHost("unused")
    old_event = host._meta_stop
    old_worker = MagicMock()
    host._meta_thread = old_worker
    with patch("radiomaster.engine.bass_host.threading.Thread") as new_worker:
        host._restart_meta_thread()
    assert old_event.is_set()
    assert host._meta_stop is not old_event
    assert not host._meta_stop.is_set()
    assert new_worker.call_args.kwargs["args"] == (host._meta_stop,)


def test_metadata_worker_is_cancelled_before_stream_is_freed():
    host = BassHost("unused")
    host._dll = MagicMock()
    host._handle = 123
    host._dll.BASS_StreamFree.side_effect = lambda _h: (
        pytest.fail("metadata monitor still active") if not host._meta_stop.is_set() else True
    )
    host._cancel_pending_play()
    host._dll.BASS_StreamFree.assert_called_once_with(123)
    assert host._handle == 0


def test_timeshift_reports_buffer_position_without_finishing_a_media_track():
    backend = hung_backend()
    backend.stop(wait=False)
    backend._generation = 1
    finished = []
    positions = []
    backend.on_track_finished(lambda: finished.append(True))
    backend.on_position_update(lambda position, duration: positions.append(position))
    responses = iter([{"ok": True}, {"ok": True}, {"state": 1},
                      {"position_seconds": 12, "length_seconds": 30}, {"state": 0}])
    with patch.object(backend, "_request", side_effect=lambda *args, **kwargs: next(responses)), \
            patch("radiomaster.engine.bass_radio_engine.time.sleep"):
        assert backend.timeshift_play("buffer.mp3", start_seconds=10)
        backend._play_and_monitor("live", "Live", "", 1)
    assert positions == [12]
    assert not finished
