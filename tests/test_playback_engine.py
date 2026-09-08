"""Tests for the playback engine."""

import os
import sys
import time

import pytest
from unittest.mock import patch, MagicMock
from radiomaster.engine.playback_engine import PlaybackEngine
from radiomaster.engine.effects_engine import EffectsEngine


class TestPlaybackEngine:
    """Test playback engine state management."""

    def test_initial_state(self) -> None:
        with patch("radiomaster.engine.bass_radio_engine.BassRadioEngine.create_if_available") as create:
            engine = PlaybackEngine()
        create.assert_not_called()
        assert engine.state == "stopped"
        assert engine.position == 0.0
        assert engine.volume == 0.8

    def test_volume_range(self) -> None:
        engine = PlaybackEngine()
        engine.set_volume(0.5)
        assert engine.volume == 0.5
        engine.set_volume(2.0)  # Above max
        assert engine.volume == 1.0
        engine.set_volume(-0.5)  # Below min
        assert engine.volume == 0.0

    def test_missing_bass_reports_error_without_starting_another_player(self):
        engine = PlaybackEngine()
        errors = []
        engine.on_error(errors.append)
        with patch("radiomaster.engine.bass_radio_engine.BassRadioEngine.create_if_available", return_value=None), \
             patch.object(engine, "_start_process") as video:
            engine.play("https://radio.example/stream", is_live=True)
        assert engine.state == "stopped"
        assert not engine._using_bass_radio
        assert "BASS audio engine could not start" in errors[0]
        video.assert_not_called()

    def test_bass_receives_saved_settings_and_live_controls(self):
        engine = PlaybackEngine()
        engine.set_volume(0.4)
        engine.set_pan(-0.2)
        engine.set_rate(1.2)
        engine.set_output_device("Test speakers")
        engine.apply_preset("reverb", "Stadium", {"mix": 0.4})
        bass = MagicMock()
        with patch("radiomaster.engine.bass_radio_engine.BassRadioEngine.create_if_available", return_value=bass):
            engine.play("book.mp3", duration=120)
        bass.set_output_device.assert_called_with("Test speakers")
        bass.set_volume.assert_called_with(0.4)
        bass.set_pan.assert_called_with(-0.2)
        bass.set_rate.assert_called_with(1.2)
        bass.apply_effects.assert_called_with(engine._effects)
        engine.pause()
        engine.resume()
        engine.seek(30)
        bass.pause.assert_called_once()
        bass.resume.assert_called_once()
        bass.seek.assert_called_once_with(30)
        engine.apply_preset("reverb", "Small Room", {"mix": 0.2})
        assert bass.apply_effects.call_args.args[0]["reverb"]["preset"] == "Small Room"
        engine.crossfade_to("next.mp3")
        bass.play.assert_called_with("next.mp3", "", "", 0.0, seekable=True)
        engine.close()

    def test_rate_range(self) -> None:
        engine = PlaybackEngine()
        engine.set_rate(1.5)
        assert engine.rate == 1.5
        engine.set_rate(0.25)  # Below min
        assert engine.rate == 0.5
        engine.set_rate(5.0)  # Above max
        assert engine.rate == 3.0

    def test_pan_range(self) -> None:
        engine = PlaybackEngine()
        engine.set_pan(0.5)
        assert engine.pan == 0.5
        engine.set_pan(-2.0)  # Below min
        assert engine.pan == -1.0
        engine.set_pan(2.0)  # Above max
        assert engine.pan == 1.0

    def test_unbounded_http_audio_uses_bass_radio_backend(self) -> None:
        engine = PlaybackEngine()
        engine._bass_radio = MagicMock()
        engine._bass_radio.state = "playing"
        engine._bass_radio.position = 3.0
        engine._bass_radio.duration = 0.0

        engine.play("http://radio.example/stream", title="Test station", is_live=True)

        engine._bass_radio.play.assert_called_once_with(
            "http://radio.example/stream", "Test station", "", 0.0,
            seekable=False,
        )
        assert engine.state == "playing"
        assert engine.position == 3.0
        assert engine.duration == 0.0

    def test_finite_http_audio_uses_seekable_bass_backend(self) -> None:
        engine = PlaybackEngine()
        engine._bass_radio = MagicMock()

        engine.play("https://media.example/episode.mp3", duration=120.0)

        engine._bass_radio.play.assert_called_once_with(
            "https://media.example/episode.mp3", "", "", 120.0,
            seekable=True,
        )

    def test_close_releases_bass_host(self) -> None:
        engine = PlaybackEngine()
        bass = MagicMock()
        engine._bass_radio = bass

        engine.close(wait=False)

        assert engine._bass_radio is None
        bass.close.assert_called_once_with()



    def test_toggle_effect(self) -> None:
        engine = PlaybackEngine()
        engine.toggle_effect("equalizer", True)
        assert engine._effects["equalizer"]["enabled"] is True
        engine.toggle_effect("equalizer", False)
        assert engine._effects["equalizer"]["enabled"] is False

    def test_video_process_exit_never_auto_reconnects(self) -> None:
        """Video plays in a real ffplay window the user can close directly
        (a click -- see -exitonmousedown -- the window's own X button, or
        Alt+F4), none of which go through this engine's own stop(). This
        used to auto-relaunch ffplay for any duration == 0 ("live") video
        whenever the process exited, with no way to tell "the user closed
        it" apart from "the stream actually dropped" -- confirmed live as
        a second ffplay window silently reopening right after the user
        closed the first one (reported as "some videos don't play" /
        "have to press Alt+F4 twice, two windows show up"). Video's own
        -reconnect/-reconnect_at_eof/-reconnect_streamed ffmpeg flags
        already recover a genuine transient network drop without the
        process ever exiting, so a real process exit no longer schedules
        a relaunch at all -- it just goes to stopped, exactly like a
        finite-duration video reaching its end. Radio's own auto-reconnect
        (BASS) is a separate code path and isn't exercised
        here."""

        class FakeProc:
            def __init__(self):
                self.stdin = MagicMock()
                self.pid = 4242
                self.returncode = None

            def poll(self):
                # Every launch "fails" (stream unreachable) instantly.
                return 1

            def terminate(self):
                pass

            def wait(self, timeout=None):
                pass

            def kill(self):
                pass

        with patch("radiomaster.engine.playback_engine.subprocess.Popen") as popen, \
             patch("radiomaster.engine.playback_engine.get_ffplay", return_value="ffplay"), \
             patch("radiomaster.utils.session_volume.set_process_volume", return_value=True):
            popen.return_value = FakeProc()

            engine = PlaybackEngine()
            engine.set_auto_reconnect(True)
            engine.play("http://example.invalid/stream", is_video=True)  # duration=0.0 -> "live"

            # Let the monitor thread notice the instant "exit".
            deadline = time.time() + 2.0
            while engine.state != "stopped" and time.time() < deadline:
                time.sleep(0.05)

            assert engine.state == "stopped"
            assert engine._reconnect_timer is None, "video should never schedule an auto-reconnect"

            calls_after_exit = popen.call_count
            # Wait past where the old 2s reconnect timer would have fired.
            time.sleep(2.3)
            assert popen.call_count == calls_after_exit, (
                "ffplay was relaunched on its own after the process exited -- "
                "video must never auto-reconnect"
            )

    def test_video_stream_rejection_triggers_retry_callback(self) -> None:
        """Confirmed live: a googlevideo.com URL resolved for one video
        can come back "HTTP error 403 Forbidden" from ffplay's own
        request, and ffplay never exits on its own afterward (-autoexit
        only fires at a real EOF, which a rejected connection never
        reaches) -- so without detecting this, the video window just
        sits there showing nothing forever. This engine only has the
        already-resolved (and now useless) stream URL, not the original
        page URL a retry needs, so on detecting the 403 in ffplay's own
        stderr log it stops the attempt and hands off via
        on_stream_rejected instead of trying to recover itself."""

        class FakeProc:
            def __init__(self):
                self.stdin = MagicMock()
                self.pid = 4243
                self.returncode = None
                self._alive = True

            def poll(self):
                return None if self._alive else 1

            def terminate(self):
                self._alive = False

            def wait(self, timeout=None):
                pass

            def kill(self):
                self._alive = False

        from radiomaster.utils.paths import get_paths
        log_path = os.path.join(get_paths()["logs"], "ffplay_last_run.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        with patch("radiomaster.engine.playback_engine.subprocess.Popen") as popen, \
             patch("radiomaster.engine.playback_engine.get_ffplay", return_value="ffplay"), \
             patch("radiomaster.utils.session_volume.set_process_volume", return_value=True):
            popen.return_value = FakeProc()

            engine = PlaybackEngine()
            rejected = []
            engine.on_stream_rejected(lambda: rejected.append(True))
            engine.play("http://example.invalid/stream", is_video=True, duration=120.0)

            # Simulate ffplay's own stderr writing a 403 shortly after launch
            # -- the real Popen is mocked out, so nothing writes this file
            # on its own.
            time.sleep(0.2)
            with open(log_path, "w", encoding="utf-8") as f:
                f.write("[https @ 0x0] HTTP error 403 Forbidden\n")

            deadline = time.time() + 5
            while not rejected and time.time() < deadline:
                time.sleep(0.1)

            assert rejected, "on_stream_rejected was never fired"
            assert engine.state == "stopped"

    def test_set_volume_does_not_restart_process(self) -> None:
        """Volume changes must apply live via WASAPI, not by killing and
        relaunching ffplay -- restarting mid-stream (audible dropout, a
        live radio reconnect) is exactly the behavior the README's
        'real-time... no restart required' promise rules out."""

        class FakeProc:
            def __init__(self):
                self.stdin = MagicMock()
                self.pid = 4242

            def poll(self):
                return None  # still running

            def terminate(self):
                pass

            def wait(self, timeout=None):
                pass

            def kill(self):
                pass

        with patch("radiomaster.engine.playback_engine.subprocess.Popen") as popen, \
             patch("radiomaster.engine.playback_engine.get_ffplay", return_value="ffplay"), \
             patch("radiomaster.utils.session_volume.set_process_volume", return_value=True) as set_vol:
            popen.return_value = FakeProc()

            engine = PlaybackEngine()
            # is_video=True: WASAPI-session volume is the ffplay-subprocess
            # backend's mechanism specifically. Audio-only playback (the
            # default) uses the BASS host's volume control.
            engine.play("http://example.invalid/stream", is_video=True)
            time.sleep(0.1)  # let the post-launch initial apply settle
            calls_before = popen.call_count

            engine.set_volume(0.3)
            time.sleep(engine.VOLUME_DEBOUNCE_SECONDS + 0.2)

            assert popen.call_count == calls_before, (
                "set_volume() relaunched ffplay instead of applying the "
                "change live through the running process's WASAPI session"
            )
            assert (4242, 0.3) in [c.args for c in set_vol.call_args_list]
            engine.stop()


class TestVideoFilters:
    def test_build_effects_filters_matches_ffplay_command_builder(self) -> None:
        """Video playback retains its filter chain after removing backup audio."""
        from radiomaster.engine.playback_engine import PlaybackEngine
        from radiomaster.engine.video_filters import build_effects_filters

        engine = PlaybackEngine()
        engine._rate = 1.2
        engine._effects["normalization"]["enabled"] = True
        cmd = engine._build_ffplay_command("http://example.invalid", is_video=True)
        af_index = cmd.index("-af")
        af_value = cmd[af_index + 1]
        expected = ",".join(build_effects_filters(1.2, engine._effects))
        assert af_value == expected


class TestEffectsEngine:
    """Test effects engine filter graph generation."""

    def test_empty_filter_graph(self) -> None:
        engine = EffectsEngine()
        result = engine.build_filter_graph()
        assert result is None

    def test_rate_filter(self) -> None:
        engine = EffectsEngine()
        result = engine.build_filter_graph(rate=1.5)
        assert result == "atempo=1.5"

    def test_pan_filter(self) -> None:
        engine = EffectsEngine()
        result = engine.build_filter_graph(pan=0.5)
        assert "pan=stereo" in result

    def test_equalizer_enabled(self) -> None:
        engine = EffectsEngine()
        engine.set_enabled("equalizer", True)
        engine.set_params("equalizer", {"32": 5, "1k": -3})
        result = engine.build_filter_graph()
        assert result is not None
        assert "firequalizer" in result

    def test_multiple_effects(self) -> None:
        engine = EffectsEngine()
        engine.set_enabled("equalizer", True)
        engine.set_enabled("normalization", True)
        result = engine.build_filter_graph(rate=1.2)
        assert result is not None
        assert "atempo=1.2" in result
        assert "firequalizer" in result
        assert "dynaudnorm" in result
