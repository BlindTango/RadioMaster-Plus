"""Real-time, sample-domain audio effects DSP chain.

Every effect used to compile to an ffmpeg `-af` libavfilter string, baked
into a filter graph rebuilt on every parameter change (see
build_effects_filters() in live_audio_engine.py, still used for rate/
pitch_tempo). For a radio stream, rebuilding that graph meant discarding
buffered audio and forcing the decode thread to refill the queue over the
network from scratch -- even with the cushion/debounce mitigations added
earlier, turning any effect on could still produce a burst of underruns
while the queue caught back up, worse on a modulating effect like Chorus
where the choppy audio and the effect's own modulation compounded into an
audibly "not clear" result. A single bad filter argument (an aecho decay
of exactly 0, firequalizer's gain_entry syntax, ...) could also fail only
at graph-configure time, well after it looked fine at add() time.

This module replaces the 9 non-pitch-shifting effects with a chain of
stateful DSP processors applied directly to already-decoded PCM samples
inside the sounddevice output callback (LiveAudioEngine._audio_callback),
the same place volume/pan/mute are already applied. Effects can be
switched on/off or re-parameterized instantly, mid-stream, with zero
network/decode/queue involvement and no way to crash the stream -- worst
case a bad parameter produces a stale or slightly-off sound for one
block, never a dead process or a glitch burst.

Ported from a proven design in a sibling project (D:\\projects\\RadioMaster,
core/dsp.py) -- ADAPTED to this app's own SAMPLE_RATE (48000, not 44100)
and to effects_data.py's existing parameter names/ranges (so no UI or
preset-schema changes were needed), not a line-for-line copy. These are
deliberately not bit-exact reimplementations of the old ffmpeg filters --
they're standard/well-known DSP techniques tuned to sound close to the
effect each one replaces.

Every processor works on float32 sample blocks shaped (n_frames, channels)
in the normalized range roughly [-1.0, 1.0], and exposes:
  - update(params: dict) -- push new parameters; safe from any thread (see
    EffectChain's GIL-atomicity reasoning below)
  - process(samples) -> samples, called once per audio block from the
    real-time output callback
"""

from __future__ import annotations

import math
import threading

import numpy as np

SAMPLE_RATE = 48000
CHANNELS = 2

# Matches effects_data.py PARAM_DEFS["equalizer"]'s band keys/frequencies
# exactly -- "32" -> 32 Hz, "1k" -> 1000 Hz, etc.
EQ_BAND_KEYS = ("32", "64", "125", "250", "500", "1k", "2k", "4k", "8k", "16k")
EQ_BAND_HZ = {"32": 32, "64": 64, "125": 125, "250": 250, "500": 500,
              "1k": 1000, "2k": 2000, "4k": 4000, "8k": 8000, "16k": 16000}


class _Biquad:
    """One RBJ-cookbook peaking-EQ biquad, direct form I, single channel."""

    __slots__ = ("b0", "b1", "b2", "a1", "a2", "x1", "x2", "y1", "y2")

    def __init__(self) -> None:
        self.b0 = 1.0
        self.b1 = 0.0
        self.b2 = 0.0
        self.a1 = 0.0
        self.a2 = 0.0
        self.x1 = 0.0
        self.x2 = 0.0
        self.y1 = 0.0
        self.y2 = 0.0

    def set_peaking(self, fs: float, freq_hz: float, gain_db: float, bw_oct: float = 1.0) -> None:
        freq_hz = min(max(freq_hz, 10.0), fs * 0.49)
        A = 10.0 ** (gain_db / 40.0)
        w0 = 2.0 * math.pi * freq_hz / fs
        sin_w0 = math.sin(w0)
        cos_w0 = math.cos(w0)
        alpha = sin_w0 * math.sinh(math.log(2.0) / 2.0 * bw_oct * (w0 / sin_w0)) if sin_w0 else 1e-6
        b0 = 1.0 + alpha * A
        b1 = -2.0 * cos_w0
        b2 = 1.0 - alpha * A
        a0 = 1.0 + alpha / A
        a1 = -2.0 * cos_w0
        a2 = 1.0 - alpha / A
        self.b0, self.b1, self.b2 = b0 / a0, b1 / a0, b2 / a0
        self.a1, self.a2 = a1 / a0, a2 / a0

    def process_sample(self, x: float) -> float:
        y = self.b0 * x + self.b1 * self.x1 + self.b2 * self.x2 - self.a1 * self.y1 - self.a2 * self.y2
        self.x2 = self.x1
        self.x1 = x
        self.y2 = self.y1
        self.y1 = y
        return y


class Equalizer:
    """10-band graphic EQ: one cascaded peaking biquad per band (fixed
    1-octave bandwidth), applied independently to each channel."""

    def __init__(self, fs: int = SAMPLE_RATE) -> None:
        self.fs = fs
        self._bands_l = [_Biquad() for _ in EQ_BAND_KEYS]
        self._bands_r = [_Biquad() for _ in EQ_BAND_KEYS]

    def update(self, params: dict) -> None:
        for band_l, band_r, key in zip(self._bands_l, self._bands_r, EQ_BAND_KEYS):
            gain_db = float(params.get(key, 0.0))
            band_l.set_peaking(self.fs, EQ_BAND_HZ[key], gain_db)
            band_r.set_peaking(self.fs, EQ_BAND_HZ[key], gain_db)

    def process(self, x: np.ndarray) -> np.ndarray:
        left = x[:, 0].tolist()
        right = x[:, 1].tolist()
        for band in self._bands_l:
            left = [band.process_sample(v) for v in left]
        for band in self._bands_r:
            right = [band.process_sample(v) for v in right]
        return np.column_stack((left, right)).astype(np.float32)


class Compressor:
    """Feed-forward dynamic-range compressor with a soft knee, linked
    stereo (peak of both channels drives one gain envelope so the effect
    doesn't shift the stereo image), attack/release-smoothed gain.

    Shared by both "compressor" and "dynamic_range" (their adapter
    functions in live_audio_engine.py convert each effect's own
    threshold units -- linear vs dB -- before calling update() here)."""

    def __init__(self, fs: int = SAMPLE_RATE) -> None:
        self.fs = fs
        self.threshold = 0.125
        self.ratio = 2.0
        self.attack_ms = 20.0
        self.release_ms = 250.0
        self.makeup = 1.0
        self.knee_db = 2.82843
        self.mix = 1.0
        self._level = 0.0
        self._gain_smoothed_db = 0.0

    def update(self, params: dict) -> None:
        self.threshold = max(0.001, float(params.get("threshold", self.threshold)))
        self.ratio = max(1.0, float(params.get("ratio", self.ratio)))
        self.attack_ms = max(0.01, float(params.get("attack", self.attack_ms)))
        self.release_ms = max(0.01, float(params.get("release", self.release_ms)))
        self.makeup = float(params.get("makeup", self.makeup))
        self.knee_db = max(0.001, float(params.get("knee", self.knee_db)))
        self.mix = max(0.0, min(1.0, float(params.get("mix", self.mix))))

    def process(self, x: np.ndarray) -> np.ndarray:
        n = x.shape[0]
        left = x[:, 0].tolist()
        right = x[:, 1].tolist()
        out_l = [0.0] * n
        out_r = [0.0] * n
        fs = self.fs
        attack_coef = math.exp(-1.0 / ((self.attack_ms / 1000.0) * fs))
        release_coef = math.exp(-1.0 / ((self.release_ms / 1000.0) * fs))
        threshold_db = 20.0 * math.log10(self.threshold)
        ratio = self.ratio
        knee_db = self.knee_db
        makeup = self.makeup
        mix = self.mix
        level = self._level
        gsm = self._gain_smoothed_db
        for i in range(n):
            l, r = left[i], right[i]
            peak = max(abs(l), abs(r))
            if peak > level:
                level = attack_coef * level + (1.0 - attack_coef) * peak
            else:
                level = release_coef * level + (1.0 - release_coef) * peak
            level_db = 20.0 * math.log10(max(1e-6, level))
            delta = level_db - threshold_db
            if 2.0 * delta < -knee_db:
                target_gain_db = 0.0
            elif 2.0 * abs(delta) <= knee_db:
                target_gain_db = (1.0 / ratio - 1.0) * (delta + knee_db / 2.0) ** 2 / (2.0 * knee_db)
            else:
                target_gain_db = (threshold_db + delta / ratio) - level_db
            if target_gain_db < gsm:
                gsm = attack_coef * gsm + (1.0 - attack_coef) * target_gain_db
            else:
                gsm = release_coef * gsm + (1.0 - release_coef) * target_gain_db
            gain_lin = (10.0 ** (gsm / 20.0)) * makeup
            out_l[i] = l * (1.0 - mix) + (l * gain_lin) * mix
            out_r[i] = r * (1.0 - mix) + (r * gain_lin) * mix
        self._level = level
        self._gain_smoothed_db = gsm
        return np.column_stack((out_l, out_r)).astype(np.float32)


class BitCrusher:
    """Bit-depth reduction (quantization) distortion, wet/dry mixed --
    matches effects_data.py's "Bit Depth"/"Mix" parameters directly
    (unlike ffmpeg's acrusher, which this replaces, there's no separate
    "mode" concept to approximate). Fully vectorized (stateless)."""

    def __init__(self) -> None:
        self.bits = 8
        self.mix = 0.6

    def update(self, params: dict) -> None:
        self.bits = max(1, min(16, int(params.get("bits", self.bits))))
        self.mix = max(0.0, min(1.0, float(params.get("mix", self.mix))))

    def process(self, x: np.ndarray) -> np.ndarray:
        levels = float(2 ** self.bits)
        crushed = np.round(x * (levels / 2.0)) / (levels / 2.0)
        crushed = np.clip(crushed, -1.0, 1.0)
        return (x * (1.0 - self.mix) + crushed * self.mix).astype(np.float32)


class MultiTapDelay:
    """Shared engine behind both Echo (one tap) and Reverb (several taps
    at fixed offsets). A single recirculating delay line is fed the
    filter's OWN output (not just the dry input), so each tap's history
    includes previous echoes too -- producing a natural decaying repeat/
    tail rather than one flat, single reflection."""

    def __init__(self, fs: int = SAMPLE_RATE) -> None:
        self.fs = fs
        self._buf_l = [0.0]
        self._buf_r = [0.0]
        self._cap = 1
        self._write_pos = 0
        self.in_gain = 1.0
        self.out_gain = 1.0
        self._taps: list[tuple[int, float]] = []  # (delay_samples, decay)

    def set_taps(self, in_gain: float, out_gain: float, taps_ms_decay: list) -> None:
        self.in_gain = in_gain
        self.out_gain = out_gain
        taps = [(max(1, int(delay_ms * self.fs / 1000.0)), decay) for delay_ms, decay in taps_ms_decay]
        self._taps = taps
        needed = max((d for d, _ in taps), default=1) + 2
        if needed > self._cap:
            self._buf_l = [0.0] * needed
            self._buf_r = [0.0] * needed
            self._cap = needed
            self._write_pos = 0

    def process(self, x: np.ndarray) -> np.ndarray:
        n = x.shape[0]
        left = x[:, 0].tolist()
        right = x[:, 1].tolist()
        out_l = [0.0] * n
        out_r = [0.0] * n
        buf_l, buf_r, cap = self._buf_l, self._buf_r, self._cap
        wp = self._write_pos
        taps = self._taps
        in_gain, out_gain = self.in_gain, self.out_gain
        for i in range(n):
            dry_l = left[i] * in_gain
            dry_r = right[i] * in_gain
            wet_l = 0.0
            wet_r = 0.0
            for delay_samples, decay in taps:
                idx = wp - delay_samples
                if idx < 0:
                    idx += cap
                wet_l += buf_l[idx] * decay
                wet_r += buf_r[idx] * decay
            y_l = (dry_l + wet_l) * out_gain
            y_r = (dry_r + wet_r) * out_gain
            out_l[i] = y_l
            out_r[i] = y_r
            buf_l[wp] = y_l
            buf_r[wp] = y_r
            wp += 1
            if wp >= cap:
                wp = 0
        self._write_pos = wp
        return np.column_stack((out_l, out_r)).astype(np.float32)


class ModulatedDelay:
    """LFO-modulated short delay line shared by Flanger and Chorus -- they
    differ only in typical delay/depth/speed ranges and whether feedback
    (regeneration) is used, which each effect's adapter function supplies."""

    def __init__(self, fs: int = SAMPLE_RATE, max_delay_ms: float = 120.0) -> None:
        self.fs = fs
        cap = int(fs * (max_delay_ms / 1000.0)) + 8
        self._buf_l = [0.0] * cap
        self._buf_r = [0.0] * cap
        self._cap = cap
        self._write_pos = 0
        self._phase = 0.0
        self.base_delay_ms = 20.0
        self.depth_ms = 2.0
        self.speed_hz = 0.5
        self.feedback = 0.0
        self.mix = 0.5
        self.phase_deg = 0.0
        self.in_gain = 1.0
        self.out_gain = 1.0

    def update(self, params: dict) -> None:
        self.base_delay_ms = float(params.get("base_delay_ms", self.base_delay_ms))
        self.depth_ms = float(params.get("depth_ms", self.depth_ms))
        self.speed_hz = max(0.001, float(params.get("speed_hz", self.speed_hz)))
        self.feedback = max(-0.95, min(0.95, float(params.get("feedback", self.feedback))))
        self.mix = max(0.0, min(1.0, float(params.get("mix", self.mix))))
        self.phase_deg = float(params.get("phase_deg", self.phase_deg))
        self.in_gain = float(params.get("in_gain", self.in_gain))
        self.out_gain = float(params.get("out_gain", self.out_gain))
        needed = int(self.fs * ((self.base_delay_ms + self.depth_ms) / 1000.0)) + 8
        if needed > self._cap:
            self._buf_l = [0.0] * needed
            self._buf_r = [0.0] * needed
            self._cap = needed
            self._write_pos = 0

    def process(self, x: np.ndarray) -> np.ndarray:
        n = x.shape[0]
        left = x[:, 0].tolist()
        right = x[:, 1].tolist()
        out_l = [0.0] * n
        out_r = [0.0] * n
        buf_l, buf_r, cap = self._buf_l, self._buf_r, self._cap
        wp = self._write_pos
        phase = self._phase
        w = 2.0 * math.pi * self.speed_hz / self.fs
        depth_samples = self.depth_ms / 1000.0 * self.fs
        base_samples = self.base_delay_ms / 1000.0 * self.fs
        phase_off = math.radians(self.phase_deg)
        fb = self.feedback
        mix = self.mix
        in_gain, out_gain = self.in_gain, self.out_gain
        for i in range(n):
            lfo_l = math.sin(phase)
            lfo_r = math.sin(phase + phase_off)
            d_l = max(1.0, base_samples + depth_samples * lfo_l)
            d_r = max(1.0, base_samples + depth_samples * lfo_r)

            rp_l = wp - d_l
            i0 = int(math.floor(rp_l))
            frac = rp_l - i0
            i0 %= cap
            i1 = (i0 + 1) % cap
            dly_l = buf_l[i0] * (1.0 - frac) + buf_l[i1] * frac

            rp_r = wp - d_r
            i0r = int(math.floor(rp_r))
            frac_r = rp_r - i0r
            i0r %= cap
            i1r = (i0r + 1) % cap
            dly_r = buf_r[i0r] * (1.0 - frac_r) + buf_r[i1r] * frac_r

            xl = left[i] * in_gain
            xr = right[i] * in_gain
            buf_l[wp] = xl + fb * dly_l
            buf_r[wp] = xr + fb * dly_r
            out_l[i] = (xl * (1.0 - mix) + dly_l * mix) * out_gain
            out_r[i] = (xr * (1.0 - mix) + dly_r * mix) * out_gain

            wp += 1
            if wp >= cap:
                wp = 0
            phase += w
        self._write_pos = wp
        self._phase = math.fmod(phase, 2.0 * math.pi)
        return np.column_stack((out_l, out_r)).astype(np.float32)


class Tremolo:
    """Amplitude-modulation approximation of Gargle -- fully vectorized
    sinusoidal tremolo, matching the old ffmpeg `tremolo` filter this
    effect used to compile to."""

    def __init__(self, fs: int = SAMPLE_RATE) -> None:
        self.fs = fs
        self.freq = 5.0
        self.depth = 0.5
        self._phase = 0.0

    def update(self, params: dict) -> None:
        self.freq = max(0.01, float(params.get("frequency_hz", self.freq)))
        self.depth = max(0.0, min(1.0, float(params.get("depth", self.depth))))

    def process(self, x: np.ndarray) -> np.ndarray:
        n = x.shape[0]
        w = 2.0 * math.pi * self.freq / self.fs
        t = self._phase + w * np.arange(n, dtype=np.float64)
        lfo = (1.0 - self.depth * 0.5 * (1.0 + np.sin(t))).astype(np.float32).reshape(-1, 1)
        self._phase = math.fmod(self._phase + w * n, 2.0 * math.pi)
        return (x * lfo).astype(np.float32)


class LoudnessNormalizer:
    """Causal automatic gain control approximating ffmpeg's dynaudnorm:
    rides a smoothed RMS envelope toward a target loudness, capped by a
    maximum gain. dynaudnorm's actual Gaussian-smoothed window looks
    slightly into the future, which doesn't exist for a live stream; this
    uses causal exponential smoothing instead, the standard real-time
    substitute. Asymmetric attack/release: gain comes down fast (a loud
    passage just arrived -- clamp before it clips) but rises slowly (a
    brief quiet gap between tracks must not be enough to crank gain all
    the way up before the next track arrives already-loud through an
    over-inflated gain)."""

    def __init__(self, fs: int = SAMPLE_RATE) -> None:
        self.fs = fs
        self.target_rms = 0.2
        self.max_gain = 15.0
        # None until the first process() call, which seeds it to the
        # target level rather than silence -- starting from 0.0 made the
        # very first block look like near-total silence, spiking gain to
        # max_gain and clipping the already-normal-level real audio for
        # the ~0.5-1s the envelope needed to catch up.
        self._rms_env = None
        self._gain_smoothed = 1.0

    def update(self, params: dict) -> None:
        self.target_rms = max(0.001, float(params.get("target_rms", self.target_rms)))
        self.max_gain = max(1.0, float(params.get("max_gain", self.max_gain)))

    def process(self, x: np.ndarray) -> np.ndarray:
        n = x.shape[0]
        left = x[:, 0].tolist()
        right = x[:, 1].tolist()
        out_l = [0.0] * n
        out_r = [0.0] * n
        if self._rms_env is None:
            self._rms_env = self.target_rms ** 2
        rms_env = self._rms_env
        gain = self._gain_smoothed
        alpha_rms = math.exp(-1.0 / (0.5 * self.fs))          # ~500ms measurement window
        alpha_gain_down = math.exp(-1.0 / (0.03 * self.fs))   # ~30ms
        alpha_gain_up = math.exp(-1.0 / (3.0 * self.fs))      # ~3s
        target_rms = self.target_rms
        max_gain = self.max_gain
        for i in range(n):
            l, r = left[i], right[i]
            power = (l * l + r * r) * 0.5
            rms_env = alpha_rms * rms_env + (1.0 - alpha_rms) * power
            rms = math.sqrt(max(rms_env, 1e-8))
            desired = min(max_gain, max(0.1, target_rms / max(rms, 1e-4)))
            alpha_gain = alpha_gain_down if desired < gain else alpha_gain_up
            gain = alpha_gain * gain + (1.0 - alpha_gain) * desired
            out_l[i] = max(-1.0, min(1.0, l * gain))
            out_r[i] = max(-1.0, min(1.0, r * gain))
        self._rms_env = rms_env
        self._gain_smoothed = gain
        return np.column_stack((out_l, out_r)).astype(np.float32)


class EffectChain:
    """Ordered, hot-swappable chain of DSP effect processors, applied
    directly to decoded PCM samples inside the real-time output audio
    callback (see LiveAudioEngine._audio_callback) -- the same place
    volume/pan/mute are already applied.

    set_stage() is called from the UI thread (settings/preset changes);
    process() is called from sounddevice's real-time audio thread. Rather
    than share a lock across both (which could stall the audio thread
    behind a slow UI-thread update), process() reads the enabled-set and
    processor dict without locking: CPython's GIL makes each individual
    dict/set access atomic, so the worst case is a one-block-late
    parameter update -- never a crash or a torn read.
    """

    def __init__(self, order: list[str]) -> None:
        self._order = list(order)
        self._processors: dict[str, object] = {}
        self._enabled: set[str] = set()
        self._lock = threading.Lock()

    def set_stage(self, effect_id: str, enabled: bool, params: dict, make_processor, apply_params) -> None:
        with self._lock:
            if not enabled:
                self._enabled.discard(effect_id)
                return
            proc = self._processors.get(effect_id)
            if proc is None:
                proc = make_processor()
                self._processors[effect_id] = proc
            apply_params(proc, params)
            self._enabled.add(effect_id)

    def is_enabled(self, effect_id: str) -> bool:
        return effect_id in self._enabled

    def process(self, samples: np.ndarray) -> np.ndarray:
        for effect_id in self._order:
            if effect_id in self._enabled:
                proc = self._processors.get(effect_id)
                if proc is not None:
                    samples = proc.process(samples)
        return samples
