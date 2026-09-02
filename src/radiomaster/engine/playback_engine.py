"""Playback engine: dispatches to one of two backends depending on content.

Audio-only content (radio, podcasts, audiobooks, local audio files,
YouTube audio) goes through LiveAudioEngine (engine/live_audio_engine.py),
a direct PyAV-decode + sounddevice/WASAPI-output pipeline that supports
genuinely live volume/pan/rate/effects changes -- no restart, matching the
README's "real-time... no restart required" promise.

Video goes through the original ffplay subprocess (unchanged) -- ffplay
still handles the actual video rendering, which this class was never
trying to replace; only its audio-control limitations motivated
LiveAudioEngine. Effect/rate/pan changes during video playback still
restart ffplay, same as before, since ffplay has no live filter-graph
reload API.
"""

import logging
import subprocess
import threading
import time
import os
from typing import Any, Callable

from radiomaster.utils.tools import get_ffplay
from radiomaster.utils.logging_setup import log_io
from radiomaster.engine.live_audio_engine import LiveAudioEngine, build_effects_filters

log = logging.getLogger("radiomaster")


class PlaybackEngine:
    """Manages audio/video playback (see module docstring for backends)."""

    STATE_STOPPED = "stopped"
    STATE_PLAYING = "playing"
    STATE_PAUSED = "paused"
    STATE_BUFFERING = "buffering"

    # Video-only: changing rate/pan/effects/output-device restarts ffplay
    # (it has no live filter-graph reload). A slider fires EVT_SLIDER on
    # every tick while being dragged, so restarting synchronously on each
    # call would relaunch ffplay dozens of times a second. Debounce so
    # only the last change in a burst actually triggers a restart.
    RESTART_DEBOUNCE_SECONDS = 0.4

    def __init__(self) -> None:
        # --- Video (ffplay subprocess) backend state ---
        self._process: subprocess.Popen | None = None
        self._ffplay_log_file = None
        self._ffplay_log_path: str = ""
        self._state = self.STATE_STOPPED
        self._duration: float = 0.0
        self._position: float = 0.0
        self._output_device: str = ""  # "" = system default; SDL device name for ffplay
        self._monitor_thread: threading.Thread | None = None
        self._monitor_running = False
        self._restart_timer: threading.Timer | None = None
        self._restart_lock = threading.Lock()
        self._reconnect_timer: threading.Timer | None = None
        self._volume_timer: threading.Timer | None = None
        self._volume_lock = threading.Lock()
        self._rate_timer: threading.Timer | None = None
        self._rate_lock = threading.Lock()
        self._crossfade_generation = 0

        # --- Shared state (both backends) ---
        self._current_url: str = ""
        self._current_title: str = ""
        self._current_artist: str = ""
        self._volume: float = 0.8
        self._rate: float = 1.0
        self._pan: float = 0.0
        self._replaygain_mode: str = "none"  # "none", "track", or "album"
        self._replaygain_db: float = 0.0
        self._auto_reconnect: bool = False
        self._reconnect_attempts: int = 0
        self._MAX_RECONNECT_ATTEMPTS = 5
        self._reconnect_interval: float = 2.0
        self._is_video: bool = False
        self._is_video_active: bool = False  # which backend owns the *current* session
        # HTTP headers (User-Agent above all) to replay on the ffplay
        # request for the current video -- see play()'s http_headers
        # param for why this matters.
        self._http_headers: dict[str, str] = {}

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

        # Callbacks
        self._on_state_change: Callable[[str], None] | None = None
        self._on_position_update: Callable[[float, float], None] | None = None
        self._on_track_change: Callable[[str, str], None] | None = None
        self._on_buffering: Callable[[int], None] | None = None
        self._on_error: Callable[[str], None] | None = None
        # Fired when ffplay's own request for the current video was
        # rejected (HTTP 403) shortly after launch -- see
        # _watch_for_stream_rejection. This engine only ever sees an
        # already-resolved stream URL, not the original video page URL,
        # so it can't re-resolve and retry itself the way
        # _watch_for_audio_device_failure does for a bad output device;
        # the caller (YouTubePanel, which does have the page URL) is
        # expected to re-resolve a fresh stream and call play() again.
        self._on_stream_rejected: Callable[[], None] | None = None
        self._on_track_finished: Callable[[], None] | None = None
        self._on_effects_changed: Callable[[str, dict[str, Any]], None] | None = None

        # --- Audio (LiveAudioEngine) backend ---
        self._live = LiveAudioEngine()
        self._wire_live_callbacks(self._live)

    def _wire_live_callbacks(self, live: LiveAudioEngine) -> None:
        """Hook a LiveAudioEngine instance's callbacks up to this engine's
        own listeners. Shared between __init__'s single long-lived instance
        and crossfade_to()'s temporary "incoming" instance."""
        live.on_state_change(lambda _s: self._notify_state())
        live.on_position_update(
            lambda p, d: self._on_position_update(p, d) if self._on_position_update else None
        )
        live.on_error(lambda m: self._notify_error(m))
        live.on_track_finished(lambda: self._on_track_finished() if self._on_track_finished else None)
        live.on_buffering(lambda p: self._on_buffering(p) if self._on_buffering else None)

    # ---------------------------------------------------------------------
    # Public accessors
    # ---------------------------------------------------------------------
    @property
    def state(self) -> str:
        """Current playback state (stopped, playing, paused, buffering)."""
        return self._state if self._is_video_active else self._live.state

    def play(self, url: str, title: str = "", artist: str = "",
              is_video: bool = False, duration: float = 0.0,
              http_headers: dict[str, str] | None = None) -> None:
        """Start playback of a URL or file.

        http_headers (video only): HTTP headers -- User-Agent above all --
        to replay on ffplay's own request for *url*. A googlevideo.com
        playback URL is bound to the request context it was resolved
        under; handing the bare URL to ffplay with ffplay's own default
        User-Agent got a flat 403 for some videos (confirmed live) while
        others played fine with no visible pattern. See youtube_dl.py's
        get_stream_info() for where these come from."""
        self.stop()
        self._current_url = url
        self._current_title = title
        self._current_artist = artist
        self._is_video = is_video
        self._is_video_active = is_video
        self._duration = duration
        self._http_headers = http_headers or {}
        self._reconnect_attempts = 0
        self._replaygain_db = self._compute_replaygain(url)

        if is_video:
            self._position = 0.0
            self._state = self.STATE_BUFFERING
            self._notify_state()
            self._start_process(url, is_video)
        else:
            self._live.set_auto_reconnect(self._auto_reconnect)
            self._live.set_replaygain_db(self._replaygain_db)
            self._live.set_volume(self._volume)
            self._live.set_pan(self._pan)
            self._live.set_rate(self._rate)
            self._live.play(url, title, artist, duration)

    def crossfade_to(self, url: str, title: str = "", artist: str = "",
                      duration: float = 0.0, fade_seconds: float = 5.0) -> None:
        """Switch to *url* with a real overlapping crossfade against
        whatever's currently playing, instead of a hard stop/start cut.

        Audio-only: video always hard-cuts (ffplay has no live mixing).
        Also hard-cuts if nothing is actually playing yet, or fade_seconds
        is 0 -- nothing to overlap against.

        Two independent LiveAudioEngine instances -- each with its own
        sounddevice.OutputStream -- play simultaneously for the fade
        window; WASAPI's shared mode mixes concurrent streams from the
        same process at the OS level, so no manual PCM mixing is needed
        here, just opposing volume ramps on each engine.
        """
        if self._is_video_active or fade_seconds <= 0 or self._live.state not in (
            LiveAudioEngine.STATE_PLAYING, LiveAudioEngine.STATE_BUFFERING
        ):
            self.play(url, title, artist, duration=duration)
            return

        self._crossfade_generation += 1
        generation = self._crossfade_generation

        outgoing = self._live
        outgoing_start_volume = outgoing.volume

        incoming = LiveAudioEngine()
        self._wire_live_callbacks(incoming)
        incoming.set_auto_reconnect(self._auto_reconnect)
        incoming.set_replaygain_db(self._compute_replaygain(url))
        incoming.set_volume(0.0)
        incoming.set_pan(self._pan)
        incoming.set_rate(self._rate)
        incoming.play(url, title, artist, duration)

        self._live = incoming
        self._current_url = url
        self._current_title = title
        self._current_artist = artist
        self._duration = duration
        self._reconnect_attempts = 0

        target_volume = self._volume
        threading.Thread(
            target=self._run_crossfade_ramp,
            args=(generation, outgoing, incoming, outgoing_start_volume, target_volume, fade_seconds),
            daemon=True,
        ).start()

    def _run_crossfade_ramp(self, generation: int, outgoing: LiveAudioEngine, incoming: LiveAudioEngine,
                             outgoing_start_volume: float, target_volume: float, fade_seconds: float) -> None:
        steps = max(1, int(fade_seconds * 20))  # ~20 volume updates/sec
        for i in range(1, steps + 1):
            if generation != self._crossfade_generation:
                # Superseded by a newer play()/crossfade_to() call -- stop
                # ramping (whatever superseded this owns the volume now)
                # but still tear down our own outgoing stream below, or
                # it would keep playing forever in the background.
                break
            t = i / steps
            incoming.set_volume(target_volume * t)
            outgoing.set_volume(outgoing_start_volume * (1 - t))
            time.sleep(fade_seconds / steps)
        outgoing.stop()

    def set_replaygain_mode(self, mode: str) -> None:
        """Set ReplayGain mode: "none", "track", or "album"."""
        self._replaygain_mode = mode if mode in ("track", "album") else "none"
        if self._current_url:
            self._replaygain_db = self._compute_replaygain(self._current_url)
            if self._is_video_active:
                if self._state in (self.STATE_PLAYING, self.STATE_PAUSED):
                    self._schedule_restart()
            else:
                self._live.set_replaygain_db(self._replaygain_db)

    def _compute_replaygain(self, url: str) -> float:
        """ReplayGain only makes sense for local files with tags -- radio
        streams and remote URLs have no metadata to read."""
        if self._replaygain_mode == "none" or not os.path.isfile(url):
            return 0.0
        from radiomaster.utils.replaygain import read_replaygain_db
        return read_replaygain_db(url, self._replaygain_mode)

    def stop(self, wait: bool = True) -> None:
        """Stop playback. Stops whichever backend might be active -- each
        call is a safe no-op on the backend that wasn't in use.

        *wait=False* (app shutdown only) skips blocking waits on both
        backends -- see LiveAudioEngine.stop()'s docstring for why a slow
        EVT_CLOSE handler mattered enough to break the installer's
        close-running-app detection."""
        self._crossfade_generation += 1  # let any in-flight ramp exit early
        self._live.stop(wait=wait)

        self._monitor_running = False
        with self._restart_lock:
            if self._restart_timer is not None:
                self._restart_timer.cancel()
                self._restart_timer = None
            if self._reconnect_timer is not None:
                # Without this, a dropped stream's pending auto-reconnect
                # attempt (scheduled by _monitor_loop, up to 2s in the
                # future) fires anyway after the user has already pressed
                # Stop, silently relaunching ffplay behind their back.
                self._reconnect_timer.cancel()
                self._reconnect_timer = None
        with self._volume_lock:
            if self._volume_timer is not None:
                self._volume_timer.cancel()
                self._volume_timer = None
        with self._rate_lock:
            if self._rate_timer is not None:
                self._rate_timer.cancel()
                self._rate_timer = None
        if self._process:
            try:
                self._process.terminate()
                if wait:
                    self._process.wait(timeout=3)
            except Exception:
                if self._process:
                    self._process.kill()
            self._process = None
            self._close_ffplay_log()
        self._state = self.STATE_STOPPED
        self._position = 0.0
        self._notify_state()

    def pause(self) -> None:
        """Pause playback."""
        if not self._is_video_active:
            self._live.pause()
            return
        if self._process and self._state == self.STATE_PLAYING:
            # FFplay: 'p' or Space toggles pause via stdin
            self._send_ffplay_key("p")
            self._state = self.STATE_PAUSED
            self._notify_state()

    def resume(self) -> None:
        """Resume from pause."""
        if not self._is_video_active:
            self._live.resume()
            return
        if self._process and self._state == self.STATE_PAUSED:
            self._send_ffplay_key("p")
            self._state = self.STATE_PLAYING
            self._notify_state()

    def _send_ffplay_key(self, key: str) -> None:
        """Send a key command to FFplay via stdin."""
        if self._process and self._process.stdin:
            try:
                self._process.stdin.write(key.encode())
                self._process.stdin.flush()
            except Exception:
                pass

    def seek(self, position_seconds: float) -> None:
        """Seek to a position in the current track."""
        if not self._is_video_active:
            self._live.seek(position_seconds)
            return
        # FFplay: 's' + seconds + '\n' seeks to absolute position
        self._send_ffplay_key(f"s{position_seconds}\n")

    # Volume changes are applied live (README promises no-restart dynamic
    # control). Rapid slider dragging fires this many times a second, so a
    # short debounce collapses each burst to one WASAPI call instead of one
    # per tick -- much shorter than RESTART_DEBOUNCE_SECONDS since setting
    # a session volume is cheap and doesn't touch the ffplay process at all.
    # (Video-only backstop: LiveAudioEngine applies volume as a direct
    # numpy gain, no debounce needed there at all.)
    VOLUME_DEBOUNCE_SECONDS = 0.08

    def set_volume(self, volume: float) -> None:
        """Set volume (0.0 to 1.0), applied live without restarting playback."""
        self._volume = max(0.0, min(1.0, volume))
        if not self._is_video_active:
            self._live.set_volume(self._volume)
            return
        if self._process is None:
            return
        with self._volume_lock:
            if self._volume_timer is not None:
                self._volume_timer.cancel()
            self._volume_timer = threading.Timer(
                self.VOLUME_DEBOUNCE_SECONDS, self._apply_volume_live
            )
            self._volume_timer.daemon = True
            self._volume_timer.start()

    def _apply_volume_live(self) -> None:
        """Set the running ffplay process's own WASAPI session volume --
        the same mechanism the Windows Volume Mixer uses per-app, and the
        only way to change a running ffplay's volume without restarting it
        (see utils/session_volume.py for why the old stdin-key approach
        never worked). Video path only -- LiveAudioEngine handles audio."""
        process = self._process
        if process is None:
            return
        from radiomaster.utils.session_volume import set_process_volume
        applied = set_process_volume(process.pid, self._volume)
        if not applied and self._state in (self.STATE_PLAYING, self.STATE_PAUSED):
            # WASAPI session not found (e.g. ffplay hasn't opened its
            # audio stream) or COM unavailable on this thread -- fall back
            # to a restart so the change still takes effect one way or
            # another rather than being silently dropped.
            self._schedule_restart()

    def _apply_volume_live_with_retry(self, process: subprocess.Popen,
                                       attempts: int = 30, delay: float = 0.25) -> None:
        """Retry applying self._volume to *process*'s WASAPI session for a
        few seconds after launch -- ffplay doesn't open its audio stream
        (and therefore doesn't have a session to find) the instant Popen()
        returns. Measured up to ~4.5s in practice for a real stream, so
        this retries for up to 7.5s before giving up."""
        from radiomaster.utils.session_volume import set_process_volume
        for _ in range(attempts):
            if self._process is not process:
                return  # superseded by a stop/restart/reconnect since we started
            if set_process_volume(process.pid, self._volume):
                return
            time.sleep(delay)

    # Unlike volume/pan (a pure numpy gain multiply, free to apply on every
    # tick), a rate change rebuilds LiveAudioEngine's filter graph AND
    # discards its ~4s buffered queue so the new rate is audible right
    # away (see LiveAudioEngine._drain_queue_for_immediate_effect) --
    # cheap once, but dragging the rate slider fires this many times a
    # second, and each call was flushing the buffer and forcing an
    # audible dropout while the decode thread caught back up over the
    # network. Debouncing collapses a drag to a single flush after the
    # user settles, matching the VOLUME_DEBOUNCE_SECONDS pattern above.
    RATE_DEBOUNCE_SECONDS = 0.25

    def set_rate(self, rate: float) -> None:
        """Set playback rate (0.5 to 3.0), applied live for audio."""
        self._rate = max(0.5, min(3.0, rate))
        if not self._is_video_active:
            with self._rate_lock:
                if self._rate_timer is not None:
                    self._rate_timer.cancel()
                self._rate_timer = threading.Timer(
                    self.RATE_DEBOUNCE_SECONDS, self._live.set_rate, args=(self._rate,)
                )
                self._rate_timer.daemon = True
                self._rate_timer.start()
            return
        if self._state in (self.STATE_PLAYING, self.STATE_PAUSED):
            self._schedule_restart()

    def set_pan(self, pan: float) -> None:
        """Set stereo pan (-1.0 to 1.0), applied live for audio."""
        self._pan = max(-1.0, min(1.0, pan))
        if not self._is_video_active:
            self._live.set_pan(self._pan)
            return
        if self._state in (self.STATE_PLAYING, self.STATE_PAUSED):
            self._schedule_restart()

    def set_auto_reconnect(self, enabled: bool) -> None:
        """Automatically retry a dropped live stream (radio) up to
        _MAX_RECONNECT_ATTEMPTS times. Never applies to finite-duration
        media (local files, on-demand URLs) reaching a normal end."""
        self._auto_reconnect = enabled
        self._live.set_auto_reconnect(enabled)

    def set_reconnect_settings(self, max_attempts: int, interval: float) -> None:
        """Configure the reconnect-attempt budget and delay between
        attempts for both backends (video/ffplay here, audio via
        LiveAudioEngine)."""
        self._MAX_RECONNECT_ATTEMPTS = max(1, max_attempts)
        self._reconnect_interval = max(0.5, interval)
        self._live.set_reconnect_settings(max_attempts, interval)

    def set_output_device(self, device_name: str) -> None:
        """Set the audio output device by name (see utils/audio_devices.py),
        or "" for the system default."""
        self._output_device = device_name
        if self._is_video_active:
            if self._state in (self.STATE_PLAYING, self.STATE_PAUSED):
                self._schedule_restart()
            return
        index = _resolve_sounddevice_index(device_name) if device_name else None
        self._live.set_output_device(index)

    def toggle_effect(self, effect_id: str, enabled: bool) -> None:
        """Enable or disable an effect."""
        if effect_id in self._effects:
            self._effects[effect_id]["enabled"] = enabled
            self._live.toggle_effect(effect_id, enabled)
            if self._is_video_active and self._state in (self.STATE_PLAYING, self.STATE_PAUSED):
                self._schedule_restart()
            self._notify_effects_changed(effect_id)

    def apply_preset(self, effect_id: str, preset_name: str, params: dict[str, Any]) -> None:
        """Apply a named preset (built-in or user-created -- the caller
        resolves the name to params; this just applies them) to an
        effect, auto-enabling it."""
        if effect_id in self._effects:
            self._effects[effect_id]["preset"] = preset_name
            self._effects[effect_id]["params"] = params
            self._effects[effect_id]["enabled"] = True
            self._live.apply_preset(effect_id, preset_name, params)
            if self._is_video_active and self._state in (self.STATE_PLAYING, self.STATE_PAUSED):
                self._schedule_restart()
            self._notify_effects_changed(effect_id)

    def get_effect_params(self, effect_id: str) -> dict[str, Any]:
        """Get current parameters for an effect."""
        return self._effects.get(effect_id, {}).get("params", {})

    def get_effect_preset(self, effect_id: str) -> str:
        """Get the name of the currently-selected preset for an effect."""
        return self._effects.get(effect_id, {}).get("preset", "")

    def apply_effect_params(self, effect_id: str, params: dict[str, Any]) -> None:
        """Apply raw effect parameters directly (e.g. from equalizer dialog)."""
        if effect_id in self._effects:
            self._effects[effect_id]["params"] = params
            self._effects[effect_id]["enabled"] = True
            self._live.apply_effect_params(effect_id, params)
            self._notify_effects_changed(effect_id)

    def restore_effects_state(self, saved: dict[str, dict[str, Any]]) -> None:
        """Restore enabled/preset/params for each effect from config at
        startup -- called before any playback starts and before the
        Effects menu is built, so both the filter graph (next play()) and
        the menu's initial checkmarks reflect last session's state.

        Deliberately not just an in-place dict update: apply_preset()/
        toggle_effect() also push the state into the LiveAudioEngine
        mirror (self._live._effects), which is what actually builds the
        ffmpeg filter chain.
        """
        for effect_id, state in saved.items():
            if effect_id not in self._effects:
                continue
            self.apply_preset(effect_id, state.get("preset", ""), dict(state.get("params", {})))
            self.toggle_effect(effect_id, state.get("enabled", False))
            if self._is_video_active and self._state in (self.STATE_PLAYING, self.STATE_PAUSED):
                self._schedule_restart()

    def _schedule_restart(self) -> None:
        """Debounce _restart_with_effects() -- see RESTART_DEBOUNCE_SECONDS.
        Video-only; audio changes apply live via LiveAudioEngine."""
        with self._restart_lock:
            if self._restart_timer is not None:
                self._restart_timer.cancel()
            self._restart_timer = threading.Timer(
                self.RESTART_DEBOUNCE_SECONDS, self._restart_with_effects
            )
            self._restart_timer.daemon = True
            self._restart_timer.start()

    def _start_process(self, url: str, is_video: bool, force_default_device: bool = False) -> None:
        """Start the FFplay subprocess (video only). *force_default_device*
        is a one-attempt override used only by _watch_for_audio_device_failure's
        retry -- it never touches the saved Settings > Playback > Output
        Device value itself, only what this particular launch asks SDL for."""
        cmd = self._build_ffplay_command(url, is_video)
        # ffplay has no CLI flag for choosing an output device -- it goes
        # through SDL2, which picks the device from this env var on the
        # child process. See utils/audio_devices.py for how the exact name
        # is derived (has to match SDL's own enumeration precisely) --
        # that fragility is exactly what _watch_for_audio_device_failure
        # exists to recover from.
        device_for_this_attempt = "" if force_default_device else self._output_device
        from radiomaster.utils.network import get_ffplay_http_proxy_env
        proxy_env = get_ffplay_http_proxy_env()
        env = None
        if device_for_this_attempt or proxy_env:
            env = dict(os.environ)
            if device_for_this_attempt:
                env["SDL_AUDIO_DEVICE_NAME"] = device_for_this_attempt
            env.update(proxy_env)
        try:
            log_io(log, "spawning ffplay: %s", cmd)
            # ffplay's own stderr (its only channel for real errors --
            # "Protocol not found", a connection that failed/reset, an
            # unsupported codec, etc.) used to go straight to DEVNULL,
            # so a video that opened a window but silently played
            # nothing left genuinely no trace of why anywhere -- not in
            # the app, not in a log, nothing to go on if it couldn't be
            # reproduced live. Captured to a plain file instead
            # (overwritten each launch -- only the most recent attempt
            # matters for this).
            from radiomaster.utils.paths import get_paths
            log_dir = get_paths()["logs"]
            os.makedirs(log_dir, exist_ok=True)
            self._ffplay_log_path = os.path.join(log_dir, "ffplay_last_run.log")
            self._ffplay_log_file = open(self._ffplay_log_path, "wb")
            self._process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=self._ffplay_log_file,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                env=env,
            )
            self._state = self.STATE_PLAYING
            self._notify_state()
            self._start_monitor()
            # A fresh process is a fresh WASAPI audio session at 100%
            # (session volume doesn't carry over from the previous
            # process/PID) -- (re)apply the saved level. ffplay may not
            # have opened its audio stream yet, so this retries briefly in
            # the background instead of failing outright.
            threading.Thread(
                target=self._apply_volume_live_with_retry, args=(self._process,), daemon=True
            ).start()
            # Only need to watch for a bad SDL device name when we actually
            # asked for one -- the fallback attempt itself (force_default_device)
            # never spawns a watcher of its own, which is what keeps this
            # from being able to retry forever.
            if device_for_this_attempt:
                threading.Thread(
                    target=self._watch_for_audio_device_failure,
                    args=(self._process, self._ffplay_log_path, url, is_video),
                    daemon=True,
                ).start()
            if is_video:
                threading.Thread(
                    target=self._watch_for_stream_rejection,
                    args=(self._process, self._ffplay_log_path),
                    daemon=True,
                ).start()
        except FileNotFoundError:
            self._notify_error("FFplay not found. Ensure ffplay.exe is in the tools/ folder.")
        except Exception as e:
            self._notify_error(f"Failed to start playback: {e}")

    def _watch_for_audio_device_failure(
        self, process: "subprocess.Popen[bytes]", log_path: str, url: str, is_video: bool
    ) -> None:
        """Confirmed live from a real user log: the saved Settings > Playback
        > Output Device name has to match SDL's own device enumeration
        *exactly* (see utils/audio_devices.py's docstring on how fragile
        that matching is), and once it's stale -- device renamed,
        disconnected, or just reordered by Windows -- SDL_OpenAudio fails
        with "No such device" and ffplay carries on decoding and "playing"
        video completely silently forever, with no error surfaced anywhere.
        That's indistinguishable from "nothing is playing" to anyone
        relying on the audio. This polls the just-started process's own
        stderr log for that failure signature for a few seconds after
        launch (SDL_OpenAudio fails, or doesn't, right at open -- not
        later), and if seen, restarts this same playback once with the
        system default device instead of the stale saved one, without
        touching the saved setting itself."""
        deadline = time.time() + 5
        text = ""
        found = False
        while time.time() < deadline:
            if self._process is not process:
                return  # superseded by a stop/new play since this attempt started
            try:
                with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                    text = f.read()
            except OSError:
                pass
            if "No more combinations to try, audio open failed" in text:
                found = True
                break
            time.sleep(0.5)
        if not found or self._process is not process:
            return
        log.warning("Configured audio output device not found by SDL; falling back to system default")
        self._notify_error(
            "The configured audio output device could not be found. "
            "Falling back to the system default for this session -- "
            "check Settings > Playback > Output Device."
        )
        # Stop the monitor loop first, same as _restart_with_effects -- otherwise
        # it can observe this deliberate terminate() as a natural process exit
        # and race this restart with its own reconnect/stopped-state handling.
        self._monitor_running = False
        try:
            process.terminate()
            process.wait(timeout=2)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
        if self._process is process:
            self._process = None
            self._close_ffplay_log()
            self._start_process(url, is_video, force_default_device=True)

    def _watch_for_stream_rejection(self, process: "subprocess.Popen[bytes]", log_path: str) -> None:
        """A googlevideo.com playback URL is bound to the request context
        it was resolved under (User-Agent above all -- see play()'s
        http_headers docstring); even with that replayed correctly, a
        freshly-resolved URL can still come back "HTTP error 403
        Forbidden" moments later for reasons outside this app's control
        (YouTube-side throttling/anti-bot checks on the resolving
        client/IP) -- confirmed live as an intermittent, not-per-video
        failure: the exact same URL that 403'd could succeed on a later,
        independent re-resolve. ffplay carries on decoding nothing after
        a 403 and never exits on its own (-autoexit only fires at a real
        EOF, and a rejected connection never gets one), so without this
        the video window just sits there indefinitely showing nothing --
        indistinguishable from "doesn't play" to anyone watching it.

        This polls the log for the failure signature for a few seconds
        after launch and, if seen, stops this attempt and tells the
        caller (on_stream_rejected) to re-resolve and retry -- this
        engine only has the already-resolved (and now known-bad) stream
        URL, not the original page URL a retry needs."""
        deadline = time.time() + 4
        text = ""
        found = False
        while time.time() < deadline:
            if self._process is not process:
                return  # superseded by a stop/new play since this attempt started
            try:
                with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                    text = f.read()
            except OSError:
                pass
            if "403 Forbidden" in text:
                found = True
                break
            time.sleep(0.5)
        if not found or self._process is not process:
            return
        log.warning("YouTube rejected the resolved stream URL (403); asking caller to retry")
        self._monitor_running = False
        try:
            process.terminate()
            process.wait(timeout=2)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
        if self._process is process:
            self._process = None
            self._close_ffplay_log()
            self._state = self.STATE_STOPPED
            self._notify_state()
        if self._on_stream_rejected:
            self._on_stream_rejected()

    def _close_ffplay_log(self) -> None:
        if self._ffplay_log_file is not None:
            try:
                self._ffplay_log_file.close()
            except Exception:
                pass
            self._ffplay_log_file = None

    def _build_ffplay_command(self, url: str, is_video: bool) -> list[str]:
        """Build the FFplay command line with current settings (video only)."""
        cmd = [get_ffplay(), "-nodisp", "-autoexit", "-exitonmousedown"]

        # Volume is intentionally NOT set here via -volume: it's applied
        # live afterwards through the process's own WASAPI session (see
        # _apply_volume_live / utils/session_volume.py), so every fresh
        # process launches at ffplay's own 100% default and self._volume
        # is the sole, unambiguous source of truth for the actual level --
        # stacking a -volume flag on top of a WASAPI session scale would
        # double-apply the same change.

        filters = []

        # ReplayGain -- a per-file volume trim read from tags, applied
        # ahead of the (already-clamped) main volume so quiet/loud tracks
        # play back at a consistent perceived level.
        if self._replaygain_db:
            filters.append(f"volume={self._replaygain_db}dB")

        # Pan (rate + effects are built by the same shared helper the
        # audio backend uses, so the two backends apply identical DSP for
        # identical settings).
        if self._pan != 0.0:
            pan_val = max(-1.0, min(1.0, self._pan))
            left_gain = 1.0 - max(0, pan_val)
            right_gain = 1.0 - max(0, -pan_val)
            filters.append(f"pan=stereo|c0={left_gain}*c0|c1={right_gain}*c1")

        filters.extend(build_effects_filters(self._rate, self._effects))

        if filters:
            cmd.extend(["-af", ",".join(filters)])

        # Video window
        if is_video:
            cmd.remove("-nodisp")

        # HTTP(S) reconnect -- confirmed live: a long googlevideo.com stream
        # (YouTube) can have its TLS connection reset mid-download (Windows
        # error -10054) well before the video actually ends; without these,
        # ffplay has no instruction to retry and just dies with corrupted
        # h264 packets ("Invalid NAL unit size", "partial file") instead of
        # picking the download back up. These are demuxer-level input
        # options, so they must come immediately before the URL.
        if url.startswith(("http://", "https://")):
            from radiomaster.utils.network import get_ffmpeg_input_args
            network_args = get_ffmpeg_input_args()
            # A resolved YouTube stream carries a User-Agent selected by
            # yt-dlp. Preserve that below instead of adding two competing
            # -user_agent options here.
            if is_video and self._http_headers and self._http_headers.get("User-Agent"):
                network_args = network_args[:2]
            cmd.extend(network_args)
            cmd.extend([
                "-reconnect", "1",
                "-reconnect_at_eof", "1",
                "-reconnect_streamed", "1",
                "-reconnect_delay_max", "5",
            ])

        # Replays yt-dlp's own HTTP headers (User-Agent above all) on
        # ffplay's request -- a googlevideo.com URL is bound to the
        # request context it was resolved under, and ffplay's own
        # default User-Agent got a flat 403 on some videos with no
        # visible pattern until this was added (see play()'s
        # http_headers docstring). Both are demuxer/input options like
        # -reconnect above, so they also have to come before the URL.
        #
        # User-Agent specifically goes through ffmpeg's own dedicated
        # -user_agent option, NOT as a "User-Agent: ..." line inside
        # -headers -- confirmed live that -headers alone left the 403
        # completely unfixed (ffmpeg's HTTP protocol handler doesn't
        # treat a User-Agent line inside -headers as authoritative the
        # way -user_agent is), while -user_agent alone reliably fixed
        # the exact same URL every time.
        if is_video and self._http_headers:
            headers = dict(self._http_headers)
            user_agent = headers.pop("User-Agent", None)
            if user_agent:
                cmd.extend(["-user_agent", user_agent])
            if headers:
                header_lines = "".join(f"{k}: {v}\r\n" for k, v in headers.items())
                cmd.extend(["-headers", header_lines])

        cmd.append(url)
        return cmd

    def _restart_with_effects(self) -> None:
        """Restart playback with current effect settings (video only)."""
        if not self._current_url:
            return
        pos = self._position
        old_state = self._state
        # Stop the old process first to avoid leaking subprocesses
        self._monitor_running = False
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=2)
            except Exception:
                if self._process:
                    self._process.kill()
            self._process = None
            self._close_ffplay_log()
        self._start_process(self._current_url, self._is_video)
        # Only seek if the restart succeeded (state changed to playing)
        if pos > 0 and self._state == self.STATE_PLAYING:
            threading.Timer(0.5, lambda: self.seek(pos)).start()
        elif self._state != self.STATE_PLAYING:
            # Restore old state on failure
            self._state = old_state

    def _start_monitor(self) -> None:
        """Start a monitoring thread for playback position (video only)."""
        self._monitor_running = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def _monitor_loop(self) -> None:
        """Monitor playback and update position (video only)."""
        start_time = time.time()
        while self._monitor_running and self._process:
            if self._state == self.STATE_PLAYING:
                self._position = time.time() - start_time
                if self._on_position_update:
                    self._on_position_update(self._position, self._duration)

                # A live stream that's stayed connected for a while is
                # healthy again -- forgive earlier reconnect attempts so a
                # brief blip long ago doesn't count against a fresh drop.
                if self._position > 10.0:
                    self._reconnect_attempts = 0

                # Check if process is still running
                if self._process.poll() is not None:
                    self._monitor_running = False
                    # This used to auto-reconnect (relaunch a fresh ffplay)
                    # for any duration == 0 (live/unbounded) video the same
                    # way radio does -- but unlike radio (LiveAudioEngine,
                    # no window, no user-facing way to stop it except this
                    # engine's own stop()), a video plays in a real ffplay
                    # window the user can close directly: a click anywhere
                    # (-exitonmousedown, below), the window's own X button,
                    # or Alt+F4 -- none of which go through stop(), so
                    # _monitor_running was never told to give up. For a
                    # live video that genuinely just ended or errored,
                    # reconnecting made sense; for the far more common case
                    # of the user closing the window themselves, it meant a
                    # second ffplay window silently reopened right after --
                    # confirmed live as "some videos don't play" (the
                    # reopened window playing a since-ended/errored stream)
                    # and "have to press Alt+F4 twice, two windows show
                    # up". ffplay's own -reconnect/-reconnect_at_eof/
                    # -reconnect_streamed flags (see _build_ffplay_command)
                    # already recover a genuine transient network drop
                    # *without* the process ever exiting, so by the time
                    # this process has actually terminated there's no
                    # reliable way left to tell "the stream really died"
                    # apart from "the user just closed it" -- so this no
                    # longer guesses. Radio's own auto-reconnect (Settings
                    # > Radio > Auto-reconnect, LiveAudioEngine) is a
                    # completely separate code path and is unaffected.
                    self._state = self.STATE_STOPPED
                    self._notify_state()
                    break
            time.sleep(0.25)

    def _notify_state(self) -> None:
        """Notify listeners of state change (always the *effective*
        current state -- whichever backend is active)."""
        if self._on_state_change:
            self._on_state_change(self.state)

    def _notify_error(self, message: str) -> None:
        """Notify listeners of an error."""
        if self._on_error:
            self._on_error(message)

    # Callback setters
    def on_state_change(self, cb: Callable[[str], None] | None) -> None:
        self._on_state_change = cb

    def on_position_update(self, cb: Callable[[float, float], None]) -> None:
        self._on_position_update = cb

    def on_track_change(self, cb: Callable[[str, str], None]) -> None:
        self._on_track_change = cb

    def on_buffering(self, cb: Callable[[int], None]) -> None:
        self._on_buffering = cb

    def on_error(self, cb: Callable[[str], None]) -> None:
        self._on_error = cb

    def on_stream_rejected(self, cb: Callable[[], None]) -> None:
        self._on_stream_rejected = cb

    def on_track_finished(self, cb: Callable[[], None]) -> None:
        """Fired only when the current track reaches its own natural end
        (not a user Stop, not a crossfade takeover) -- audio-only, since
        video's ffplay backend has no equivalent natural-end signal."""
        self._on_track_finished = cb

    def on_effects_changed(self, cb: Callable[[str, dict[str, Any]], None]) -> None:
        """Fired whenever an effect's enabled/preset/params state changes
        (toggle, preset selection, or manual param edit e.g. the equalizer
        dialog), so callers can persist it across restarts."""
        self._on_effects_changed = cb

    def _notify_effects_changed(self, effect_id: str) -> None:
        if self._on_effects_changed:
            state = self._effects.get(effect_id, {})
            self._on_effects_changed(effect_id, {
                "enabled": state.get("enabled", False),
                "preset": state.get("preset", ""),
                "params": dict(state.get("params", {})),
            })

    @property
    def position(self) -> float:
        return self._position if self._is_video_active else self._live.position

    @property
    def duration(self) -> float:
        return self._duration if self._is_video_active else self._live.duration

    @property
    def volume(self) -> float:
        return self._volume

    @property
    def current_url(self) -> str:
        return self._current_url

    @property
    def current_title(self) -> str:
        return self._current_title

    @property
    def current_artist(self) -> str:
        return self._current_artist

    @property
    def is_video(self) -> bool:
        return self._is_video

    @property
    def rate(self) -> float:
        return self._rate

    @property
    def pan(self) -> float:
        return self._pan

    # ------------------------------------------------------------------
    # Track navigation helpers (used by MainWindow callbacks)
    # ------------------------------------------------------------------
    def fast_forward(self, seconds: float = 10.0) -> None:
        """Fast-forward by *seconds* (default 10)."""
        new_pos = self.position + seconds
        if self.duration > 0 and new_pos > self.duration:
            new_pos = self.duration
        self.seek(new_pos)

    def rewind(self, seconds: float = 10.0) -> None:
        """Rewind by *seconds* (default 10)."""
        new_pos = self.position - seconds
        if new_pos < 0:
            new_pos = 0
        self.seek(new_pos)


def _resolve_sounddevice_index(device_name: str) -> int | None:
    """Best-effort match of a saved SDL-scheme device name (see
    utils/audio_devices.py) against sounddevice/PortAudio's own device
    list, which enumerates and names devices differently. Returns None
    (system default) if nothing matches closely enough."""
    try:
        import sounddevice as sd
        devices = sd.query_devices()
    except Exception:
        return None
    # Strip the "N- " disambiguation prefix and match on the core name.
    core = device_name.split("- ", 1)[-1].strip().lower()
    best_index = None
    for i, d in enumerate(devices):
        if d.get("max_output_channels", 0) <= 0:
            continue
        name = str(d.get("name", "")).lower()
        if core and core in name:
            return i
        if best_index is None and device_name.strip().lower() in name:
            best_index = i
    return best_index
