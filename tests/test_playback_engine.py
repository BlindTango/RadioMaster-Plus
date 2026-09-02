"""Tests for the playback engine."""

import os
import sys
import time

import numpy as np
import pytest
from unittest.mock import patch, MagicMock
from radiomaster.engine.playback_engine import PlaybackEngine
from radiomaster.engine.effects_engine import EffectsEngine


class TestPlaybackEngine:
    """Test playback engine state management."""

    def test_initial_state(self) -> None:
        engine = PlaybackEngine()
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

    def test_rate_change_debounces_live_audio_calls(self) -> None:
        """Dragging the rate slider fires set_rate() on every EVT_SLIDER
        tick -- each one used to immediately flush LiveAudioEngine's ~4s
        buffered queue, causing an audible dropout on every single tick
        (reported live as "when increasing or decreasing the rate, it is
        noticeable"). A burst of rapid ticks should collapse into exactly
        one call to the live engine, after the burst settles."""
        engine = PlaybackEngine()
        engine._live = MagicMock()
        engine._is_video_active = False

        for i in range(20):
            engine.set_rate(1.0 + i * 0.01)
            time.sleep(0.01)  # faster than RATE_DEBOUNCE_SECONDS

        assert engine._live.set_rate.call_count == 0, "should still be debounced mid-drag"
        time.sleep(PlaybackEngine.RATE_DEBOUNCE_SECONDS + 0.15)
        assert engine._live.set_rate.call_count == 1
        engine._live.set_rate.assert_called_once_with(pytest.approx(1.19))

    def test_stop_cancels_pending_rate_timer(self) -> None:
        """Same reasoning as test_stop_cancels_pending_auto_reconnect: a
        rate change scheduled just before Stop must not fire afterward
        against a since-replaced/stopped LiveAudioEngine."""
        engine = PlaybackEngine()
        engine._live = MagicMock()
        engine._is_video_active = False
        engine.set_rate(2.0)
        assert engine._rate_timer is not None
        engine.stop()
        assert engine._rate_timer is None
        time.sleep(PlaybackEngine.RATE_DEBOUNCE_SECONDS + 0.15)
        engine._live.set_rate.assert_not_called()

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
        (LiveAudioEngine) is a separate code path and isn't exercised
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
            # default) uses LiveAudioEngine, which applies volume as a
            # direct numpy gain -- no process or session involved at all.
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


class TestLiveAudioEngine:
    """Tests for the audio-only backend (PyAV decode + sounddevice output)
    that gives Volume/Pan/Rate/effects genuinely live, no-restart changes."""

    def test_initial_playback_waits_for_prebuffer_cushion(self) -> None:
        """Opening a live source must not start PortAudio on an empty queue.

        That old behaviour made ordinary network jitter audible immediately,
        especially on high-bitrate FLAC stations and YouTube audio streams.
        """
        from radiomaster.engine.live_audio_engine import (
            CHANNELS,
            LiveAudioEngine,
            PREBUFFER_CHUNKS,
        )

        engine = LiveAudioEngine()
        engine._stop_flag.clear()
        chunk = np.ones((1024, CHANNELS), dtype=np.float32)
        with patch.object(engine, "_start_output_stream") as start_output:
            for _ in range(PREBUFFER_CHUNKS - 1):
                engine._pcm_queue.put(chunk.copy())
            engine._begin_output_if_buffered()
            start_output.assert_not_called()

            engine._pcm_queue.put(chunk.copy())
            engine._begin_output_if_buffered()
            start_output.assert_called_once()
            assert engine.state == engine.STATE_PLAYING
            assert engine._rebuffering is False

    def test_underrun_waits_for_full_cushion_before_resuming(self) -> None:
        """After starvation, isolated arriving chunks stay buffered instead
        of producing the repeated audio/silence breakup reported by users."""
        from radiomaster.engine.live_audio_engine import (
            CHANNELS,
            LiveAudioEngine,
            PREBUFFER_CHUNKS,
        )

        engine = LiveAudioEngine()
        engine._volume = 1.0
        engine._rebuffering = True
        chunk = np.ones((1024, CHANNELS), dtype=np.float32) * 0.25
        outdata = np.empty_like(chunk)

        for _ in range(PREBUFFER_CHUNKS - 1):
            engine._pcm_queue.put(chunk.copy())
        engine._audio_callback(outdata, 1024, None, None)
        assert np.all(outdata == 0.0)
        assert engine._pcm_queue.qsize() == PREBUFFER_CHUNKS - 1

        engine._pcm_queue.put(chunk.copy())
        engine._audio_callback(outdata, 1024, None, None)
        assert np.any(outdata != 0.0)
        assert engine._rebuffering is False

    def test_initial_state(self) -> None:
        from radiomaster.engine.live_audio_engine import LiveAudioEngine
        engine = LiveAudioEngine()
        assert engine.state == "stopped"
        assert engine.volume == 0.8
        assert engine.rate == 1.0
        assert engine.pan == 0.0

    def test_underrun_uses_configured_recovery_cushion(self) -> None:
        from radiomaster.engine.live_audio_engine import (
            CHANNELS, LiveAudioEngine, REBUFFER_CHUNKS,
        )
        engine = LiveAudioEngine()
        engine._volume = 1.0
        engine._rebuffering = False
        outdata = np.empty((1024, CHANNELS), dtype=np.float32)

        engine._audio_callback(outdata, 1024, None, None)

        assert engine._underrun_count == 1
        assert engine._rebuffering is True
        assert engine._rebuffer_target_chunks == REBUFFER_CHUNKS
        assert np.all(outdata == 0.0)

    def test_volume_pan_rate_apply_without_playback(self) -> None:
        """These are just numpy-gain/filter-spec parameters -- setting them
        with nothing playing must not error or require a process/session."""
        from radiomaster.engine.live_audio_engine import LiveAudioEngine
        engine = LiveAudioEngine()
        engine.set_volume(0.3)
        engine.set_pan(-0.5)
        engine.set_rate(1.5)
        assert engine.volume == 0.3
        assert engine.pan == -0.5
        assert engine.rate == 1.5

    def test_fade_underrun_edges_no_hard_jumps(self) -> None:
        """A buffer underrun (network jitter, or a rate/effects change
        flushing the queue) used to hand the output device a literal
        1.0 -> 0.0 sample-value jump, audible as a click/pop -- reported
        as "occasional artifacts in the stream". _fade_underrun_edges()
        should ramp through every real-audio/silence boundary instead."""
        from radiomaster.engine.live_audio_engine import LiveAudioEngine, CHANNELS

        engine = LiveAudioEngine.__new__(LiveAudioEngine)
        engine._pcm_queue = MagicMock(empty=MagicMock(return_value=True))

        n = 1024
        block = np.ones((n, CHANNELS), dtype=np.float32)
        pad = np.zeros(n, dtype=bool)
        pad[500:] = True
        block[500:] = 0.0  # real code always synthesizes literal zeros for pad chunks

        faded = engine._fade_underrun_edges(block.copy(), pad)

        max_jump = np.abs(np.diff(faded[:, 0])).max()
        assert max_jump < 0.02, f"adjacent-sample jump too large: {max_jump}"
        assert faded[400, 0] == pytest.approx(1.0)  # untouched, well before the fade zone
        assert faded[600, 0] == pytest.approx(0.0)  # fully silent past the fade zone

    def test_fade_underrun_edges_fade_in_on_resume(self) -> None:
        from radiomaster.engine.live_audio_engine import LiveAudioEngine, CHANNELS

        engine = LiveAudioEngine.__new__(LiveAudioEngine)
        engine._pcm_queue = MagicMock(empty=MagicMock(return_value=True))

        n = 1024
        block = np.zeros((n, CHANNELS), dtype=np.float32)
        pad = np.ones(n, dtype=bool)
        pad[700:] = False
        block[700:] = 1.0

        faded = engine._fade_underrun_edges(block.copy(), pad)

        assert faded[699, 0] == pytest.approx(0.0)
        assert faded[800, 0] == pytest.approx(1.0)  # fully resumed well after the fade zone
        max_jump = np.abs(np.diff(faded[:, 0])).max()
        assert max_jump < 0.02

    def test_fade_underrun_edges_preemptive_tail_fade_when_queue_empty(self) -> None:
        """No hard cut can be fixed after the fact once handed to the
        output device -- if this block is about to run the queue dry,
        taper its tail pre-emptively in case the *next* callback underruns."""
        from radiomaster.engine.live_audio_engine import LiveAudioEngine, CHANNELS

        engine = LiveAudioEngine.__new__(LiveAudioEngine)
        n = 1024
        block = np.ones((n, CHANNELS), dtype=np.float32)
        pad = np.zeros(n, dtype=bool)  # entirely real audio

        engine._pcm_queue = MagicMock(empty=MagicMock(return_value=True))
        faded = engine._fade_underrun_edges(block.copy(), pad)
        assert faded[-1, 0] == pytest.approx(0.0)
        assert faded[900, 0] == pytest.approx(1.0)  # well before the tail, untouched

        engine._pcm_queue = MagicMock(empty=MagicMock(return_value=False))
        not_faded = engine._fade_underrun_edges(block.copy(), pad)
        assert not_faded[-1, 0] == pytest.approx(1.0)  # queue has more -- no fade needed

    def test_dsp_effects_produce_bounded_finite_output(self) -> None:
        """Every effect except pitch_tempo now runs through a numpy DSP
        chain instead of an ffmpeg filter graph (see dsp.py) -- verifies
        each one's real built-in preset actually processes a real signal
        without NaN/Inf/exploding output, using the real audio callback
        (not a mock), for every effect in one pass."""
        from radiomaster.engine.live_audio_engine import LiveAudioEngine, DSP_EFFECT_ADAPTERS, CHANNELS
        from radiomaster.ui.effects_data import BUILTIN_PRESETS

        sr = 48000
        n = 1024
        t = np.arange(n, dtype=np.float32) / sr
        tone = (0.3 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
        chunk = np.column_stack([tone, tone])

        for effect_id in DSP_EFFECT_ADAPTERS:
            engine = LiveAudioEngine()
            engine.toggle_effect(effect_id, True)
            presets = BUILTIN_PRESETS.get(effect_id, {})
            if presets:
                name, params = next(iter(presets.items()))
                engine.apply_preset(effect_id, name, params)
            else:
                engine.apply_preset(effect_id, "Test", {"target": -16})

            outdata = np.zeros((n, CHANNELS), dtype=np.float32)
            for _ in range(10):
                engine._pcm_queue.put(chunk.copy())
            for _ in range(10):
                engine._audio_callback(outdata, n, None, None)
                assert not np.isnan(outdata).any(), effect_id
                assert not np.isinf(outdata).any(), effect_id
            assert np.abs(outdata).max() <= 1.0, effect_id

    def test_dsp_effects_never_touch_the_queue(self) -> None:
        """The whole point of moving effects off the filter graph: turning
        one on/applying a preset must not disturb a single already-queued
        sample -- unlike pitch_tempo (still filter-graph-based), which
        does still trim to a small cushion (see DRAIN_KEEP_CHUNKS).
        Regression test for the "artifacts"/glitchy-on-engage complaint
        that motivated this rewrite."""
        from radiomaster.engine.live_audio_engine import LiveAudioEngine, DSP_EFFECT_ADAPTERS, CHANNELS

        engine = LiveAudioEngine()
        for _ in range(150):
            engine._pcm_queue.put(np.ones((1024, CHANNELS), dtype=np.float32) * 0.5)
        full_size = engine._pcm_queue.qsize()

        for effect_id in DSP_EFFECT_ADAPTERS:
            engine.toggle_effect(effect_id, True)
            assert engine._pcm_queue.qsize() == full_size, effect_id
            engine.apply_effect_params(effect_id, {})
            assert engine._pcm_queue.qsize() == full_size, effect_id

    def test_pitch_tempo_still_uses_the_filter_graph_and_cushion(self) -> None:
        """pitch_tempo is the one effect that stays on the ffmpeg filter
        graph (true pitch-shifting, not a gain/delay/filter op a numpy
        chain can easily do) -- confirms it still gets the queue-cushion
        treatment the other 9 effects no longer need at all."""
        from radiomaster.engine.live_audio_engine import LiveAudioEngine, CHANNELS

        engine = LiveAudioEngine()
        for _ in range(150):
            engine._pcm_queue.put(np.ones((1024, CHANNELS), dtype=np.float32) * 0.5)

        engine.toggle_effect("pitch_tempo", True)
        engine.apply_preset("pitch_tempo", "Chipmunk", {"cents": 400, "tempo": 1.0})
        assert engine._pcm_queue.qsize() == engine.DRAIN_KEEP_CHUNKS

    def test_reconnect_closes_previous_output_stream(self) -> None:
        """A dropped-and-retried connection calls _start_output_stream()
        again on the same engine instance without going through stop()
        first. If the old stream isn't closed, its callback keeps running
        concurrently with the new one -- both consuming the PCM queue and
        both incrementing self._position, which looked exactly like
        position racing far ahead of real time (worse with every retry)."""
        from radiomaster.engine.live_audio_engine import LiveAudioEngine

        with patch("radiomaster.engine.live_audio_engine.sd.OutputStream") as out_stream_cls:
            first = MagicMock()
            second = MagicMock()
            out_stream_cls.side_effect = [first, second]

            engine = LiveAudioEngine()
            engine._start_output_stream()
            assert engine._output_stream is first
            first.close.assert_not_called()

            engine._start_output_stream()
            assert engine._output_stream is second
            first.abort.assert_called_once()
            first.close.assert_called_once()

    def test_output_stream_close_is_idempotent(self) -> None:
        """Stop and decoder failure must not free one native stream twice."""
        from radiomaster.engine.live_audio_engine import LiveAudioEngine

        engine = LiveAudioEngine()
        stream = MagicMock()
        engine._output_stream = stream
        engine._close_output_stream(abort=True)
        engine._close_output_stream(abort=True)

        stream.abort.assert_called_once()
        stream.close.assert_called_once()
        assert engine._output_stream is None

    def test_system_default_is_not_replaced_with_another_host_api(self) -> None:
        """System Default must retain the stable v1.1.70 device selection."""
        from radiomaster.engine.live_audio_engine import LiveAudioEngine

        with patch("radiomaster.engine.live_audio_engine.sd.OutputStream") as stream_cls:
            stream_cls.return_value = MagicMock()
            LiveAudioEngine()._start_output_stream()

        assert stream_cls.call_args.kwargs["device"] is None

    def test_decode_loop_does_not_start_output_after_stop(self) -> None:
        """_decode_loop() opens the container (can take real seconds --
        e.g. a fresh TCP connection on a reconnect retry) before it had
        ever checked _stop_flag. If Stop was clicked during that window,
        the reconnect finished anyway and started a brand new output
        stream right after -- Stop looked like it worked (briefly silent)
        then played again moments later."""
        from radiomaster.engine.live_audio_engine import LiveAudioEngine

        fake_stream = MagicMock()
        fake_stream.type = "audio"
        fake_container = MagicMock()
        fake_container.streams = [fake_stream]
        fake_container.demux.return_value = iter([])  # no packets either way

        engine = LiveAudioEngine()
        with patch("radiomaster.engine.live_audio_engine.av.open", return_value=fake_container), \
             patch.object(engine, "_start_output_stream") as start_output:
            engine._stop_flag.set()  # simulate Stop landing right after av.open() returns
            engine._decode_loop("http://example.invalid/stream")
            start_output.assert_not_called()

    def test_build_effects_filters_rate_only(self) -> None:
        from radiomaster.engine.live_audio_engine import build_effects_filters
        effects = LiveAudioEngineDefaults.effects()
        filters = build_effects_filters(1.5, effects)
        assert filters == ["atempo=1.5"]

    def test_build_effects_filters_equalizer(self) -> None:
        from radiomaster.engine.live_audio_engine import build_effects_filters
        effects = LiveAudioEngineDefaults.effects()
        effects["equalizer"]["enabled"] = True
        effects["equalizer"]["params"] = {"32": 5, "1k": -3}
        filters = build_effects_filters(1.0, effects)
        assert len(filters) == 1
        assert "firequalizer" in filters[0]

    @staticmethod
    def _assert_graph_configures(filter_specs) -> None:
        """Actually build+configure a real libavfilter graph from these
        specs -- add() alone doesn't validate a filter's argument string,
        only configure() (link resolution) does. This is exactly how
        firequalizer/compand/aecho/acrossfade args that looked fine at
        add() time turned out to be invalid and crashed live playback the
        moment that effect was actually turned on."""
        import av
        graph = av.filter.Graph()
        node = graph.add("abuffer", sample_rate="48000", sample_fmt="fltp", channel_layout="stereo")
        for spec in filter_specs:
            name, _, args = spec.partition("=")
            nxt = graph.add(name, args) if args else graph.add(name)
            node.link_to(nxt)
            node = nxt
        sink = graph.add("abuffersink")
        node.link_to(sink)
        graph.configure()  # raises if any filter's args are invalid

    def test_every_effect_produces_a_valid_filter_graph(self) -> None:
        """One real libavfilter validation per effect (plus rate, plus all
        of them combined) -- catches invalid filter syntax that only
        surfaces at graph-configure time, which a plain string-shape
        assertion (e.g. 'firequalizer' in filters[0]) would never catch."""
        from radiomaster.engine.live_audio_engine import build_effects_filters

        cases = [
            ("rate only", 1.5, {}),
            ("equalizer", 1.0, {"equalizer": {"enabled": True, "params": {"32": 5, "1k": -3}}}),
            ("dynamic_range", 1.0, {"dynamic_range": {"enabled": True,
             "params": {"threshold": -20, "attack": 5, "release": 50}}}),
            ("echo", 1.0, {"echo": {"enabled": True,
             "params": {"delay": 500, "decay": 0.4, "in_gain": 0.8, "out_gain": 0.88}}}),
            ("reverb", 1.0, {"reverb": {"enabled": True,
             "params": {"room_size": 0.4, "decay": 0.4, "mix": 0.3}}}),
            ("pitch_tempo", 1.0, {"pitch_tempo": {"enabled": True, "params": {"cents": 700, "tempo": 1.0}}}),
            ("chorus", 1.0, {"chorus": {"enabled": True,
             "params": {"delay": 50, "decay": 0.4, "speed": 2.0, "depth": 2.0}}}),
            ("compressor", 1.0, {"compressor": {"enabled": True,
             "params": {"threshold": 0.1, "ratio": 4, "attack": 20, "release": 250, "makeup": 1}}}),
            ("distortion", 1.0, {"distortion": {"enabled": True, "params": {"bits": 8, "mix": 0.6}}}),
            ("flanger", 1.0, {"flanger": {"enabled": True,
             "params": {"delay": 10, "depth": 2, "speed": 0.5}}}),
            ("gargle", 1.0, {"gargle": {"enabled": True, "params": {"rate": 20, "depth": 0.7}}}),
            ("normalization", 1.0, {"normalization": {"enabled": True, "params": {"target": -16}}}),
        ]
        for label, rate, overrides in cases:
            effects = LiveAudioEngineDefaults.effects()
            for k, v in overrides.items():
                effects[k].update(v)
            filters = build_effects_filters(rate, effects)
            self._assert_graph_configures(filters), f"{label} produced an invalid filter graph"

        # And all of them enabled together (rate + every effect at once).
        effects = LiveAudioEngineDefaults.effects()
        for effect_id in effects:
            effects[effect_id]["enabled"] = True
        filters = build_effects_filters(1.2, effects)
        self._assert_graph_configures(filters)

    def test_build_effects_filters_matches_ffplay_command_builder(self) -> None:
        """PlaybackEngine's video (ffplay) path and LiveAudioEngine's audio
        path must apply identical DSP for identical settings -- they now
        share this exact function, so this just confirms the wiring."""
        from radiomaster.engine.playback_engine import PlaybackEngine
        from radiomaster.engine.live_audio_engine import build_effects_filters

        engine = PlaybackEngine()
        engine._rate = 1.2
        engine._effects["normalization"]["enabled"] = True
        cmd = engine._build_ffplay_command("http://example.invalid", is_video=True)
        af_index = cmd.index("-af")
        af_value = cmd[af_index + 1]
        expected = ",".join(build_effects_filters(1.2, engine._effects))
        assert af_value == expected


class LiveAudioEngineDefaults:
    @staticmethod
    def effects() -> dict:
        return {
            "echo": {"enabled": False, "preset": "Medium Delay", "params": {}},
            "equalizer": {"enabled": False, "preset": "Flat", "params": {}},
            "reverb": {"enabled": False, "preset": "Small Room", "params": {}},
            "dynamic_range": {"enabled": False, "preset": "Light Compression", "params": {}},
            "pitch_tempo": {"enabled": False, "preset": "Semitone Down", "params": {}},
            "chorus": {"enabled": False, "preset": "Classic Chorus", "params": {}},
            "compressor": {"enabled": False, "preset": "Standard", "params": {}},
            "distortion": {"enabled": False, "preset": "Light Grit", "params": {}},
            "flanger": {"enabled": False, "preset": "Classic Flange", "params": {}},
            "gargle": {"enabled": False, "preset": "Classic Gargle", "params": {}},
            "normalization": {"enabled": False, "preset": "Standard (-16 LUFS)", "params": {}},
        }


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
