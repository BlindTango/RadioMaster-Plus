"""Dropped BASS radio streams must honor the reconnect settings."""

from unittest.mock import Mock, patch
import os
import sys
import threading
import time

from radiomaster.engine.bass_radio_engine import BassRadioEngine

from radiomaster.engine.playback_engine import PlaybackEngine


def radio():
    engine = PlaybackEngine()
    bass = Mock(state=engine.STATE_STOPPED)
    engine._bass_radio = bass
    engine._using_bass_radio = True
    engine._is_live = True
    engine._current_url = "https://station.example/live"
    engine._current_title = "Test station"
    engine.set_auto_reconnect(True)
    return engine, bass


def test_drop_schedules_one_retry_and_preserves_limit():
    engine, bass = radio()
    with patch("radiomaster.engine.playback_engine.threading.Timer") as timer:
        engine._on_bass_state(bass, "stopped")
        engine._on_bass_state(bass, "stopped")
        timer.assert_called_once()
        timer.return_value.start.assert_called_once()
    with patch.object(engine, "play") as play:
        engine._reconnect_radio(bass, engine.playback_generation, False)
        play.assert_called_once_with(engine.current_url, "Test station", "", is_live=True)
        assert engine._reconnect_attempts == 1


def test_stop_cancels_retry_and_stale_callback_cannot_restart():
    engine, bass = radio()
    generation = engine.playback_generation
    pending = engine._reconnect_timer = Mock()
    engine.stop(wait=False)
    pending.cancel.assert_called_once()
    with patch.object(engine, "play") as play:
        engine._reconnect_radio(bass, generation, False)
        play.assert_not_called()


def test_disabled_and_finite_media_never_reconnect():
    engine, bass = radio()
    with patch("radiomaster.engine.playback_engine.threading.Timer") as timer:
        engine._auto_reconnect = False
        engine._on_bass_state(bass, "stopped")
        engine._auto_reconnect = True
        engine._is_live = False
        engine._on_bass_state(bass, "stopped")
        timer.assert_not_called()


def test_limit_is_checked_before_schedule_and_execution():
    engine, bass = radio()
    engine._reconnect_attempts = engine._MAX_RECONNECT_ATTEMPTS
    with patch("radiomaster.engine.playback_engine.threading.Timer") as timer, \
            patch.object(engine, "play") as play:
        engine._on_bass_state(bass, "stopped")
        engine._reconnect_radio(bass, engine.playback_generation, True)
        timer.assert_not_called()
        play.assert_not_called()


def test_recovered_or_paused_stream_is_not_restarted():
    engine, bass = radio()
    with patch.object(engine, "play") as play:
        bass.state = engine.STATE_PLAYING
        engine._reconnect_radio(bass, engine.playback_generation, False)
        bass.state = engine.STATE_PAUSED
        engine._reconnect_radio(bass, engine.playback_generation, True)
        play.assert_not_called()


def test_native_stall_event_can_recover_stuck_playing_decoder():
    engine, bass = radio()
    bass.state = engine.STATE_PLAYING
    with patch.object(engine, "play") as play:
        engine._reconnect_radio(bass, engine.playback_generation, True)
        play.assert_called_once()


def test_healthy_playback_forgives_previous_attempts():
    engine, bass = radio()
    engine._reconnect_attempts = 3
    engine._radio_healthy_since = 10
    with patch("radiomaster.engine.playback_engine.time.monotonic", return_value=21), \
            patch("radiomaster.engine.playback_engine.threading.Timer"):
        engine._on_bass_state(bass, "stopped")
    assert engine._reconnect_attempts == 0


def test_disabling_reconnect_cancels_pending_retry():
    engine, bass = radio()
    pending = engine._reconnect_timer = Mock()
    engine.set_auto_reconnect(False)
    pending.cancel.assert_called_once()
    assert engine._reconnect_timer is None


def test_initial_open_error_is_reported_once_without_automatic_retry():
    engine, bass = radio()
    errors = []
    engine.on_error(errors.append)
    with patch("radiomaster.engine.playback_engine.threading.Timer") as timer, \
            patch.object(engine, "play") as play:
        engine._on_bass_error(bass, "StreamCreateURL failed")
        engine._on_bass_state(bass, "stopped")
        engine._reconnect_radio(bass, engine.playback_generation, False)
    assert errors == ["StreamCreateURL failed"]
    timer.assert_not_called()
    play.assert_not_called()


def test_error_after_successful_connection_still_allows_reconnect():
    engine, bass = radio()
    engine._on_bass_state(bass, "playing")
    engine._on_bass_error(bass, "Host exited")
    with patch("radiomaster.engine.playback_engine.threading.Timer") as timer:
        engine._on_bass_state(bass, "stopped")
    timer.assert_called_once()


def test_replaced_host_error_does_not_interrupt_current_station():
    engine, _bass = radio()
    errors = []
    engine.on_error(errors.append)
    engine._on_bass_error(Mock(), "Old station failed")
    assert not errors
    assert not engine._radio_open_failed


def test_real_host_dropout_is_replaced_without_manual_stop():
    hosts = []
    engine = PlaybackEngine()
    engine.set_auto_reconnect(True)
    engine.set_reconnect_settings(2, 0.5)

    def create():
        state = 0 if not hosts else 1
        script = (
            "import json,sys\n"
            "print(json.dumps({'ok':True,'ready':True}),flush=True)\n"
            "for line in sys.stdin:\n"
            " command=json.loads(line)\n"
            f" print(json.dumps({{'ok':True,'state':{state}}}),flush=True)\n"
            " if command['cmd']=='quit': break\n"
        )
        backend = BassRadioEngine([sys.executable, "-u", "-c", script], os.environ.copy())
        hosts.append(backend)
        return backend

    try:
        with patch.object(BassRadioEngine, "create_if_available", side_effect=create):
            engine.play("https://station.example/live", "Test radio", is_live=True)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if len(hosts) == 2 and engine.state == "playing":
                    break
                time.sleep(0.02)
            assert len(hosts) == 2
            assert engine.state == "playing"
            assert not hosts[0].available
            engine.stop(wait=False)
            time.sleep(0.6)
            assert len(hosts) == 2
    finally:
        engine.close()
        for backend in hosts:
            backend.close()


def test_failed_reopen_uses_remaining_reconnect_budget():
    hosts = []
    engine = PlaybackEngine()
    engine.set_auto_reconnect(True)
    engine.set_reconnect_settings(3, 0.5)
    errors = []
    engine.on_error(errors.append)

    def create():
        index = len(hosts)
        script = (
            "import json,sys\n"
            "print(json.dumps({'ok':True,'ready':True}),flush=True)\n"
            "statuses=0\n"
            "for line in sys.stdin:\n"
            " command=json.loads(line)\n"
            " statuses += command['cmd']=='status'\n"
            f" rejected={index == 1!r} and command['cmd']=='play'\n"
            f" state=0 if {index == 0!r} and statuses>1 else 1\n"
            " print(json.dumps({'ok':not rejected,'state':state,'error':'Temporary outage'}),flush=True)\n"
            " if command['cmd']=='quit': break\n"
        )
        backend = BassRadioEngine([sys.executable, "-u", "-c", script], os.environ.copy())
        hosts.append(backend)
        return backend

    try:
        with patch.object(BassRadioEngine, "create_if_available", side_effect=create):
            engine.play("https://station.example/live", "Test radio", is_live=True)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if len(hosts) == 3 and engine.state == "playing":
                    break
                time.sleep(0.01)
            assert len(hosts) == 3
            assert engine.state == "playing"
            assert engine._reconnect_attempts == 2
            assert not engine._radio_open_failed
            assert len(errors) == 1
    finally:
        engine.close()
        for backend in hosts:
            backend.close()


def test_failed_open_stops_retrying_and_another_station_can_play():
    hosts = []
    failed = threading.Event()
    engine = PlaybackEngine()
    engine.set_auto_reconnect(True)
    engine.set_reconnect_settings(2, 0.5)
    engine.on_error(lambda message: failed.set())

    def create():
        reject_play = not hosts
        script = (
            "import json,sys\n"
            "print(json.dumps({'ok':True,'ready':True}),flush=True)\n"
            "for line in sys.stdin:\n"
            " command=json.loads(line)\n"
            f" rejected={reject_play!r} and command['cmd']=='play'\n"
            " print(json.dumps({'ok':not rejected,'state':1,'error':'Invalid stream'}),flush=True)\n"
            " if command['cmd']=='quit': break\n"
        )
        backend = BassRadioEngine([sys.executable, "-u", "-c", script], os.environ.copy())
        hosts.append(backend)
        return backend

    try:
        with patch.object(BassRadioEngine, "create_if_available", side_effect=create):
            engine.play("https://station.example/broken", "Broken", is_live=True)
            assert failed.wait(2)
            time.sleep(0.7)  # longer than the reconnect interval
            assert engine.state == "stopped"
            assert len(hosts) == 1
            assert engine._reconnect_timer is None
            engine.play("https://station.example/working", "Working", is_live=True)
            deadline = time.monotonic() + 2
            while engine.state != "playing" and time.monotonic() < deadline:
                time.sleep(0.01)
            assert engine.state == "playing"
            assert not engine._radio_open_failed
    finally:
        engine.close()
        for backend in hosts:
            backend.close()
