"""Audio-only playback engine using direct PyAV decode + sounddevice/WASAPI
output, instead of shelling out to ffplay.

This exists specifically so Volume, Pan, playback Rate, and the Effects
menu (Echo, Equalizer, Reverb, Dynamic Range, Pitch/Tempo Shift, Chorus,
Compressor, Distortion, Flanger, Gargle, plus Normalization) can change
*live* -- no restart, no reconnect -- which the README promises and the
ffplay-subprocess model (PlaybackEngine's other backend, still used for
video) fundamentally cannot deliver: ffplay has no API to reload its
filter graph while running, so any filter change there requires killing
and relaunching the process.

Crossfade is NOT part of this per-stream filter chain -- it needs two
overlapping streams (outgoing/incoming), which a single-stream filter
graph can't express. See PlaybackEngine.crossfade_to(), which runs two
whole LiveAudioEngine instances concurrently and ramps their volumes
instead.

Volume and Pan are applied as a direct numpy gain multiply on each
decoded PCM chunk right before it's queued for output -- genuinely
sample-accurate instant changes, no filter graph involved at all. Rate and
the filter-graph effects go through a small libavfilter graph (abuffer ->
[effects...] -> abuffersink) that gets rebuilt in-process, in place, in
microseconds whenever a parameter changes -- the decode thread and network
connection are completely undisturbed by a rebuild.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any, Callable, Optional

import av
import numpy as np
import sounddevice as sd

logger = logging.getLogger("radiomaster")

SAMPLE_RATE = 48000
CHANNELS = 2
BLOCKSIZE = 1024
QUEUE_MAXSIZE = 200  # ~4s of audio at 1024-sample blocks/48kHz
FADE_SAMPLES = 64  # ~1.3ms at 48kHz -- inaudible as a level change, but
# long enough that a fade through it (instead of a raw sample-value jump)
# eliminates the audible "click" a buffer-underrun boundary produces,
# whether from real network jitter or a rate/effects change flushing the
# queue for an immediate-feeling change (see _drain_queue_for_immediate_effect).


def _describe_stream_error(exc: Exception) -> str:
    """Turn a raw connection failure into something a user can act on.
    PyAV falls back to a useless "Error number -138 occurred" whenever its
    own error-name table doesn't cover a code (confirmed live against a
    real dead station: errno 138 has no entry in Python's own
    errno.errorcode table either) -- but the OS's own C runtime, which is
    where ffmpeg's error codes are actually drawn from, does know a plain
    string for most of these (os.strerror(138) resolves to "timed out")
    even when the higher-level tables above it don't."""
    errno_val = getattr(exc, "errno", None)
    if errno_val:
        import os as _os
        try:
            desc = _os.strerror(errno_val)
        except (ValueError, OSError):
            desc = None
        if desc and "unknown error" not in desc.lower():
            return f"Could not connect to the stream ({desc}). The station may be down or unreachable."
    return str(exc)


def build_effects_filters(rate: float, effects: dict[str, dict[str, Any]]) -> list[str]:
    """Build the list of "name=args" libavfilter descriptors for the
    current rate + effects settings. Shared between this engine (graph
    rebuild) and PlaybackEngine's ffplay -af string builder (video path)
    so the two backends apply identical DSP for identical settings.
    """
    filters: list[str] = []

    if rate != 1.0:
        filters.append(f"atempo={rate}")

    if effects["equalizer"]["enabled"]:
        params = effects["equalizer"]["params"]
        if params:
            # firequalizer's gain_entry takes semicolon-separated
            # entry(freq,gain_db) pairs -- NOT the "c0 f=.. w=.. g=.."
            # form this used to build, which is invalid syntax that
            # libavfilter only rejects at graph-configure time, not at
            # filter-creation time (so it went undetected until now).
            entries = ";".join(f"entry({k},{v})" for k, v in params.items())
            filters.append(f"firequalizer=gain_entry={entries}")
        # No params with EQ "enabled" means no bands set yet -- nothing to
        # apply, and there's no valid neutral firequalizer arg string to
        # fall back to, so just skip adding the filter.

    if effects["dynamic_range"]["enabled"]:
        params = effects["dynamic_range"]["params"]
        threshold = params.get("threshold", -20)
        attack = params.get("attack", 5)
        release = params.get("release", 50)
        # compand's points list is "x/y|x/y|..." -- a slash between each
        # point's x and y, not a comma (comma is the separator libavfilter
        # actually uses between *options*, so "x,y" parsed as two options
        # and failed at graph-configure time).
        filters.append(
            f"compand=attacks={attack}:decays={release}:"
            f"points=-80/-80|-{abs(threshold)}/-{abs(threshold)}|0/0"
        )

    if effects["echo"]["enabled"]:
        params = effects["echo"]["params"]
        delay = params.get("delay", 500)
        decay = params.get("decay", 0.4)
        in_gain = params.get("in_gain", 0.8)
        out_gain = params.get("out_gain", 0.88)
        # aecho's positional args are in_gain:out_gain:delays:decays.
        filters.append(f"aecho={in_gain}:{out_gain}:{delay}:{decay}")

    if effects["reverb"]["enabled"]:
        params = effects["reverb"]["params"]
        room_size = params.get("room_size", 0.4)
        decay = params.get("decay", 0.4)
        mix = params.get("mix", 0.3)
        # ffmpeg has no dedicated reverb filter -- simulate room
        # reflections with a single aecho call given 4 taps (pipe-
        # separated delay/decay lists), spaced out and scaled by
        # room_size, each successive tap decaying faster than the last.
        max_delay = 30 + room_size * 220  # ms, roughly 50-250ms
        delays = [max_delay * f for f in (0.15, 0.35, 0.6, 1.0)]
        decays = [max(0.05, decay * f) for f in (0.9, 0.7, 0.5, 0.3)]
        delays_str = "|".join(f"{d:.0f}" for d in delays)
        decays_str = "|".join(f"{d:.3f}" for d in decays)
        filters.append(f"aecho=1.0:{mix}:{delays_str}:{decays_str}")

    if effects["chorus"]["enabled"]:
        params = effects["chorus"]["params"]
        delay = params.get("delay", 50)
        decay = params.get("decay", 0.4)
        speed = params.get("speed", 2.0)
        depth = params.get("depth", 2.0)
        filters.append(f"chorus=0.5:0.9:{delay}:{decay}:{speed}:{depth}")

    if effects["compressor"]["enabled"]:
        params = effects["compressor"]["params"]
        threshold = params.get("threshold", 0.1)
        ratio = params.get("ratio", 4)
        attack = params.get("attack", 20)
        release = params.get("release", 250)
        makeup = params.get("makeup", 1)
        filters.append(
            f"acompressor=threshold={threshold}:ratio={ratio}:"
            f"attack={attack}:release={release}:makeup={makeup}"
        )

    if effects["distortion"]["enabled"]:
        params = effects["distortion"]["params"]
        bits = int(params.get("bits", 8))
        mix = params.get("mix", 0.6)
        filters.append(f"acrusher=bits={bits}:mix={mix}:mode=log")

    if effects["flanger"]["enabled"]:
        params = effects["flanger"]["params"]
        delay = params.get("delay", 10)
        depth = params.get("depth", 2)
        speed = params.get("speed", 0.5)
        filters.append(f"flanger=delay={delay}:depth={depth}:speed={speed}")

    if effects["gargle"]["enabled"]:
        params = effects["gargle"]["params"]
        rate = params.get("rate", 20)
        depth = params.get("depth", 0.7)
        # No native "gargle" filter -- tremolo's amplitude modulation at a
        # gargle-appropriate rate produces the same warbling character.
        filters.append(f"tremolo=f={rate}:d={depth}")

    if effects["pitch_tempo"]["enabled"]:
        params = effects["pitch_tempo"]["params"]
        cents = params.get("cents", 0)
        tempo = params.get("tempo", 1.0)
        ratio = 2 ** (cents / 1200)
        # Three separate chained filters, appended as three separate list
        # entries (not one comma-joined string): every entry in this list
        # must be exactly one filter for LiveAudioEngine's graph builder,
        # which adds each entry as its own graph.add() call -- bundling
        # multiple filters into one string here previously made it try to
        # pass "48000*ratio,aresample=...,atempo=..." as asetrate's own
        # (single) argument, which is invalid. Harmless for the ffplay
        # -af string builder either way, since joining 3 separate entries
        # with "," produces the exact same flattened string as one
        # already-comma-joined entry would.
        filters.append(f"asetrate={SAMPLE_RATE}*{ratio}")
        filters.append(f"aresample={SAMPLE_RATE}")
        filters.append(f"atempo={tempo / ratio}")

    # Crossfade is deliberately NOT added to this single-stream filter
    # chain: acrossfade takes two separate audio inputs and blends them
    # into one output (for transitioning between two tracks) -- it can't
    # function as an in-place effect on a single stream, in either this
    # engine or the old ffplay -af string it was copied from. Making
    # crossfade real would mean decoding the next track in parallel and
    # mixing the tail of one into the head of the other, which is a
    # genuinely separate feature, not a filter-string fix.

    if effects["normalization"]["enabled"]:
        params = effects["normalization"]["params"]
        target = params.get("target", -16)
        filters.append(f"dynaudnorm=framelen=500:targetrms={10 ** (target / 20):.4f}")

    return filters


def _rate_and_pitch_filters(rate: float, effects: dict[str, dict[str, Any]]) -> list[str]:
    """The rate/pitch_tempo subset of build_effects_filters() -- the only
    two effects LiveAudioEngine's own filter graph still handles (see
    dsp.py's module docstring for why the other 9 moved to a numpy DSP
    chain applied directly in _audio_callback instead). Kept as a
    separate function rather than filtering build_effects_filters()'s
    output down: this list feeds directly into a real libavfilter graph
    here, while build_effects_filters() itself is still used as-is by
    PlaybackEngine for the video (ffplay) path, which has no DSP-chain
    option and still needs every effect's filter string.
    """
    filters: list[str] = []
    if rate != 1.0:
        filters.append(f"atempo={rate}")
    if effects["pitch_tempo"]["enabled"]:
        params = effects["pitch_tempo"]["params"]
        cents = params.get("cents", 0)
        tempo = params.get("tempo", 1.0)
        ratio = 2 ** (cents / 1200)
        filters.append(f"asetrate={SAMPLE_RATE}*{ratio}")
        filters.append(f"aresample={SAMPLE_RATE}")
        filters.append(f"atempo={tempo / ratio}")
    return filters


def _parse_filter_spec(spec: str) -> tuple[str, str]:
    """Split "name=args" (ffmpeg -af syntax) into (name, args) for
    Graph.add(). A filter with no "=" (rare, e.g. a bare flag) gets an
    empty args string."""
    name, _, args = spec.partition("=")
    return name, args


# ---------------------------------------------------------------------------
# DSP-chain effect adapters -- convert this app's own effects_data.py
# parameter names/ranges into whatever each dsp.py processor's update()
# expects. One make_processor()/apply_params() pair per effect_id; two
# effects intentionally share one processor type (dsp.Compressor for both
# "compressor" and "dynamic_range", dsp.ModulatedDelay for both "chorus"
# and "flanger", dsp.MultiTapDelay for both "echo" and "reverb"), matching
# the reference project's own EffectSpec design.
# ---------------------------------------------------------------------------
from radiomaster.engine import dsp  # noqa: E402


def _apply_equalizer(proc: "dsp.Equalizer", p: dict[str, Any]) -> None:
    proc.update(p)


def _apply_dynamic_range(proc: "dsp.Compressor", p: dict[str, Any]) -> None:
    # effects_data.py's dynamic_range threshold is in dB (-60..0);
    # dsp.Compressor takes linear amplitude (0.001..1) like "compressor"
    # already uses natively.
    threshold_db = float(p.get("threshold", -20))
    proc.update({
        "threshold": 10 ** (threshold_db / 20),
        "ratio": float(p.get("ratio", 4)),
        "attack": float(p.get("attack", 5)),
        "release": float(p.get("release", 50)),
        "knee": float(p.get("knee", 10)),
        "makeup": 1.0,
        "mix": 1.0,
    })


def _apply_compressor(proc: "dsp.Compressor", p: dict[str, Any]) -> None:
    proc.update({
        "threshold": float(p.get("threshold", 0.1)),
        "ratio": float(p.get("ratio", 4)),
        "attack": float(p.get("attack", 20)),
        "release": float(p.get("release", 250)),
        "makeup": float(p.get("makeup", 1)),
    })


def _apply_distortion(proc: "dsp.BitCrusher", p: dict[str, Any]) -> None:
    proc.update(p)


def _apply_echo(proc: "dsp.MultiTapDelay", p: dict[str, Any]) -> None:
    delay_ms = max(1.0, float(p.get("delay", 500)))
    decay = max(0.001, float(p.get("decay", 0.4)))
    proc.set_taps(
        in_gain=float(p.get("in_gain", 0.8)), out_gain=float(p.get("out_gain", 0.88)),
        taps_ms_decay=[(delay_ms, decay)],
    )


def _apply_reverb(proc: "dsp.MultiTapDelay", p: dict[str, Any]) -> None:
    room_size = float(p.get("room_size", 0.4))
    decay = float(p.get("decay", 0.4))
    mix = float(p.get("mix", 0.3))
    max_delay = 30 + room_size * 220  # ms, roughly 50-250ms
    delays = [max_delay * f for f in (0.15, 0.35, 0.6, 1.0)]
    decays = [max(0.001, decay * f * mix) for f in (0.9, 0.7, 0.5, 0.3)]
    proc.set_taps(in_gain=1.0, out_gain=1.0, taps_ms_decay=list(zip(delays, decays)))


def _apply_chorus(proc: "dsp.ModulatedDelay", p: dict[str, Any]) -> None:
    proc.update({
        "base_delay_ms": float(p.get("delay", 50)),
        "depth_ms": float(p.get("depth", 2.0)),
        "speed_hz": float(p.get("speed", 2.0)),
        "feedback": 0.0,  # a mixed delayed voice, not regenerative -- matches the old chorus filter
        "mix": max(0.0, min(1.0, float(p.get("decay", 0.4)))),
        "phase_deg": 90.0,  # fixed stereo spread between L/R modulation for width
        "in_gain": 1.0, "out_gain": 1.0,
    })


def _apply_flanger(proc: "dsp.ModulatedDelay", p: dict[str, Any]) -> None:
    proc.update({
        "base_delay_ms": float(p.get("delay", 10)),
        "depth_ms": float(p.get("depth", 2)),
        "speed_hz": float(p.get("speed", 0.5)),
        "feedback": 0.25,  # flangers are characteristically regenerative, unlike chorus
        "mix": 0.5,
        "phase_deg": 0.0,
        "in_gain": 1.0, "out_gain": 1.0,
    })


def _apply_gargle(proc: "dsp.Tremolo", p: dict[str, Any]) -> None:
    proc.update({"frequency_hz": float(p.get("rate", 20)), "depth": float(p.get("depth", 0.7))})


def _apply_normalization(proc: "dsp.LoudnessNormalizer", p: dict[str, Any]) -> None:
    target_db = float(p.get("target", -16))
    proc.update({"target_rms": 10 ** (target_db / 20), "max_gain": 15.0})


# effect_id -> (make_processor, apply_params). Anything NOT in this dict
# (currently only "pitch_tempo") stays on the filter-graph path.
DSP_EFFECT_ADAPTERS: dict[str, tuple[Callable[[], Any], Callable[[Any, dict], None]]] = {
    "equalizer": (dsp.Equalizer, _apply_equalizer),
    "dynamic_range": (dsp.Compressor, _apply_dynamic_range),
    "compressor": (dsp.Compressor, _apply_compressor),
    "distortion": (dsp.BitCrusher, _apply_distortion),
    "chorus": (dsp.ModulatedDelay, _apply_chorus),
    "flanger": (dsp.ModulatedDelay, _apply_flanger),
    "gargle": (dsp.Tremolo, _apply_gargle),
    "echo": (dsp.MultiTapDelay, _apply_echo),
    "reverb": (dsp.MultiTapDelay, _apply_reverb),
    "normalization": (dsp.LoudnessNormalizer, _apply_normalization),
}

# Order matters for how effects sound when chained: EQ/dynamics first, then
# distortion/colour effects, then modulation, with time-based echo/reverb,
# and loudness normalization LAST so it corrects the final output level
# regardless of what every effect before it did to the signal.
DSP_CHAIN_ORDER = [
    "equalizer", "dynamic_range", "compressor", "distortion",
    "chorus", "flanger", "gargle", "echo", "reverb", "normalization",
]


class LiveAudioEngine:
    """Decode + filter + play a single audio URL/file, with volume, pan,
    rate, and effects all appliable live during playback."""

    STATE_STOPPED = "stopped"
    STATE_PLAYING = "playing"
    STATE_PAUSED = "paused"
    STATE_BUFFERING = "buffering"

    def __init__(self) -> None:
        self._state = self.STATE_STOPPED
        self._current_url: str = ""
        self._current_title: str = ""
        self._current_artist: str = ""
        self._duration: float = 0.0
        self._position: float = 0.0
        self._is_local_file: bool = False

        self._volume: float = 0.8
        self._pan: float = 0.0
        self._rate: float = 1.0
        self._replaygain_db: float = 0.0
        self._effects: dict[str, dict[str, Any]] = {
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

        self._auto_reconnect: bool = False
        self._reconnect_attempts: int = 0
        self._MAX_RECONNECT_ATTEMPTS = 5

        self._output_device_index: Optional[int] = None

        self._pcm_queue: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=QUEUE_MAXSIZE)
        self._decode_thread: Optional[threading.Thread] = None
        self._output_stream: Optional[sd.OutputStream] = None
        self._stop_flag = threading.Event()
        self._pause_flag = threading.Event()
        self._seek_request: Optional[float] = None

        # Filter graph state, rebuilt live on rate/effects change without
        # touching the decode thread's network connection.
        self._graph_lock = threading.Lock()
        self._graph = None
        self._graph_buf = None
        self._graph_sink = None
        self._applied_filter_spec: tuple[float, tuple[str, ...]] | None = None

        self._leftover = np.zeros((0, CHANNELS), dtype=np.float32)
        self._leftover_was_padded = False
        self._callback_lock = threading.Lock()

        # Every effect except pitch_tempo (which still needs a real
        # asetrate/atempo filter chain -- true pitch-shifting, not just a
        # gain/delay/filter op) runs through this instead of the filter
        # graph -- see dsp.py's module docstring for why. Applied in
        # _audio_callback right where volume/pan already are.
        self._effect_chain = dsp.EffectChain(DSP_CHAIN_ORDER)

        self._on_state_change: Optional[Callable[[str], None]] = None
        self._on_position_update: Optional[Callable[[float, float], None]] = None
        self._on_error: Optional[Callable[[str], None]] = None
        self._on_track_finished: Optional[Callable[[], None]] = None
        self._on_buffering: Optional[Callable[[int], None]] = None

    # ------------------------------------------------------------------
    # Callback setters (mirrors PlaybackEngine's API)
    # ------------------------------------------------------------------
    def on_state_change(self, cb: Callable[[str], None]) -> None:
        self._on_state_change = cb

    def on_position_update(self, cb: Callable[[float, float], None]) -> None:
        self._on_position_update = cb

    def on_error(self, cb: Callable[[str], None]) -> None:
        self._on_error = cb

    def on_track_finished(self, cb: Callable[[], None]) -> None:
        """Fired only when the stream reaches its own natural end (decoder
        ran out of packets) -- unlike on_state_change("stopped"), never
        fires for a user-initiated stop() or a crossfade_to() takeover, so
        callers can auto-advance a playlist without also triggering on a
        manual Stop press."""
        self._on_track_finished = cb

    def on_buffering(self, cb: Callable[[int], None]) -> None:
        """Reports how full the decode-ahead PCM queue is (0-100), the
        same cadence as on_position_update -- was defined on
        PlaybackEngine as a pass-through but never actually fed a value
        from anywhere, so nothing calling it ever saw a real number."""
        self._on_buffering = cb

    def _notify_state(self) -> None:
        if self._on_state_change:
            self._on_state_change(self._state)

    def _notify_error(self, message: str) -> None:
        if self._on_error:
            self._on_error(message)

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------
    def play(self, url: str, title: str = "", artist: str = "", duration: float = 0.0) -> None:
        self.stop()
        self._current_url = url
        self._current_title = title
        self._current_artist = artist
        self._duration = duration
        self._position = 0.0
        self._reconnect_attempts = 0
        self._leftover = np.zeros((0, CHANNELS), dtype=np.float32)
        self._leftover_was_padded = False

        self._state = self.STATE_BUFFERING
        self._notify_state()

        self._stop_flag.clear()
        self._pause_flag.clear()
        self._decode_thread = threading.Thread(target=self._run_decode, args=(url,), daemon=True)
        self._decode_thread.start()
        threading.Thread(target=self._position_notify_loop, daemon=True).start()

    def _position_notify_loop(self) -> None:
        """Poll self._position (kept current by the audio callback) and
        notify listeners a couple times a second. A dedicated low-rate
        thread rather than notifying from the decode loop directly: for a
        local file, decode finishes almost instantly, so tying
        notification cadence to decode iterations would fire a burst of
        stale updates instead of tracking real playback over time."""
        while not self._stop_flag.is_set():
            if self._on_position_update:
                self._on_position_update(self._position, self._duration)
            if self._on_buffering:
                percent = min(100, int(self._pcm_queue.qsize() * 100 / QUEUE_MAXSIZE))
                self._on_buffering(percent)
            time.sleep(0.5)

    def stop(self, wait: bool = True) -> None:
        """*wait=False* (app shutdown only -- see MainWindow._on_close)
        skips the decode thread join below entirely. It's a daemon
        thread, so it dies with the process regardless; the join only
        matters for a genuine Stop click during continued app use (so a
        following play() doesn't race the old thread). Blocking here
        during window close made EVT_CLOSE handling take up to 3s (longer
        if the decode thread was stuck in a network read with its own
        longer timeout) -- long enough that Inno Setup's own "close
        running applications before installing" wait gave up, leaving
        the old process still holding the exe/DLL files locked exactly
        when the installer tried to overwrite them ("DeleteFile failed;
        Access is denied").
        """
        if self._state == self.STATE_STOPPED and self._decode_thread is None:
            return
        self._stop_flag.set()
        if self._output_stream is not None:
            try:
                # abort(), not stop(): PortAudio's stop() is a *graceful*
                # stop that finishes playing whatever's already buffered
                # in the driver before returning -- audibly, Stop kept
                # playing for a bit before actually going silent. abort()
                # discards it and halts immediately.
                self._output_stream.abort()
                self._output_stream.close()
            except Exception:
                pass
            self._output_stream = None
        # Otherwise this stream's callback keeps running in the driver's
        # own thread even after the reference above is gone, and a
        # reconnect attempt already past its "am I stopped?" check when
        # stop() was called would still complete and call
        # _start_output_stream() again -- both together are exactly what
        # made Stop look like it just paused before playback resumed on
        # its own a moment later.
        self._pcm_queue = queue.Queue(maxsize=QUEUE_MAXSIZE)
        with self._callback_lock:
            self._leftover = np.zeros((0, CHANNELS), dtype=np.float32)
            self._leftover_was_padded = False
        if self._decode_thread is not None:
            if wait:
                self._decode_thread.join(timeout=3)
            self._decode_thread = None
        self._state = self.STATE_STOPPED
        self._position = 0.0
        self._notify_state()

    def pause(self) -> None:
        if self._state == self.STATE_PLAYING:
            self._pause_flag.set()
            self._state = self.STATE_PAUSED
            self._notify_state()

    def resume(self) -> None:
        if self._state == self.STATE_PAUSED:
            self._pause_flag.clear()
            self._state = self.STATE_PLAYING
            self._notify_state()

    def seek(self, position_seconds: float) -> None:
        # A local file is always finite/seekable; a remote URL is too as
        # long as it has a known duration (an on-demand file like a
        # podcast episode) -- ffmpeg's http protocol handler supports
        # Range-request seeking same as a local filesystem seek. Only a
        # genuinely unbounded live stream (radio -- duration always 0)
        # can't be meaningfully seeked. This previously gated on
        # _is_local_file alone, which silently no-op'd every remote URL
        # including podcast episodes -- exactly the case the transport
        # bar's seek slider/rewind/fast-forward are *enabled* for
        # (set_seekable(duration > 0), the same signal used here now).
        if self._is_local_file or self._duration > 0:
            self._seek_request = position_seconds

    # ------------------------------------------------------------------
    # Live controls -- volume/pan are pure numpy gain (instant, no graph
    # rebuild); rate/effects rebuild the filter graph (near-instant, no
    # network/decoder disruption).
    # ------------------------------------------------------------------
    def set_volume(self, volume: float) -> None:
        self._volume = max(0.0, min(1.0, volume))

    def set_pan(self, pan: float) -> None:
        self._pan = max(-1.0, min(1.0, pan))

    def set_replaygain_db(self, db: float) -> None:
        self._replaygain_db = db

    # Chunks of already-decoded, old-setting PCM left in the queue after a
    # rate/effects change instead of draining it to empty -- see
    # _drain_queue_for_immediate_effect for why full draining caused
    # exactly the "glitchy"/"chorus sounds terrible" symptom it was
    # reported as. ~170ms at 1024 samples/48kHz: long enough that the
    # output is never left with nothing real to play, short enough that
    # the change still feels close to instant.
    DRAIN_KEEP_CHUNKS = 8

    def _drain_queue_for_immediate_effect(self) -> None:
        """Trim (not empty) the queue so a rate/effects change is audible
        soon, without ever forcing the output completely dry.

        Volume/Pan are applied at the output callback itself (right as
        queued audio is consumed), so they're unaffected by queue depth
        and always feel instant. Rate and the filter-graph effects are
        baked into the audio *when it's decoded*, well before it reaches
        the queue -- so a change here only affects frames decoded from
        this point on. This used to drain the queue to fully empty, which
        for a real-time network stream (radio) forced the decode thread
        to refill the whole ~4s queue from scratch at whatever the
        network could sustain -- on a connection only marginally faster
        than the stream's own bitrate, that refill could take several
        seconds, with the queue trickling in a few chunks at a time and
        the output underrunning between each one: audible as a burst of
        glitches every time *any* effect was turned on, not just the one
        moment of the change itself, and worse yet on a modulating effect
        like chorus, where the choppy audio and the effect's own
        modulation compounded into "sounds terrible" rather than a single
        click. Leaving a small cushion means the output always has real
        (if briefly old-setting) audio to play while the decode thread
        catches back up, so it never needs to fabricate silence at all.
        """
        with self._callback_lock:
            self._leftover = np.zeros((0, CHANNELS), dtype=np.float32)
            self._leftover_was_padded = False
        while self._pcm_queue.qsize() > self.DRAIN_KEEP_CHUNKS:
            try:
                self._pcm_queue.get_nowait()
            except queue.Empty:
                break

    def set_rate(self, rate: float) -> None:
        self._rate = max(0.5, min(3.0, rate))
        self._drain_queue_for_immediate_effect()

    def set_auto_reconnect(self, enabled: bool) -> None:
        self._auto_reconnect = enabled

    def set_output_device(self, device_index: Optional[int]) -> None:
        """*device_index* is a sounddevice device index, or None for the
        system default. Rebuilding the output stream (not the decoder) is
        enough to move to a new device mid-playback."""
        self._output_device_index = device_index
        if self._output_stream is not None and self._state in (self.STATE_PLAYING, self.STATE_PAUSED):
            self._rebuild_output_stream()

    def _sync_dsp_stage(self, effect_id: str) -> None:
        """Push effect_id's current enabled/params into the DSP chain --
        instant, sample-accurate, no queue/graph involvement at all
        (unlike _drain_queue_for_immediate_effect's rate/pitch_tempo
        path, which still needs the graph rebuilt and a queue cushion
        since it's baked into the audio at decode time)."""
        make, apply_params = DSP_EFFECT_ADAPTERS[effect_id]
        state = self._effects[effect_id]
        self._effect_chain.set_stage(effect_id, state["enabled"], state["params"], make, apply_params)

    def toggle_effect(self, effect_id: str, enabled: bool) -> None:
        if effect_id not in self._effects:
            return
        self._effects[effect_id]["enabled"] = enabled
        if effect_id in DSP_EFFECT_ADAPTERS:
            self._sync_dsp_stage(effect_id)
        else:
            self._drain_queue_for_immediate_effect()

    def apply_preset(self, effect_id: str, preset_name: str, preset_params: dict[str, Any]) -> None:
        if effect_id not in self._effects:
            return
        self._effects[effect_id]["preset"] = preset_name
        self._effects[effect_id]["params"] = preset_params
        self._effects[effect_id]["enabled"] = True
        if effect_id in DSP_EFFECT_ADAPTERS:
            self._sync_dsp_stage(effect_id)
        else:
            self._drain_queue_for_immediate_effect()

    def get_effect_params(self, effect_id: str) -> dict[str, Any]:
        return self._effects.get(effect_id, {}).get("params", {})

    def apply_effect_params(self, effect_id: str, params: dict[str, Any]) -> None:
        if effect_id not in self._effects:
            return
        self._effects[effect_id]["params"] = params
        self._effects[effect_id]["enabled"] = True
        if effect_id in DSP_EFFECT_ADAPTERS:
            self._sync_dsp_stage(effect_id)
        else:
            self._drain_queue_for_immediate_effect()

    # ------------------------------------------------------------------
    # Filter graph management -- rate and pitch_tempo only; every other
    # effect is applied by self._effect_chain directly in _audio_callback.
    # ------------------------------------------------------------------
    def _current_filter_spec(self) -> tuple[float, tuple[str, ...]]:
        filters = _rate_and_pitch_filters(self._rate, self._effects)
        # A tuple, not a joined string: keeps each filter spec as its own
        # list element so nothing downstream ever needs to re-split a
        # joined string apart.
        return (self._rate, tuple(filters))

    def _build_graph(self, filter_specs: tuple[str, ...]):
        """Build and configure a filter graph from *filter_specs* (each a
        complete "name=args" entry -- see _current_filter_spec). Raises if
        any filter rejects its args -- libavfilter validates some filters'
        argument strings only at configure() time, not at add() time, so a
        bad args string (see build_effects_filters for real examples this
        caught) surfaces here, not where the filter was added."""
        graph = av.filter.Graph()
        buf = graph.add(
            "abuffer",
            sample_rate=str(SAMPLE_RATE),
            sample_fmt="fltp",
            channel_layout="stereo",
        )
        node = buf
        for spec in filter_specs:
            name, args = _parse_filter_spec(spec)
            nxt = graph.add(name, args) if args else graph.add(name)
            node.link_to(nxt)
            node = nxt
        sink = graph.add("abuffersink")
        node.link_to(sink)
        graph.configure()
        return graph, buf, sink

    def _ensure_graph(self) -> None:
        """(Re)build the filter graph if rate/effects have changed since
        the last chunk was processed. Cheap and instant -- no I/O."""
        spec = self._current_filter_spec()
        if spec == self._applied_filter_spec and self._graph is not None:
            return
        _rate, filter_specs = spec
        try:
            graph, buf, sink = self._build_graph(filter_specs)
        except Exception as e:
            # A bad filter combination must not take the whole stream
            # down with it (see the module docstring's account of
            # firequalizer/compand/aecho args that looked fine at add()
            # time and only failed here) -- fall back to a plain
            # passthrough graph so playback keeps going, just without
            # whatever effect/rate change just broke it.
            logger.warning(f"Live filter graph {filter_specs} failed ({e}); falling back to passthrough")
            graph, buf, sink = self._build_graph(())
        self._graph = graph
        self._graph_buf = buf
        self._graph_sink = sink
        self._applied_filter_spec = spec

    def _filter_frame(self, frame) -> list[np.ndarray]:
        """Push a decoded frame through the (possibly just-rebuilt) filter
        graph and pull out zero or more resulting PCM chunks, shaped
        (samples, channels) float32."""
        with self._graph_lock:
            self._ensure_graph()
            out_chunks = []
            try:
                self._graph_buf.push(frame)
            except Exception:
                return out_chunks
            while True:
                try:
                    out = self._graph_sink.pull()
                except (av.EOFError, av.error.BlockingIOError, EOFError):
                    break
                except Exception:
                    break
                arr = out.to_ndarray()
                if arr.ndim == 1:
                    arr = arr.reshape(1, -1)
                if arr.shape[0] != CHANNELS:
                    # Some filters (atempo among them) emit packed/interleaved
                    # "flt" frames instead of the planar "fltp" the graph was
                    # fed -- to_ndarray() then returns (1, samples*channels)
                    # as one flat L,R,L,R,... row. reshape(CHANNELS, -1) would
                    # silently slice that flat buffer in half instead of
                    # deinterleaving it, scrambling every sample (audible as
                    # bad pitch/speed artifacts, not just wrong stereo image).
                    # reshape(-1, CHANNELS).T groups each consecutive
                    # CHANNELS-sample run as one frame before transposing,
                    # which is the correct inverse of interleaving.
                    arr = arr.reshape(-1, CHANNELS).T
                pcm = np.ascontiguousarray(arr.T.astype(np.float32))
                out_chunks.append(pcm)
            return out_chunks

    # ------------------------------------------------------------------
    # Decode thread
    # ------------------------------------------------------------------
    def _run_decode(self, url: str) -> None:
        import os
        self._is_local_file = os.path.isfile(url)
        try:
            self._decode_loop(url)
        except Exception as e:
            if not self._stop_flag.is_set():
                logger.error(f"Decode error: {e}")
                self._handle_decode_failure(_describe_stream_error(e))

    def _handle_decode_failure(self, message: str) -> None:
        if (self._auto_reconnect and self._duration == 0.0 and self._current_url
                and self._reconnect_attempts < self._MAX_RECONNECT_ATTEMPTS
                and not self._stop_flag.is_set()):
            self._reconnect_attempts += 1
            self._state = self.STATE_BUFFERING
            self._notify_state()
            time.sleep(2.0)
            if self._stop_flag.is_set():
                return
            try:
                self._decode_loop(self._current_url)
                return
            except Exception as e2:
                self._handle_decode_failure(_describe_stream_error(e2))
                return
        if self._auto_reconnect and self._reconnect_attempts >= self._MAX_RECONNECT_ATTEMPTS:
            self._notify_error("Lost connection to the stream and could not reconnect.")
        else:
            self._notify_error(f"Playback failed: {message}")
        self._state = self.STATE_STOPPED
        self._notify_state()

    def _decode_loop(self, url: str) -> None:
        from radiomaster.utils.logging_setup import log_io
        log_io(logger, "av.open %s", url)
        container = av.open(url, timeout=10, metadata_errors="replace")
        try:
            stream = next((s for s in container.streams if s.type == "audio"), None)
            if stream is None:
                raise RuntimeError("No audio stream found")
            resampler = av.AudioResampler(format="fltp", layout="stereo", rate=SAMPLE_RATE)

            if self._stop_flag.is_set():
                # Opening the container (can take seconds, e.g. a fresh
                # TCP connection on a reconnect attempt) is the one place
                # this loop went a while without checking stop_flag.
                # Without this, Stop clicked during that window still let
                # a reconnect finish and start a brand new output stream
                # right after -- Stop looked like it worked (briefly
                # silent) and then played anyway moments later.
                return
            self._start_output_stream()
            self._state = self.STATE_PLAYING
            self._notify_state()
            self._reconnect_attempts = 0

            for packet in container.demux(stream):
                if self._stop_flag.is_set():
                    return
                if self._seek_request is not None:
                    try:
                        container.seek(int(self._seek_request * av.time_base))
                        self._position = self._seek_request
                        # Local-file decode can run well ahead of
                        # real-time (nothing throttles it like a network
                        # stream does), leaving several seconds of
                        # already-decoded pre-seek audio sitting in the
                        # queue. Without discarding it, playback would
                        # keep going for a few seconds before actually
                        # jumping -- clear it so the jump is immediate.
                        with self._callback_lock:
                            self._leftover = np.zeros((0, CHANNELS), dtype=np.float32)
                            self._leftover_was_padded = False
                        while True:
                            try:
                                self._pcm_queue.get_nowait()
                            except queue.Empty:
                                break
                    except Exception:
                        pass
                    self._seek_request = None
                for frame in packet.decode():
                    if self._stop_flag.is_set():
                        return
                    for rframe in resampler.resample(frame):
                        for pcm in self._filter_frame(rframe):
                            while not self._stop_flag.is_set():
                                try:
                                    self._pcm_queue.put(pcm, timeout=0.5)
                                    break
                                except queue.Full:
                                    continue
            # Demuxer ran out of packets -- natural end of stream/track.
            if not self._stop_flag.is_set():
                if self._auto_reconnect and self._duration == 0.0:
                    raise RuntimeError("stream ended unexpectedly")
                # Let any buffered audio finish playing before reporting stopped.
                deadline = time.time() + 5
                while not self._pcm_queue.empty() and time.time() < deadline:
                    time.sleep(0.1)
                self._state = self.STATE_STOPPED
                self._notify_state()
                if self._on_track_finished:
                    self._on_track_finished()
        finally:
            try:
                container.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Output stream (sounddevice / WASAPI)
    # ------------------------------------------------------------------
    def _start_output_stream(self) -> None:
        # A reconnect calls this again on the same engine instance without
        # going through stop() first. Without closing the previous stream,
        # its callback keeps running in the background right alongside the
        # new one -- two callbacks both consuming the queue and both
        # incrementing self._position concurrently, which looked like
        # position racing ahead of real time (each reconnect compounded
        # it further).
        old = self._output_stream
        self._output_stream = sd.OutputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="float32",
            blocksize=BLOCKSIZE,
            latency="high",
            device=self._output_device_index,
            callback=self._audio_callback,
        )
        self._output_stream.start()
        if old is not None:
            try:
                old.stop()
                old.close()
            except Exception:
                pass

    def _rebuild_output_stream(self) -> None:
        old = self._output_stream
        try:
            new = sd.OutputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="float32",
                blocksize=BLOCKSIZE,
                latency="high",
                device=self._output_device_index,
                callback=self._audio_callback,
            )
            new.start()
            self._output_stream = new
            if old is not None:
                old.stop()
                old.close()
        except Exception as e:
            self._notify_error(f"Failed to switch output device: {e}")

    def _fade_underrun_edges(self, block: np.ndarray, pad: np.ndarray) -> np.ndarray:
        """Ramp through every real-audio/synthesized-silence boundary in
        *block* instead of leaving the raw sample-value jump a hard cut
        produces -- that jump is what's audible as a "click"/"artifact",
        not merely the underrun itself. A brief, otherwise-unnoticed gap
        reads as a soft dropout instead of a pop this way."""
        n = block.shape[0]
        if n == 0:
            return block
        transitions = np.flatnonzero(pad[1:] != pad[:-1]) + 1
        for idx in transitions:
            if pad[idx]:  # real audio ending, silence starting -- fade OUT
                start = max(0, idx - FADE_SAMPLES)
                ramp = np.linspace(1.0, 0.0, idx - start, dtype=np.float32).reshape(-1, 1)
                block[start:idx] *= ramp
            else:  # silence ending, real audio resuming -- fade IN
                end = min(n, idx + FADE_SAMPLES)
                ramp = np.linspace(0.0, 1.0, end - idx, dtype=np.float32).reshape(-1, 1)
                block[idx:end] *= ramp
        # If this block's tail is real audio but the queue is now empty,
        # taper toward zero pre-emptively in case the *next* callback
        # comes up dry too -- there's no way to fix a hard cut after the
        # fact once it's already been handed to the output device, so this
        # has to happen before that cut can occur. Harmless (inaudible)
        # even on the common case where the decode thread actually does
        # refill in time and this fade turns out not to have been needed.
        if not pad[-1] and self._pcm_queue.empty():
            start = max(0, n - FADE_SAMPLES)
            ramp = np.linspace(1.0, 0.0, n - start, dtype=np.float32).reshape(-1, 1)
            block[start:] *= ramp
        return block

    def _audio_callback(self, outdata: np.ndarray, frames: int, time_info, status) -> None:
        with self._callback_lock:
            if self._pause_flag.is_set():
                outdata.fill(0.0)
                return
            need = frames
            chunks = [self._leftover]
            pad_flags = [self._leftover_was_padded]
            have = self._leftover.shape[0]
            while have < need:
                try:
                    chunk = self._pcm_queue.get_nowait()
                    pad_flags.append(False)
                except queue.Empty:
                    chunk = np.zeros((need - have, CHANNELS), dtype=np.float32)
                    pad_flags.append(True)
                chunks.append(chunk)
                have += chunk.shape[0]
            combined = np.concatenate(chunks, axis=0)
            pad_mask = np.concatenate([
                np.full(c.shape[0], p, dtype=bool) for c, p in zip(chunks, pad_flags)
            ])
            block = combined[:need]
            block_pad = pad_mask[:need]
            self._leftover = combined[need:]
            leftover_pad = pad_mask[need:]
            self._leftover_was_padded = bool(leftover_pad[0]) if leftover_pad.shape[0] else False

            block = self._fade_underrun_edges(block, block_pad)

            # DSP effect chain, applied to normalized [-1, 1] samples
            # before volume/pan/mute -- matches where the old ffmpeg -af
            # chain used to sit in the pipeline (upstream of this gain
            # stage), but live and stateful instead of baked into decode.
            block = self._effect_chain.process(block)

            gain = self._volume * (10 ** (self._replaygain_db / 20) if self._replaygain_db else 1.0)
            block = block * gain
            if self._pan != 0.0:
                left_gain = 1.0 - max(0.0, self._pan)
                right_gain = 1.0 - max(0.0, -self._pan)
                block = block * np.array([left_gain, right_gain], dtype=np.float32)
            np.clip(block, -1.0, 1.0, out=block)
            outdata[:] = block
            # Position tracks samples actually consumed here (what's
            # genuinely audible), not decode progress -- those only
            # coincide for a network stream, where decode throughput
            # happens to track real-time. A local file decodes almost
            # instantly, which raced this far ahead of real playback when
            # position was tracked from decoded-frame timestamps instead.
            self._position += frames / SAMPLE_RATE

    # ------------------------------------------------------------------
    # Accessors (mirrors PlaybackEngine)
    # ------------------------------------------------------------------
    @property
    def state(self) -> str:
        return self._state

    @property
    def position(self) -> float:
        return self._position

    @property
    def duration(self) -> float:
        return self._duration

    @property
    def volume(self) -> float:
        return self._volume

    @property
    def rate(self) -> float:
        return self._rate

    @property
    def pan(self) -> float:
        return self._pan
