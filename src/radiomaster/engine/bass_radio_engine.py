"""Crash-isolated BASS backend for live RadioMaster+ streams.

The adapted GPL host runs as a separate process so a native decoder failure
cannot take down the wxPython interface.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

from radiomaster.utils.tools import get_tools_dir

log = logging.getLogger("radiomaster")

BASS_ACTIVE_PLAYING = 1
BASS_ACTIVE_STALLED = 2
BASS_ACTIVE_PAUSED = 3


def _host_launch() -> tuple[list[str], dict[str, str]] | None:
    tools_root = Path(get_tools_dir())
    bass = tools_root / "bass" / "x64" / "bass.dll"
    if not bass.is_file():
        return None
    command = ([sys.executable, "--bass-host"] if getattr(sys, "frozen", False)
               else [sys.executable, "-m", "radiomaster", "--bass-host"])
    environment = os.environ.copy()
    environment["RADIOMASTER_BASS_ROOT"] = str(tools_root)
    return command, environment


class BassRadioEngine:
    """PlaybackEngine-compatible adapter for RadioMaster's BASS subprocess."""

    STATE_STOPPED = "stopped"
    STATE_PLAYING = "playing"
    STATE_PAUSED = "paused"
    STATE_BUFFERING = "buffering"

    @classmethod
    def create_if_available(cls) -> "BassRadioEngine | None":
        launch = _host_launch()
        if not launch:
            return None
        try:
            return cls(*launch)
        except Exception:
            log.warning("Could not start external BASS host", exc_info=True)
            return None

    def __init__(self, command: list[str], environment: dict[str, str]) -> None:
        self._state = self.STATE_STOPPED
        self._volume = 0.8
        self._pan = 0.0
        self._rate = 1.0
        self._position = 0.0
        self._duration = 0.0
        self._seekable = False
        self._effects: dict = {}
        self._generation = 0
        self._lock = threading.RLock()
        self._io_lock = threading.RLock()
        self._on_state_change: Callable[[str], None] | None = None
        self._on_position_update: Callable[[float, float], None] | None = None
        self._on_buffering: Callable[[int], None] | None = None
        self._on_error: Callable[[str], None] | None = None
        self._on_track_change: Callable[[str, str], None] | None = None
        self._on_track_finished: Callable[[], None] | None = None
        self._process = subprocess.Popen(
            command, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=environment,
        )
        ready = self._read_response()
        if not ready.get("ok") or not ready.get("ready"):
            self._terminate_host()
            raise RuntimeError(ready.get("error", "BASS host did not become ready"))
        log.info("BASS radio backend enabled through isolated RadioMaster host")

    @property
    def state(self) -> str:
        return self._state

    @property
    def position(self) -> float:
        return self._position

    @property
    def duration(self) -> float:
        return self._duration

    def _read_response(self) -> dict:
        assert self._process.stdout is not None
        while True:
            line = self._process.stdout.readline()
            if not line:
                detail = self._process.stderr.read().strip() if self._process.stderr else ""
                raise RuntimeError(detail or "BASS host exited unexpectedly")
            response = json.loads(line)
            if not response.get("event"):
                return response
            event_type = response.get("type")
            if event_type == "meta" and self._on_track_change:
                self._on_track_change(str(response.get("title", "")), "")
            elif event_type == "stall":
                self._state = self.STATE_BUFFERING
                self._notify_state()
                if self._on_buffering:
                    self._on_buffering(0)

    def _request(self, command: dict) -> dict:
        with self._io_lock:
            if self._process.poll() is not None:
                raise RuntimeError("BASS host is no longer running")
            assert self._process.stdin is not None
            self._process.stdin.write(json.dumps(command) + "\n")
            self._process.stdin.flush()
            return self._read_response()

    def play(self, url: str, title: str = "", artist: str = "",
             duration: float = 0.0, seekable: bool | None = None) -> None:
        self.stop()
        with self._lock:
            self._generation += 1
            generation = self._generation
            self._state = self.STATE_BUFFERING
            self._position = 0.0
            self._duration = max(0.0, duration)
            self._seekable = (seekable if seekable is not None else
                              (self._duration > 0.0 or not url.startswith(("http://", "https://"))))
        self._notify_state()
        threading.Thread(target=self._play_and_monitor,
                         args=(url, title, artist, generation), daemon=True,
                         name="bass-radio-monitor").start()

    def _play_and_monitor(self, url: str, title: str, artist: str,
                          generation: int) -> None:
        completed = False
        try:
            result = self._request({"cmd": "play", "url": url,
                                    "volume": self._volume, "seq": generation,
                                    "seekable": self._seekable})
            if not result.get("ok"):
                raise RuntimeError(result.get("error", "stream open failed"))
            last = time.monotonic()
            while generation == self._generation:
                active = self._request({"cmd": "status"}).get("state", -1)
                now = time.monotonic()
                if active == BASS_ACTIVE_PLAYING:
                    self._position += now - last
                    state = self.STATE_PLAYING
                elif active == BASS_ACTIVE_STALLED:
                    state = self.STATE_BUFFERING
                elif active == BASS_ACTIVE_PAUSED:
                    state = self.STATE_PAUSED
                else:
                    completed = True
                    break
                last = now
                if self._seekable:
                    media = self._request({"cmd": "media_status"})
                    self._position = max(0.0, float(media.get("position_seconds", 0.0)))
                    reported_duration = max(0.0, float(media.get("length_seconds", 0.0)))
                    if reported_duration:
                        self._duration = reported_duration
                if state != self._state:
                    self._state = state
                    self._notify_state()
                if self._on_buffering:
                    self._on_buffering(0 if active == BASS_ACTIVE_STALLED else 100)
                if self._on_position_update:
                    self._on_position_update(self._position, self._duration)
                time.sleep(0.25)
        except Exception as exc:
            if generation == self._generation:
                self._notify_error(f"BASS could not play '{title}': {exc}")
        finally:
            if generation == self._generation:
                self._state = self.STATE_STOPPED
                self._notify_state()
                if completed and self._seekable and self._on_track_finished:
                    self._on_track_finished()

    def stop(self, wait: bool = True) -> None:
        del wait
        with self._lock:
            self._generation += 1
            changed = self._state != self.STATE_STOPPED
            self._state = self.STATE_STOPPED
            self._position = 0.0
            self._duration = 0.0
        try:
            self._request({"cmd": "stop"})
        except Exception:
            log.debug("Could not stop BASS host playback", exc_info=True)
        if changed:
            self._notify_state()

    def pause(self) -> None:
        if self._request({"cmd": "pause"}).get("ok"):
            self._state = self.STATE_PAUSED
            self._notify_state()

    def resume(self) -> None:
        if self._request({"cmd": "resume"}).get("ok"):
            self._state = self.STATE_PLAYING
            self._notify_state()

    def set_volume(self, value: float) -> None:
        self._volume = max(0.0, min(2.0, value))
        self._request({"cmd": "volume", "value": self._volume})

    def set_pan(self, value: float) -> None:
        self._pan = max(-1.0, min(1.0, value))
        self._request({"cmd": "pan", "value": self._pan})

    def seek(self, position_seconds: float) -> None:
        result = self._request({"cmd": "media_seek",
                                "position_seconds": max(0.0, position_seconds)})
        if result.get("seeked"):
            self._position = float(result.get("position_seconds", position_seconds))
            self._duration = float(result.get("length_seconds", self._duration))

    def set_rate(self, rate: float) -> None:
        self._rate = max(0.5, min(3.0, rate))
        pitch_tempo = self._effects.get("pitch_tempo", {})
        effect_tempo = (float(pitch_tempo.get("params", {}).get("tempo", 1.0))
                        if pitch_tempo.get("enabled") else 1.0)
        self._request({"cmd": "set_playback_rate",
                       "rate": max(0.5, min(3.0, self._rate * effect_tempo))})

    def apply_effects(self, effects: dict) -> None:
        """Map RadioMaster's effects model onto BASS's native FX set."""
        self._effects = effects
        pitch_tempo = effects.get("pitch_tempo", {})
        cents = (float(pitch_tempo.get("params", {}).get("cents", 0.0))
                 if pitch_tempo.get("enabled") else 0.0)
        self._request({"cmd": "set_pitch", "semitones": cents / 100.0})
        self.set_rate(self._rate)
        direct = {"echo", "reverb", "chorus", "compressor", "distortion",
                  "flanger", "gargle"}
        active = {name for name in direct
                  if effects.get(name, {}).get("enabled")}
        if effects.get("dynamic_range", {}).get("enabled"):
            active.add("compressor")
        eq = effects.get("equalizer", {})
        if eq.get("enabled"):
            params = eq.get("params", {})
            groups = {
                "eq_bass": ("32", "64", "125"),
                "eq_vocal": ("250", "500", "1k", "2k"),
                "eq_treble": ("4k", "8k", "16k"),
            }
            for band, keys in groups.items():
                gain = sum(float(params.get(key, 0.0)) for key in keys) / len(keys)
                active.add(band)
                self._request({"cmd": "set_eq_gain", "band": band,
                               "gain_db": gain})
        self._request({"cmd": "set_fx", "fx": sorted(active),
                       "params": {name: dict(effects.get(name, {}).get("params", {}))
                                  for name in active}})

    def set_output_device(self, device_name: str) -> bool:
        devices = self._request({"cmd": "list_devices"}).get("devices", [])
        if not device_name:
            return True
        wanted = device_name.casefold()
        for index, name in devices:
            candidate = str(name).casefold()
            if candidate == wanted or wanted in candidate or candidate in wanted:
                return bool(self._request({"cmd": "set_device", "index": index}).get("changed"))
        return False

    def close(self) -> None:
        try:
            self._request({"cmd": "quit"})
        except Exception:
            pass
        self._terminate_host()

    def _terminate_host(self) -> None:
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.kill()

    def _notify_state(self) -> None:
        if self._on_state_change:
            self._on_state_change(self._state)

    def _notify_error(self, message: str) -> None:
        log.error(message)
        if self._on_error:
            self._on_error(message)

    def on_state_change(self, callback) -> None:
        self._on_state_change = callback

    def on_position_update(self, callback) -> None:
        self._on_position_update = callback

    def on_buffering(self, callback) -> None:
        self._on_buffering = callback

    def on_error(self, callback) -> None:
        self._on_error = callback

    def on_track_change(self, callback) -> None:
        self._on_track_change = callback

    def on_track_finished(self, callback) -> None:
        self._on_track_finished = callback
