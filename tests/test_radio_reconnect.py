"""Dropped BASS radio streams must honor the reconnect settings."""

from unittest.mock import Mock, patch
import os
import sys
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
