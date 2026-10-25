"""Crossfade: the real BASS host mixing two streams, and the engine routing."""

import ctypes
import math
import os
import struct
import time
import wave
from unittest.mock import MagicMock

import pytest

from radiomaster.engine.bass_host import BassHost, _BASS_ATTRIB_VOL
from radiomaster.utils.tools import get_tools_dir


def _tone(path, hz, seconds=3.0, rate=44100):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(
            struct.pack("<h", int(12000 * math.sin(2 * math.pi * hz * i / rate)))
            for i in range(int(rate * seconds))))


@pytest.fixture(scope="module")
def _loaded_host(tmp_path_factory):
    # BASS_Init is process-global, so the DLL is loaded once for the module.
    h = BassHost(get_tools_dir(), device_index=0)   # device 0 = BASS "no sound"
    ok, reason = h.load()
    if not ok:
        pytest.skip(f"BASS not available: {reason}")
    folder = tmp_path_factory.mktemp("tones")
    files = []
    for name, hz in (("a.wav", 440), ("b.wav", 880), ("c.wav", 660)):
        path = str(folder / name)
        _tone(path, hz)
        files.append(path)
    yield h, files
    h.stop()


@pytest.fixture
def host(_loaded_host):
    h, files = _loaded_host
    h.stop()
    yield h, files
    h.stop()


def _vol(h, handle):
    value = ctypes.c_float(-1)
    ok = h._dll.BASS_ChannelGetAttribute(handle, _BASS_ATTRIB_VOL, ctypes.byref(value))
    return value.value if ok else None


def test_host_overlaps_streams_then_frees_the_old_one(host):
    h, (a, b, _c) = host
    assert h.play(a, 1.0, seq=1, seekable=True)[0]
    time.sleep(0.3)
    old = h._handle
    assert h.crossfade(b, 1.0, seq=2, seekable=True, fade_seconds=1.0) == (True, "ok")
    new = h._handle
    assert new != old
    time.sleep(0.5)
    mid_old, mid_new = _vol(h, old), _vol(h, new)
    assert 0.1 < mid_old < 0.9 and 0.1 < mid_new < 0.9      # both audible: a real overlap
    assert h._dll.BASS_ChannelIsActive(old) == 1 and h._dll.BASS_ChannelIsActive(new) == 1
    time.sleep(1.4)
    assert h._dll.BASS_ChannelIsActive(old) == 0              # outgoing stream freed
    assert _vol(h, new) == pytest.approx(1.0, abs=0.02)       # incoming at full volume
    assert h._dll.BASS_ChannelIsActive(new) == 1


def test_host_crossfade_with_amplification_and_back_to_back(host):
    h, (a, b, c) = host
    assert h.play(a, 1.5, seq=1, seekable=True)[0]          # >1.0 installs the gain DSP
    time.sleep(0.2)
    assert h.crossfade(b, 1.5, seq=2, seekable=True, fade_seconds=0.5)[0]
    time.sleep(0.2)
    assert h.crossfade(c, 1.5, seq=3, seekable=True, fade_seconds=0.5)[0]
    time.sleep(1.0)
    assert h._dll.BASS_ChannelIsActive(h._handle) == 1


def test_host_crossfade_without_a_playing_stream_just_plays(host):
    h, (a, _b, _c) = host
    assert h.crossfade(a, 1.0, seq=1, seekable=True, fade_seconds=1.0)[0]
    assert h._dll.BASS_ChannelIsActive(h._handle) == 1


def test_host_crossfade_to_missing_file_fails_cleanly(host):
    h, (a, _b, _c) = host
    h.play(a, 1.0, seq=1, seekable=True)
    ok, reason = h.crossfade(a + ".missing", 1.0, seq=2, seekable=True, fade_seconds=1.0)
    assert not ok and h._handle == 0


def test_engine_overlaps_local_files_only(tmp_path):
    from radiomaster.engine.playback_engine import PlaybackEngine
    engine = PlaybackEngine.__new__(PlaybackEngine)
    engine._bass_radio = bass = MagicMock()
    engine._using_bass_radio = True
    engine._is_video_active = False
    engine._state = PlaybackEngine.STATE_PLAYING
    engine._effects = {"normalization": {"enabled": False, "params": {}}}
    engine._volume, engine._pan, engine._rate = 1.0, 0.0, 1.0
    engine._replaygain_mode = "none"
    engine._play_lock = __import__("threading").RLock()
    engine._playback_generation = 0
    engine._loudness_cache, engine._loudness_pending = {}, set()
    engine.play = MagicMock()
    local = tmp_path / "next.mp3"
    local.write_bytes(b"x")
    engine.crossfade_to(str(local), "T", "A", duration=10, fade_seconds=3)
    bass.crossfade.assert_called_once()
    engine.play.assert_not_called()
    engine.crossfade_to("http://example.com/s", "T", fade_seconds=3)
    engine.play.assert_called_once()
