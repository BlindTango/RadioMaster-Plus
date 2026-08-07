"""Central data for the Effects menu: which effects exist, their
adjustable parameters, and their built-in presets.

Filter mapping (verified against PyAV's bundled libavfilter before use --
see build_effects_filters() in engine/live_audio_engine.py for the actual
"name=args" strings):
    echo        -> aecho (single delayed repeat)
    equalizer   -> firequalizer (10-band)
    reverb      -> aecho with multiple pipe-separated delay/decay taps
                   (ffmpeg has no dedicated reverb filter; chaining several
                   echo taps at different delays is the standard technique
                   for simulating room reflections with aecho alone)
    dynamic_range -> compand
    pitch_tempo -> asetrate+aresample+atempo chain
    chorus      -> chorus
    compressor  -> acompressor (a distinct filter/character from compand,
                   despite both being "dynamics" processors -- kept
                   separate because that's what was asked for)
    distortion  -> acrusher (bit-crusher; ffmpeg has no analog-style
                   distortion filter)
    flanger     -> flanger
    gargle      -> tremolo, as an amplitude-modulation approximation --
                   ffmpeg has no filter literally called "gargle" (that's
                   a Windows DirectSound-specific effect); tremolo's
                   amplitude modulation at a gargle-appropriate rate
                   produces the same warbling character
"""

from typing import Any

# Display order in the Effects menu.
EFFECT_IDS = [
    "echo", "equalizer", "reverb", "dynamic_range", "pitch_tempo",
    "chorus", "compressor", "distortion", "flanger", "gargle",
]

EFFECT_LABELS: dict[str, str] = {
    "echo": "Echo",
    "equalizer": "Equalizer",
    "reverb": "Reverb",
    "dynamic_range": "Dynamic Range",
    "pitch_tempo": "Pitch/Tempo Shift",
    "chorus": "Chorus",
    "compressor": "Compressor",
    "distortion": "Distortion",
    "flanger": "Flanger",
    "gargle": "Gargle",
}

# (label, param key, min, max, default)
PARAM_DEFS: dict[str, list[tuple[str, str, float, float, float]]] = {
    "echo": [
        ("Delay (ms)", "delay", 5, 1000, 500),
        ("Decay", "decay", 0.0, 1.0, 0.4),
        ("In Gain", "in_gain", 0.0, 1.0, 0.8),
        ("Out Gain", "out_gain", 0.0, 1.0, 0.88),
    ],
    "equalizer": [
        ("32 Hz", "32", -12, 12, 0),
        ("64 Hz", "64", -12, 12, 0),
        ("125 Hz", "125", -12, 12, 0),
        ("250 Hz", "250", -12, 12, 0),
        ("500 Hz", "500", -12, 12, 0),
        ("1 kHz", "1k", -12, 12, 0),
        ("2 kHz", "2k", -12, 12, 0),
        ("4 kHz", "4k", -12, 12, 0),
        ("8 kHz", "8k", -12, 12, 0),
        ("16 kHz", "16k", -12, 12, 0),
    ],
    "reverb": [
        ("Room Size", "room_size", 0.1, 1.0, 0.4),
        ("Decay", "decay", 0.0, 1.0, 0.4),
        ("Mix", "mix", 0.0, 1.0, 0.3),
    ],
    "dynamic_range": [
        ("Threshold (dB)", "threshold", -60, 0, -20),
        ("Ratio:1", "ratio", 1, 20, 4),
        ("Knee (dB)", "knee", 0, 30, 10),
        ("Attack (ms)", "attack", 0.1, 20, 5),
        ("Release (ms)", "release", 5, 500, 50),
    ],
    "pitch_tempo": [
        ("Cents (-1200 to +1200)", "cents", -1200, 1200, 0),
        ("Tempo (0.5x to 2.0x)", "tempo", 0.5, 2.0, 1.0),
    ],
    "chorus": [
        ("Delay (ms)", "delay", 20, 100, 50),
        ("Decay", "decay", 0.0, 1.0, 0.4),
        ("Speed (Hz)", "speed", 0.1, 5.0, 2.0),
        ("Depth (ms)", "depth", 0.0, 10.0, 2.0),
    ],
    "compressor": [
        ("Threshold", "threshold", 0.01, 1.0, 0.1),
        ("Ratio:1", "ratio", 1, 20, 4),
        ("Attack (ms)", "attack", 1, 200, 20),
        ("Release (ms)", "release", 20, 2000, 250),
        ("Makeup Gain", "makeup", 1, 10, 1),
    ],
    "distortion": [
        ("Bit Depth", "bits", 2, 16, 8),
        ("Mix", "mix", 0.0, 1.0, 0.6),
    ],
    "flanger": [
        ("Delay (ms)", "delay", 0, 30, 10),
        ("Depth (ms)", "depth", 0, 10, 2),
        ("Speed (Hz)", "speed", 0.1, 10.0, 0.5),
    ],
    "gargle": [
        ("Rate (Hz)", "rate", 1, 40, 20),
        ("Depth", "depth", 0.0, 1.0, 0.7),
    ],
}

BUILTIN_PRESETS: dict[str, dict[str, dict[str, Any]]] = {
    "echo": {
        "Short Slap": {"delay": 80, "decay": 0.3, "in_gain": 0.8, "out_gain": 0.88},
        "Medium Delay": {"delay": 300, "decay": 0.4, "in_gain": 0.8, "out_gain": 0.88},
        "Long Delay": {"delay": 600, "decay": 0.5, "in_gain": 0.8, "out_gain": 0.88},
        "Canyon Echo": {"delay": 900, "decay": 0.6, "in_gain": 0.8, "out_gain": 0.9},
    },
    "equalizer": {
        "Flat": {},
        "Rock": {"32": 0, "64": 2, "125": 3, "250": 4, "500": 5, "1k": 4, "2k": 3, "4k": 2, "8k": 1, "16k": 0},
        "Pop": {"32": -1, "64": 0, "125": 2, "250": 3, "500": 4, "1k": 3, "2k": 2, "4k": 1, "8k": 0, "16k": -1},
        "Jazz": {"32": 2, "64": 3, "125": 2, "250": 4, "500": 5, "1k": 3, "2k": 2, "4k": 1, "8k": 2, "16k": 3},
        "Classical": {"32": 2, "64": 3, "125": 2, "250": 1, "500": 0, "1k": 0, "2k": 1, "4k": 2, "8k": 3, "16k": 4},
        "Dance": {"32": 4, "64": 3, "125": 2, "250": 5, "500": 6, "1k": 4, "2k": 2, "4k": 1, "8k": 0, "16k": -1},
        "Bass Boost": {"32": 6, "64": 5, "125": 4, "250": 2, "500": 0, "1k": 0, "2k": 0, "4k": 0, "8k": 0, "16k": 0},
        "Vocal": {"32": -2, "64": -1, "125": 0, "250": 2, "500": 4, "1k": 5, "2k": 4, "4k": 3, "8k": 1, "16k": 0},
    },
    "reverb": {
        "Small Room": {"room_size": 0.2, "decay": 0.25, "mix": 0.2},
        "Large Room": {"room_size": 0.45, "decay": 0.4, "mix": 0.3},
        "Hall": {"room_size": 0.7, "decay": 0.55, "mix": 0.4},
        "Church": {"room_size": 0.85, "decay": 0.7, "mix": 0.45},
        "Stadium": {"room_size": 1.0, "decay": 0.85, "mix": 0.5},
    },
    "dynamic_range": {
        "Light Compression": {"threshold": -20, "ratio": 2, "knee": 5, "attack": 5, "release": 50},
        "Medium Compression": {"threshold": -30, "ratio": 4, "knee": 10, "attack": 3, "release": 30},
        "Heavy Compression": {"threshold": -40, "ratio": 8, "knee": 20, "attack": 1, "release": 20},
        "Limiter Only": {"threshold": -6, "ratio": 20, "knee": 0, "attack": 0.5, "release": 10},
    },
    "pitch_tempo": {
        "Semitone Down": {"cents": -100, "tempo": 1.0},
        "Semitone Up": {"cents": 100, "tempo": 1.0},
        "Chipmunk": {"cents": 400, "tempo": 1.0},
        "Deep Voice": {"cents": -300, "tempo": 1.0},
    },
    "chorus": {
        "Subtle": {"delay": 40, "decay": 0.3, "speed": 1.0, "depth": 1.5},
        "Classic Chorus": {"delay": 50, "decay": 0.4, "speed": 2.0, "depth": 2.5},
        "Deep Chorus": {"delay": 60, "decay": 0.5, "speed": 1.5, "depth": 4.0},
        "Ensemble": {"delay": 45, "decay": 0.45, "speed": 3.0, "depth": 3.0},
    },
    "compressor": {
        "Gentle": {"threshold": 0.3, "ratio": 2, "attack": 20, "release": 250, "makeup": 1},
        "Standard": {"threshold": 0.15, "ratio": 4, "attack": 20, "release": 200, "makeup": 1.5},
        "Aggressive": {"threshold": 0.08, "ratio": 8, "attack": 10, "release": 150, "makeup": 2},
        "Brick Wall Limiter": {"threshold": 0.03, "ratio": 20, "attack": 1, "release": 50, "makeup": 3},
    },
    "distortion": {
        "Light Grit": {"bits": 12, "mix": 0.3},
        "Overdrive": {"bits": 8, "mix": 0.5},
        "Heavy Crush": {"bits": 5, "mix": 0.7},
        "Lo-Fi Radio": {"bits": 4, "mix": 0.9},
    },
    "flanger": {
        "Subtle Sweep": {"delay": 5, "depth": 1, "speed": 0.3},
        "Classic Flange": {"delay": 10, "depth": 2, "speed": 0.5},
        "Jet Sweep": {"delay": 15, "depth": 4, "speed": 1.0},
        "Deep Flange": {"delay": 20, "depth": 6, "speed": 0.2},
    },
    "gargle": {
        "Slow Warble": {"rate": 8, "depth": 0.5},
        "Classic Gargle": {"rate": 20, "depth": 0.7},
        "Fast Robot": {"rate": 30, "depth": 0.8},
        "Extreme": {"rate": 38, "depth": 1.0},
    },
}
