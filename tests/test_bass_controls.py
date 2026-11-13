"""UI-thread controls must not wait behind a slow stream open."""

import threading
import time
from unittest.mock import MagicMock

from radiomaster.engine.bass_radio_engine import BassRadioEngine


def make_engine():
    engine = BassRadioEngine.__new__(BassRadioEngine)
    engine._lock = threading.RLock()
    engine._io_lock = threading.RLock()
    engine._deferred = {}
    engine._pipe_busy = False
    engine._generation = 1
    engine._volume, engine._pan, engine._rate = 0.8, 0.0, 1.0
    engine._effects = {}
    engine._state = engine.STATE_PLAYING
    engine._position = engine._duration = 0.0
    engine._on_state_change = None
    sent = []
    engine._request = lambda command, generation=None: sent.append(command) or {"ok": True}
    return engine, sent


def hold_pipe(engine, seconds):
    ready, release = threading.Event(), threading.Event()

    def holder():
        with engine._io_lock:
            ready.set()
            release.wait(seconds)
    threading.Thread(target=holder, daemon=True).start()
    ready.wait(2)
    return release


def test_control_while_pipe_busy_returns_quickly_and_is_sent_later():
    engine, sent = make_engine()
    release = hold_pipe(engine, 5)
    started = time.perf_counter()
    engine.set_volume(0.3)
    engine.set_pan(0.5)
    engine.set_rate(1.2)
    assert time.perf_counter() - started < 0.5           # never waits for the open
    assert sent == []
    release.set()
    time.sleep(0.05)
    engine._flush_deferred(1)
    commands = {c["cmd"]: c for c in sent}
    assert commands["volume"]["value"] == 0.3            # the latest value, not the first
    assert commands["pan"]["value"] == 0.5
    assert commands["set_playback_rate"]["rate"] == 1.2


def test_latest_control_wins_when_several_are_deferred():
    engine, sent = make_engine()
    release = hold_pipe(engine, 5)
    for value in (0.1, 0.2, 0.9):
        engine.set_volume(value)
    release.set()
    time.sleep(0.05)
    engine._flush_deferred(1)
    assert [c["value"] for c in sent if c["cmd"] == "volume"] == [0.9]


def test_control_failure_is_swallowed_not_raised_into_the_ui():
    engine, _ = make_engine()
    engine._request = MagicMock(side_effect=RuntimeError("BASS host is no longer running"))
    engine.set_volume(0.5)          # must not raise
    assert engine._volume == 0.5


def test_stop_while_open_is_in_progress_abandons_the_host_without_waiting():
    engine, _ = make_engine()
    aborted = threading.Event()
    engine._terminate_host = aborted.set
    release = hold_pipe(engine, 5)
    started = time.perf_counter()
    engine.stop()
    assert time.perf_counter() - started < 0.6
    assert aborted.wait(2)
    release.set()


def test_normal_control_is_sent_immediately_when_pipe_is_free():
    engine, sent = make_engine()
    engine.set_volume(0.4)
    assert sent == [{"cmd": "volume", "value": 0.4}]
    assert not engine._deferred
