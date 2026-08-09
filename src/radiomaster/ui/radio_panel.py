"""Radio tab panel with station browser, search, playback controls, and custom stations."""

from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
import time
from datetime import datetime
from typing import Any, Callable, Optional

import wx
import wx.lib.scrolledpanel as scrolled

from radiomaster.services.station_api import Station, StationAPI, StationAPIError
from radiomaster.services.station_db import StationDB
from radiomaster.services.station_updater import StationUpdater
from radiomaster.engine.playback_engine import PlaybackEngine
from radiomaster.ui.widgets.station_tree import StationTree
from radiomaster.ui.widgets.now_playing import NowPlayingPanel
from radiomaster.utils.paths import get_paths
from radiomaster.utils.tools import get_ffmpeg

log = logging.getLogger("radiomaster")


def _parse_icy_song(song: str) -> tuple[str, str]:
    """Split an ICY StreamTitle value into (artist, title).

    "Artist - Title" is the overwhelming convention stations use (it's
    literally what most broadcast software defaults to), but it's not a
    guaranteed format -- if there's no " - " separator, treat the whole
    string as the title with an empty artist rather than guessing wrong.
    """
    if " - " in song:
        artist, _, title = song.partition(" - ")
        return artist.strip(), title.strip()
    return "", song.strip()


class RadioPanel(scrolled.ScrolledPanel):
    """Radio browsing and playback panel."""

    def __init__(self, parent, station_api: StationAPI, station_db: StationDB,
                 station_updater: StationUpdater, engine: PlaybackEngine,
                 set_status: Callable[[str], None], db=None):
        super().__init__(parent)
        self.station_api = station_api
        self.station_db = station_db
        self.station_updater = station_updater
        self.engine = engine
        self.set_status = set_status
        self._db = db
        self._selected_station: Optional[Station] = None
        self._search_seq = 0
        self._now_playing_generation = 0

        # Manual (Record button / hotkey) recordings -- separate from the
        # timed SchedulerService recordings, this just ffmpeg-copies
        # whatever's currently selected to a file until toggled off again.
        # Keyed by the "downloads" table row id (source_type=
        # "radio_recording", see _on_record) so multiple different
        # stations can each be recording at once, independently -- keying
        # by a single value used to mean starting a second recording
        # silently had no way to track the first one at all.
        self._recordings: dict[int, dict[str, Any]] = {}
        # The transport bar's Record button (NowPlayingBar, owned by
        # MainWindow -- a different class from this panel's own
        # NowPlayingPanel) lives outside this panel, so starting/stopping
        # a recording notifies MainWindow through this callback to flip
        # its label/accessible name ("Record Off" <-> "Recording On") to
        # reflect whether the *currently selected* station specifically
        # is being recorded. Without it, ffmpeg genuinely recorded in the
        # background but the button never changed state -- indistinguishable
        # from "does nothing" for a screen reader user with no other feedback.
        self.on_recording_changed: Optional[Callable[[bool], None]] = None

        # Station play history (browser-style back/forward, not a queue):
        # picking a fresh station truncates anything ahead of the current
        # position and appends it; History navigation just moves the
        # index and replays whatever's already there.
        self._history: list[Station] = []
        self._history_index: int = -1
        # Called after every history change (fresh station played, or
        # Previous/Next/First/Last moved the index) so MainWindow can
        # re-enable/grey out the transport bar's history buttons.
        self.on_history_changed: Optional[Callable[[], None]] = None
        # Called whenever ICY metadata gives us the actual song now playing
        # (artist, title) -- as opposed to just the station name, which is
        # all engine._current_title ever had before. MainWindow uses this
        # to fetch lyrics for the real song; without it, lyrics lookups
        # only ever saw the station's name as "title" and an empty artist,
        # which no lyrics provider can match against anything.
        self.on_now_playing_changed: Optional[Callable[[str, str], None]] = None

        # Search row
        search_label = wx.StaticText(self, label="&Search:")
        self.search_ctrl = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.search_ctrl.SetHint("Search by name, genre, country, or language")
        self.search_btn = wx.Button(self, label="&Search")

        # Station tree
        self.tree = StationTree(self, station_db)
        self.tree.SetMinSize((-1, 320))

        # Now playing
        self.now_playing = NowPlayingPanel(self)

        # Action buttons
        self.add_custom_btn = wx.Button(self, label="&Add Custom Station")

        search_row = wx.BoxSizer(wx.HORIZONTAL)
        search_row.Add(search_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        search_row.Add(self.search_ctrl, 1, wx.EXPAND | wx.RIGHT, 4)
        search_row.Add(self.search_btn, 0)

        action_row = wx.BoxSizer(wx.HORIZONTAL)
        action_row.Add(self.add_custom_btn, 0, wx.RIGHT, 6)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(search_row, 0, wx.EXPAND | wx.ALL, 6)
        outer.Add(self.tree, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        outer.Add(action_row, 0, wx.EXPAND | wx.ALL, 6)
        outer.Add(self.now_playing, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        self.SetSizer(outer)
        self.SetupScrolling(scroll_x=False, scroll_y=True)

        # Bind events
        self.search_btn.Bind(wx.EVT_BUTTON, self._on_search)
        self.search_ctrl.Bind(wx.EVT_TEXT_ENTER, self._on_search)
        self.add_custom_btn.Bind(wx.EVT_BUTTON, self._on_add_custom)
        self.tree.on_station_activated = self._on_station_activated
        self.tree.on_selection_changed = self._on_tree_sel_changed

        # Volume/rate/pan restoration happens once, centrally, in
        # MainWindow.__init__ (after this panel and the engine both
        # exist) -- not here, to avoid two places independently reading
        # "the saved volume" at slightly different times.

        self.tree.add_custom_section(self.station_db.get_custom_stations())

        self._load_stations()

    def _load_stations(self) -> None:
        """Populate the tree from the local SQLite DB. If empty, fetch first."""
        if self.station_db.station_count() > 0:
            self._apply_sections()
            return

        self.set_status("Status: Fetching station list for the first time...")

        def progress_cb(bytes_read: int, total) -> None:
            if total:
                percent = min(100, int(bytes_read * 100 / total))
                text = f"Status: Fetching station list for the first time... {percent}%"
            else:
                text = f"Status: Fetching station list for the first time... ({bytes_read // 1024} KB)"
            wx.CallAfter(self.set_status, text)

        def worker():
            result = self.station_updater.update_now(progress_cb=progress_cb)
            if not result.ok:
                wx.CallAfter(self.set_status, f"Status: Could not load stations ({result.error})")
                return
            wx.CallAfter(self._apply_sections)

        threading.Thread(target=worker, daemon=True).start()

    def refresh_after_station_update(self) -> None:
        """Called after a scheduled (or manual "Update Now" in Settings >
        Radio) station DB update completes, so the tree reflects the
        newly-synced catalog."""
        self._apply_sections()

    def _apply_sections(self) -> None:
        from radiomaster.utils.config import ConfigManager
        config = ConfigManager.get_instance()

        self.tree.set_show_duplicates(config.get("radio.show_duplicates", default=False))
        self.tree.load_sections()

        default_country = config.get("radio.default_country", default="all")
        if default_country and default_country != "all":
            self.tree.show_country(default_country)

        self.set_status("Status: Ready")

    def _on_search(self, event: wx.CommandEvent) -> None:
        query = self.search_ctrl.GetValue().strip()
        if not query:
            return
        self.set_status("Status: Searching...")
        self._search_seq += 1
        seq = self._search_seq

        def worker():
            results = self.station_db.search_local(query)
            if not results:
                try:
                    results = self.station_api.search(query)
                except StationAPIError:
                    pass
            if seq != self._search_seq:
                return
            wx.CallAfter(self.tree.set_search_results, results)
            wx.CallAfter(self.set_status, f"Status: {len(results)} result(s) for '{query}'")

        threading.Thread(target=worker, daemon=True).start()

    def _on_tree_sel_changed(self) -> None:
        try:
            self._selected_station = self.tree.get_selected_station()
        except RuntimeError:
            return
        # With multiple stations potentially recording at once, the
        # Record button reflects whichever station is now selected --
        # without this, selecting a station that's already recording
        # (started while a different one was selected) still showed
        # "Record Off", the opposite of what's actually happening.
        if self.on_recording_changed:
            self.on_recording_changed(self.is_station_recording(self._selected_station))

    def _on_station_activated(self, station: Station) -> None:
        self._selected_station = station
        self._play_station(station)

    def play_last_station_if_enabled(self) -> None:
        """Auto-play whatever station was playing at the end of the last
        session, if the user opted in via Settings > Radio."""
        from radiomaster.utils.config import ConfigManager
        config = ConfigManager.get_instance()
        if not config.get("radio.auto_play_last_station", default=False):
            return
        last = config.get("radio.last_station", default={})
        if not last or not last.get("url"):
            return
        station = Station.from_dict(last)
        self._selected_station = station
        self._play_station(station)

    def _play_station(self, station: Station, add_to_history: bool = True) -> None:
        if add_to_history:
            self._push_history(station)
        self.now_playing.set_station(station.name)
        self.now_playing.set_now_playing("")
        self.set_status(f"Status: Connecting to {station.name}...")
        # engine.play() stops the previous process (up to a 3s wait) and
        # spawns ffplay via subprocess.Popen — both can stall for several
        # seconds (e.g. on first-run AV scanning of the exe), which would
        # freeze the UI if run on this event-handler thread.
        from radiomaster.utils.config import ConfigManager
        config = ConfigManager.get_instance()
        config.set("radio.last_station", value=station.to_dict())
        config.save()
        fade_seconds = config.get("playback.crossfade_duration", default=0)
        if fade_seconds:
            threading.Thread(target=self.engine.crossfade_to, args=(station.url,),
                              kwargs={"title": station.name, "fade_seconds": fade_seconds},
                              daemon=True).start()
        else:
            threading.Thread(target=self.engine.play, args=(station.url,),
                              kwargs={"title": station.name}, daemon=True).start()
        threading.Thread(target=self.station_api.click, args=(station.uuid,), daemon=True).start()

        # Poll ICY/SHOUTcast metadata in the background so "Now Playing"
        # shows the current song instead of staying blank for the whole
        # session. The generation counter lets a stale poll from a station
        # we've since switched away from (or stopped) notice and exit
        # instead of overwriting the field with old data.
        self._now_playing_generation += 1
        generation = self._now_playing_generation
        threading.Thread(target=self._poll_now_playing, args=(station.url, generation), daemon=True).start()

    # Give up on a station's ICY metadata after this many *consecutive*
    # failed connection attempts (a real drop/refusal, not a timed poll --
    # see _iter_icy_songs) -- distinguishes "this station genuinely
    # doesn't support/allow it" from a transient hiccup worth retrying.
    _MAX_ICY_CONSECUTIVE_FAILURES = 5

    def _iter_icy_songs(self, url: str, should_continue: Callable[[], bool]):
        """Yields each new ICY StreamTitle seen on *url*, reusing ONE
        connection for as long as it stays alive and only reconnecting
        (with backoff) after a real failure -- a dropped connection, or
        the station momentarily refusing a second slot alongside ffmpeg's
        own recording connection. Used by both _poll_now_playing and
        _record_track_watcher.

        This used to just die silently and stop watching entirely the
        first time anything went wrong with the metadata connection --
        indistinguishable from "nothing changed", so a recording with
        Split Tracks on could quietly stop splitting for the rest of the
        session (or never even start) with no error and no way to tell.
        Reconnecting here means one hiccup on this secondary connection
        doesn't end metadata watching for the whole session, while the
        failure cap below still avoids hammering a station that plain
        doesn't support this at all.
        """
        from radiomaster.engine.stream_reader import StreamReader
        consecutive_failures = 0
        while should_continue():
            response, meta_interval = StreamReader.open_icy_stream(url, timeout=15)
            if response is None or meta_interval <= 0:
                if response is not None:
                    try:
                        response.close()
                    except Exception:
                        pass
                consecutive_failures += 1
                if consecutive_failures >= self._MAX_ICY_CONSECUTIVE_FAILURES:
                    log.warning(f"Giving up on ICY metadata for {url} after "
                                f"{consecutive_failures} failed attempts")
                    return
                time.sleep(min(30, 2 ** consecutive_failures))
                continue
            consecutive_failures = 0
            try:
                while should_continue():
                    try:
                        song = StreamReader.read_next_icy_song(response, meta_interval)
                    except Exception:
                        break  # connection dropped mid-stream -- fall through to reconnect
                    if not should_continue():
                        return
                    if song:
                        yield song
            finally:
                try:
                    response.close()
                except Exception:
                    pass
            if should_continue():
                time.sleep(2)  # brief pause before reconnecting after a live drop

    def _poll_now_playing(self, url: str, generation: int) -> None:
        """Watches ICY/SHOUTcast in-band metadata for song changes over a
        persistent connection for the whole time this station is
        selected (see _iter_icy_songs) -- this used to open a brand new
        connection to the station every 8 seconds, forever, completely
        separate from the actual playback connection. That reconnect
        churn (a second full TCP/TLS handshake competing for bandwidth
        with the real stream, repeated indefinitely, sometimes a THIRD
        connection too if recording the same station -- see
        _record_track_watcher) is exactly what made continuous listening
        sound like the stream "kept breaking": some Icecast/SHOUTcast
        servers cap concurrent connections per listener or total
        listener slots and would throttle or drop the real playback
        connection under that pressure. One connection, read
        continuously, has no such churn and also detects song changes
        as fast as the station announces them rather than only every 8s.
        """
        last_song = None
        for song in self._iter_icy_songs(url, lambda: generation == self._now_playing_generation):
            if song != last_song:
                last_song = song
                wx.CallAfter(self.now_playing.set_now_playing, song)
                artist, title = _parse_icy_song(song)
                if title and self.on_now_playing_changed:
                    wx.CallAfter(self.on_now_playing_changed, artist, title)

    # ------------------------------------------------------------------
    # Station history (Previous/Next/First/Last on the transport bar)
    # ------------------------------------------------------------------
    def _push_history(self, station: Station) -> None:
        """Record a freshly-picked station, browser-style: anything ahead
        of the current position (from earlier Previous navigation) is
        discarded, then the station is appended and becomes current."""
        if self._history and self._history[self._history_index].uuid == station.uuid:
            return  # re-activating the station already playing -- no-op
        del self._history[self._history_index + 1:]
        self._history.append(station)
        self._history_index = len(self._history) - 1
        self._notify_history_changed()

    def _notify_history_changed(self) -> None:
        if self.on_history_changed:
            self.on_history_changed()

    def history_has_previous(self) -> bool:
        return self._history_index > 0

    def history_has_next(self) -> bool:
        return 0 <= self._history_index < len(self._history) - 1

    def _goto_history_index(self, index: int) -> None:
        if not (0 <= index < len(self._history)):
            return
        self._history_index = index
        station = self._history[index]
        self._selected_station = station
        self._play_station(station, add_to_history=False)
        self._notify_history_changed()

    def history_previous(self) -> None:
        if self.history_has_previous():
            self._goto_history_index(self._history_index - 1)

    def history_next(self) -> None:
        if self.history_has_next():
            self._goto_history_index(self._history_index + 1)

    def history_first(self) -> None:
        if self._history:
            self._goto_history_index(0)

    def history_last(self) -> None:
        if self._history:
            self._goto_history_index(len(self._history) - 1)

    def _on_play_pause(self) -> None:
        # Always try to get the currently selected station from the tree
        station = self._selected_station or self.tree.get_selected_station()
        if self.engine.state in ("stopped", "error") and station:
            self._selected_station = station
            self._play_station(station)
        elif self.engine.state == "paused":
            self.engine.resume()
        elif self.engine.state in ("playing", "buffering"):
            self.engine.pause()

    def _on_stop(self) -> None:
        # Invalidate any in-flight Now Playing metadata poll so it stops
        # itself instead of overwriting the (now blank) field later.
        self._now_playing_generation += 1
        # engine.stop() terminates the ffplay process and can block for up
        # to 3s waiting on it to exit; keep that off the UI thread.
        threading.Thread(target=self.engine.stop, daemon=True).start()
        self.now_playing.set_station("")
        self.now_playing.set_now_playing("")
        # Deliberately does NOT touch an active recording -- Stop only
        # stops playback. A recording is a separate ffmpeg connection to
        # the stream and is only ever stopped by toggling Record off
        # again (_on_record), by design.

    def _station_key(self, station: Optional[Station]) -> Optional[str]:
        """Identity for matching a Station to an entry in self._recordings
        -- uuid for a catalog station, url as a fallback for a custom
        station (no uuid)."""
        if station is None:
            return None
        return station.uuid or station.url

    def is_station_recording(self, station: Optional[Station]) -> bool:
        key = self._station_key(station)
        if key is None:
            return False
        return any(e["station_key"] == key for e in self._recordings.values())

    # Maps Settings > Recordings > "Recording Format" to an output
    # extension and the ffmpeg audio codec that produces it. FLAC/WAV are
    # lossless so "Recording Quality" (a bitrate) doesn't apply to them.
    _RECORDING_CODECS: dict[str, tuple[str, str]] = {
        "mp3": (".mp3", "libmp3lame"),
        "aac": (".aac", "aac"),
        "ogg": (".ogg", "libvorbis"),
        "flac": (".flac", "flac"),
        "wav": (".wav", "pcm_s16le"),
    }

    def _recording_ffmpeg_args(self, station: Station, output_path: str,
                                song: Optional[str] = None) -> list[str]:
        """Build the ffmpeg command for one recording segment, honoring
        Settings > Recordings (format/quality/metadata). *song* is the
        ICY "Artist - Title" string for the track this segment actually
        contains, when known -- tagged instead of just the station name."""
        from radiomaster.utils.config import ConfigManager
        config = ConfigManager.get_instance()
        rec_format = config.get("recordings.recording_format", default="mp3")
        _, codec = self._RECORDING_CODECS.get(rec_format, (".mp3", "libmp3lame"))
        quality = config.get("recordings.recording_quality", default="320k")

        cmd = [get_ffmpeg(), "-y", "-i", station.url, "-c:a", codec]
        if rec_format in ("mp3", "aac", "ogg"):
            cmd += ["-b:a", "320k" if quality.lower() == "best" else quality]
        if config.get("recordings.add_metadata", default=True):
            artist, title = _parse_icy_song(song) if song else ("", "")
            cmd += ["-metadata", f"title={title or station.name}",
                    "-metadata", f"artist={artist or station.name}"]
        cmd.append(output_path)
        return cmd

    def _start_ffmpeg_segment(self, station: Station, output_path: str,
                               song: Optional[str]) -> subprocess.Popen:
        """Starts one recording segment. stdin is a pipe (not DEVNULL) so
        it can be told to quit gracefully -- see _stop_ffmpeg_gracefully;
        a hard TerminateProcess() (what a plain .terminate() on Windows
        actually does) can leave the container's header/index unwritten,
        producing a file that won't seek or, for some formats, won't play
        back at all. This runs once per track when splitting is on, so an
        unfinalized file is no longer a rare "recording got interrupted"
        edge case -- it would be nearly every segment."""
        cmd = self._recording_ffmpeg_args(station, output_path, song=song)
        return subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )

    @staticmethod
    def _stop_ffmpeg_gracefully(process: subprocess.Popen, timeout: float = 5.0) -> None:
        """ffmpeg's documented graceful-quit is 'q' on stdin -- it then
        finalizes and closes the output file itself instead of being cut
        off mid-write. Falls back to a hard kill only if that doesn't
        work (process already gone, pipe broken, or it hangs)."""
        try:
            if process.stdin:
                process.stdin.write(b"q")
                process.stdin.flush()
                process.stdin.close()
            process.wait(timeout=timeout)
        except Exception:
            try:
                process.terminate()
                process.wait(timeout=3)
            except Exception:
                process.kill()

    @staticmethod
    def _unique_path(path: str) -> str:
        """Appends " (2)", " (3)", ... if *path* already exists -- the
        same song can legitimately play twice in one recording session."""
        if not os.path.exists(path):
            return path
        base, ext = os.path.splitext(path)
        n = 2
        while os.path.exists(f"{base} ({n}){ext}"):
            n += 1
        return f"{base} ({n}){ext}"

    def _finalize_segment_path(self, station_dir: str, ext: str,
                                song: Optional[str], station_name: str) -> str:
        """The just-finished segment's real filename: "Artist - Title" from
        ICY metadata when known, falling back to a timestamp (matching the
        pre-splitting naming) when the station never sent usable metadata
        for that segment at all."""
        if song:
            artist, title = _parse_icy_song(song)
            base_name = f"{artist} - {title}" if artist and title else (title or station_name)
        else:
            base_name = f"{station_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        safe = re.sub(r'[<>:"/\\|?*]', "_", base_name).strip() or "track"
        return self._unique_path(os.path.join(station_dir, f"{safe}{ext}"))

    def _finalize_current_segment(self, key_id: int, entry: dict[str, Any]) -> None:
        """Stops entry's current ffmpeg process and renames the temp file
        it was writing to its real "Artist - Title" (or timestamp) name.
        Caller holds entry['lock']. Only used for the non-split, single-
        continuous-file recording path -- see _finalize_encode_segment
        for the split-track path's equivalent."""
        self._stop_ffmpeg_gracefully(entry["process"])
        temp_path = entry["temp_path"]
        if os.path.exists(temp_path):
            final_path = self._finalize_segment_path(
                entry["station_dir"], entry["ext"], entry.get("last_song"), entry["station_name"],
            )
            try:
                os.replace(temp_path, final_path)
            except OSError as e:
                log.error(f"Could not finalize recording segment {temp_path}: {e}")
                return
            if self._db:
                # _stop_recording already marked this row "completed"
                # synchronously (so the Downloads tab reflects Stop
                # immediately) -- but that happens before the file is
                # actually renamed here, so file_path couldn't be known
                # yet. Backfilling it now is what makes a plain (non-
                # split) recording playable from Download History at all.
                from radiomaster.database.repository import DownloadRepository
                DownloadRepository(self._db).set_file_path(key_id, final_path)

    # ------------------------------------------------------------------
    # Split-track recording: ONE ffmpeg process stays connected to the
    # station for the whole session, decoding to raw PCM; each track gets
    # its own local (no network) ffmpeg process encoding that PCM to a
    # file. Splitting a track is then purely local -- close one encode
    # process's stdin (clean EOF, proper container finalization) and
    # start the next -- instead of the previous design, which killed the
    # in-progress network connection and opened a brand new one for
    # *every single split*. On a station that only allows one connection
    # per listener, that race (old connection's graceful shutdown vs. the
    # new one trying to connect) could fail outright and silently leave
    # the recording producing no further audio, with no error shown --
    # exactly "recording is not splitting on tracks". Matches the
    # reference implementation's approach (see D:\Projects\RadioMaster,
    # core/recorder.py and core/icy.py).
    # ------------------------------------------------------------------
    _DECODE_SAMPLE_RATE = 44100
    _DECODE_CHANNELS = 2

    # See _on_icy_title_changed's docstring for why acting on a title
    # change isn't instant.
    _SPLIT_SETTLE_SECONDS = 2.0

    def _start_decode_process(self, station: Station) -> subprocess.Popen:
        """The one network connection for a split-track recording's
        entire session. -reconnect lets ffmpeg itself recover from a
        transient drop without RadioMaster+ needing to notice and
        restart anything (the per-segment encode processes never touch
        the network at all, so a reconnect here doesn't disturb them)."""
        cmd = [
            get_ffmpeg(), "-hide_banner", "-loglevel", "error",
            "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5",
            "-i", station.url,
            "-vn", "-f", "s16le", "-acodec", "pcm_s16le",
            "-ac", str(self._DECODE_CHANNELS), "-ar", str(self._DECODE_SAMPLE_RATE),
            "pipe:1",
        ]
        return subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )

    def _start_encode_segment(self, output_path: str) -> subprocess.Popen:
        """One track's local encode process: raw PCM in via stdin (fed by
        _feed_decode_to_encode), the real configured format/quality out.
        Closing stdin (see _finalize_encode_segment) is a clean EOF that
        makes ffmpeg finish encoding and exit on its own -- there's no
        "q"-on-stdin graceful-quit here the way the non-split path uses,
        since stdin on this process IS the raw audio, not a command
        channel."""
        from radiomaster.utils.config import ConfigManager
        config = ConfigManager.get_instance()
        rec_format = config.get("recordings.recording_format", default="mp3")
        _, codec = self._RECORDING_CODECS.get(rec_format, (".mp3", "libmp3lame"))
        quality = config.get("recordings.recording_quality", default="320k")
        cmd = [
            get_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
            "-f", "s16le", "-ar", str(self._DECODE_SAMPLE_RATE), "-ac", str(self._DECODE_CHANNELS),
            "-i", "pipe:0", "-c:a", codec,
        ]
        if rec_format in ("mp3", "aac", "ogg"):
            cmd += ["-b:a", "320k" if quality.lower() == "best" else quality]
        cmd.append(output_path)
        return subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )

    def _feed_decode_to_encode(self, key_id: int) -> None:
        """Pumps raw PCM from the session's one decode process into
        whichever encode process is current -- entry['lock'] guards
        against a split (which replaces entry['encode_proc']) landing a
        write on the just-finalized process's already-closed stdin."""
        entry = self._recordings.get(key_id)
        if entry is None:
            return
        decode_proc = entry["decode_proc"]
        try:
            while True:
                chunk = decode_proc.stdout.read(8192)
                if not chunk:
                    return  # decode process ended -- station dropped, or Stop killed it
                entry = self._recordings.get(key_id)
                if entry is None:
                    return
                with entry["lock"]:
                    encode_proc = entry.get("encode_proc")
                    if encode_proc is None or encode_proc.stdin is None:
                        continue
                    try:
                        encode_proc.stdin.write(chunk)
                    except (BrokenPipeError, OSError):
                        pass
        except Exception as e:
            log.error(f"Recording feed loop for {entry.get('station_name', key_id)} ended: {e}")

    def _finalize_encode_segment(self, entry: dict[str, Any]) -> None:
        """Split-track path's equivalent of _finalize_current_segment:
        closes the current segment's encode process's stdin (ending its
        PCM input cleanly) and renames the resulting file. Caller holds
        entry['lock']."""
        encode_proc = entry.get("encode_proc")
        if encode_proc is not None:
            try:
                if encode_proc.stdin:
                    encode_proc.stdin.close()
                encode_proc.wait(timeout=10)
            except Exception:
                try:
                    encode_proc.terminate()
                    encode_proc.wait(timeout=3)
                except Exception:
                    encode_proc.kill()
        temp_path = entry["temp_path"]
        if os.path.exists(temp_path):
            final_path = self._finalize_segment_path(
                entry["station_dir"], entry["ext"], entry.get("last_song"), entry["station_name"],
            )
            try:
                os.replace(temp_path, final_path)
            except OSError as e:
                log.error(f"Could not finalize recording segment {temp_path}: {e}")
                return
            if self._db:
                # A split-off track is a finished file the moment it's
                # renamed here -- fires once per track *during* the still-
                # running recording session, not just when the whole
                # session eventually stops, so each one shows up in
                # Download History right away instead of only a single
                # generic "Recording: <station>" row at the end.
                from radiomaster.database.repository import DownloadRepository
                DownloadRepository(self._db).add_completed(
                    url=entry["station"].url,
                    title=os.path.splitext(os.path.basename(final_path))[0],
                    source_type="radio_recording",
                    file_path=final_path,
                )

    def _split_recording_segment(self, key_id: int, entry: dict[str, Any]) -> None:
        """A track change settled (see _on_icy_title_changed): finalize
        the segment that just ended under its own name and start the
        next one -- purely local, since the encode process has no
        network connection of its own to disturb."""
        with entry["lock"]:
            if self._recordings.get(key_id) is not entry:
                return  # stopped between the settle timer firing and the lock
            self._finalize_encode_segment(entry)
            if self._recordings.get(key_id) is not entry:
                return  # stopped while finalizing
            try:
                entry["encode_proc"] = self._start_encode_segment(entry["temp_path"])
            except Exception as e:
                log.error(f"Could not start next recording segment: {e}")

    def _on_icy_title_changed(self, key_id: int, title: str) -> None:
        """FFmpeg's own decode buffering means a title change is seen on
        the ICY metadata connection a bit BEFORE the matching audio
        actually reaches the encode side -- splitting immediately on the
        change cuts the boundary too early, gluing the tail of the
        outgoing track (sometimes part of the ad break right after it)
        onto the start of the next file. Settling for a short delay
        before acting lets decode catch up first, so the split lands
        much closer to the real boundary and tracks end up named (and
        cut) correctly instead of a beat early. A newer title arriving
        before the timer fires cancels and restarts it, so only the
        settled, real, final title for that change is ever acted on.

        The real, live-reproduced bug this fixes: this used to compare
        the incoming title against entry["last_song"] to decide whether
        to (re)start the settle timer -- but last_song only updates once
        a split actually APPLIES, several seconds after a change is
        first seen. Many stations resend the current StreamTitle on
        EVERY metadata block, not just when it changes. So while a title
        change was still settling, every repeat of that same still-
        pending title looked like yet another brand new change relative
        to the stale last_song, endlessly cancelling and restarting the
        timer -- it could take a very long time to ever actually fire
        (only once the station happened to go quiet for a full settle
        window), which is exactly "recording is not splitting on
        tracks": confirmed live with a simulated station that resent its
        title every ~1.5s, where only the very last song of a 3-song
        test session ever actually got split off. Comparing against
        pending_title instead -- what's already scheduled/settling --
        means a repeat of that exact title changes nothing, while an
        actually different title still cancels and restarts the timer
        as intended.
        """
        entry = self._recordings.get(key_id)
        if entry is None:
            return
        if title == entry.get("pending_title"):
            return
        entry["pending_title"] = title
        old_timer = entry.get("split_timer")
        if old_timer is not None:
            old_timer.cancel()
        timer = threading.Timer(self._SPLIT_SETTLE_SECONDS, self._apply_settled_split, args=(key_id, title))
        timer.daemon = True
        entry["split_timer"] = timer
        timer.start()

    def _apply_settled_split(self, key_id: int, title: str) -> None:
        entry = self._recordings.get(key_id)
        if entry is None or title != entry.get("pending_title"):
            return  # stopped, or superseded by a newer title while settling
        if entry.get("last_song") is None:
            # First title seen for this session -- the segment that's
            # already recording just learns its own name; there's no
            # prior segment to close yet.
            entry["last_song"] = title
            return
        self._split_recording_segment(key_id, entry)
        entry["last_song"] = title

    def _record_track_watcher(self, key_id: int) -> None:
        """Watches ICY metadata for an active split-track recording (see
        _iter_icy_songs) and feeds every detected title change through
        the settle-delay in _on_icy_title_changed -- independent of
        playback/Now Playing polling, since the station being recorded
        doesn't have to be the one currently playing.

        This is a SECOND connection to the station running alongside the
        session's one decode connection -- some stations only allow it
        intermittently (a shared connection-slot limit, a momentary
        refusal), which used to permanently kill split-track detection
        for the rest of the recording the first time it happened, with
        no error and no visible sign anything had gone wrong. _iter_icy_
        songs reconnects after a failure instead of giving up outright,
        so a single hiccup on this secondary connection doesn't end
        splitting for the whole session."""
        entry = self._recordings.get(key_id)
        if entry is None:
            return
        url = entry["station"].url

        def _still_recording() -> bool:
            return key_id in self._recordings

        for song in self._iter_icy_songs(url, _still_recording):
            self._on_icy_title_changed(key_id, song)

    def _on_record(self) -> None:
        """Toggle recording of the selected station's stream to a file.

        Multiple different stations can each be recording at once --
        pressing Record again for a station that ISN'T already recording
        starts a new, independent recording alongside any others; only
        pressing Record while the *selected* station's own recording is
        active stops that one specifically (matching the Recording
        Scheduler's existing "multiple simultaneous recordings" promise
        in the README, which the old single-recording-at-a-time
        implementation didn't honor for manual recordings).

        When Settings > Recordings > "Split recordings into tracks" is on,
        each track becomes its own file (named "Artist - Title" from ICY
        metadata) inside a per-station subfolder, instead of one
        continuous file for the whole session.
        """
        station = self._selected_station or self.tree.get_selected_station()
        if not station:
            wx.MessageBox("Select a station first.", "No Station Selected",
                          wx.OK | wx.ICON_INFORMATION)
            return

        key = self._station_key(station)
        existing_id = next(
            (did for did, e in self._recordings.items() if e["station_key"] == key), None
        )
        if existing_id is not None:
            self._stop_recording(existing_id)
            return

        from radiomaster.utils.config import ConfigManager
        from radiomaster.utils.paths import get_recordings_dir
        config = ConfigManager.get_instance()
        recordings_dir = get_recordings_dir()
        rec_format = config.get("recordings.recording_format", default="mp3")
        ext, _ = self._RECORDING_CODECS.get(rec_format, (".mp3", "libmp3lame"))
        split_tracks = config.get("recordings.split_tracks", default=False)

        safe_station_name = re.sub(r'[<>:"/\\|?*]', "_", station.name).strip() or "station"
        station_dir = os.path.join(recordings_dir, safe_station_name)
        os.makedirs(station_dir, exist_ok=True)
        # Recorded to a fixed temp name and renamed once its real name is
        # known (on the next track change, or on Stop) -- there's only
        # ever one temp file per station since a station can't have two
        # recordings running at once (the existing_id check above).
        temp_path = os.path.join(station_dir, f".recording_in_progress{ext}")

        entry: dict[str, Any] = {
            "station_name": station.name, "station_key": key, "station": station,
            "station_dir": station_dir, "ext": ext, "temp_path": temp_path,
            "last_song": None, "pending_title": None, "split_timer": None,
            "lock": threading.Lock(), "split_tracks": split_tracks,
        }

        decode_proc: Optional[subprocess.Popen] = None
        try:
            if split_tracks:
                # One continuous network connection for the whole session
                # (see _start_decode_process) plus one local, no-network
                # encode process for the first track -- splitting later
                # never touches the connection at all.
                decode_proc = self._start_decode_process(station)
                entry["decode_proc"] = decode_proc
                entry["encode_proc"] = self._start_encode_segment(temp_path)
            else:
                entry["process"] = self._start_ffmpeg_segment(station, temp_path, song=None)
        except Exception as e:
            log.error(f"Failed to start recording: {e}")
            if decode_proc is not None:
                try:
                    decode_proc.kill()
                except Exception:
                    pass
            wx.MessageBox(f"Could not start recording: {e}", "Recording Error",
                          wx.OK | wx.ICON_ERROR)
            return

        download_id: Optional[int] = None
        if self._db:
            # source_type="radio_recording" is what the Downloads tab's
            # Active Downloads list picks up -- without this row, a
            # manual recording never showed there at all, even while it
            # was genuinely running.
            from radiomaster.database.repository import DownloadRepository
            repo = DownloadRepository(self._db)
            download_id = repo.add(
                url=station.url, title=f"Recording: {station.name}",
                source_type="radio_recording", format=rec_format,
            )
            repo.update_progress(download_id, 0, status="downloading")
        # Falls back to the entry's own id() when there's no db (keeps
        # this panel usable standalone, e.g. in tests) -- guaranteed
        # unique among currently-alive recordings either way.
        key_id = download_id if download_id is not None else id(entry)

        self._recordings[key_id] = entry
        self.set_status(f"Status: Recording {station.name}")
        if self.on_recording_changed:
            self.on_recording_changed(self.is_station_recording(self._selected_station))

        if split_tracks:
            threading.Thread(target=self._feed_decode_to_encode, args=(key_id,), daemon=True).start()
            threading.Thread(target=self._record_track_watcher, args=(key_id,), daemon=True).start()

    def _stop_recording(self, key_id: int) -> None:
        entry = self._recordings.pop(key_id, None)
        if entry is None:
            return
        station_name = entry["station_name"]
        timer = entry.get("split_timer")
        if timer is not None:
            timer.cancel()
        if self._db:
            from radiomaster.database.repository import DownloadRepository
            repo = DownloadRepository(self._db)
            if entry.get("split_tracks"):
                # This session's placeholder row never corresponded to a
                # real file when splitting was on -- each actual track
                # already got its own completed row as it was split off
                # (see _finalize_encode_segment), including the final
                # in-progress one, which is about to be finalized by the
                # worker below. Marking this row "completed" too would
                # just leave a bogus extra "Recording: <station>" entry
                # in History alongside the real per-track ones.
                repo.delete(key_id)
            else:
                repo.update_progress(key_id, 100, status="completed")
        if self.on_recording_changed:
            self.on_recording_changed(self.is_station_recording(self._selected_station))

        def worker():
            # Still need the lock even though entry is already popped: a
            # split triggered by the watcher thread right before Stop was
            # pressed could be mid-flight (old process being finalized,
            # new one about to start) -- without serializing on the same
            # lock, this could grab entry["process"]/entry["encode_proc"]
            # mid-swap.
            with entry["lock"]:
                if entry.get("split_tracks"):
                    decode_proc = entry.get("decode_proc")
                    if decode_proc is not None:
                        # The network connection -- no graceful quit needed
                        # (it isn't writing a file, the encode side is);
                        # killing it also unblocks _feed_decode_to_encode's
                        # blocking read with a clean EOF.
                        try:
                            decode_proc.kill()
                        except Exception:
                            pass
                    self._finalize_encode_segment(entry)
                else:
                    self._finalize_current_segment(key_id, entry)

        threading.Thread(target=worker, daemon=True).start()
        self.set_status(f"Status: Stopped recording {station_name}")

    def stop_recording_by_download_id(self, download_id: int) -> bool:
        """Public entry point for the Downloads tab's "Stop Recording"
        button -- lets a specific active recording be stopped from there
        directly, without needing to first re-select that exact station
        back in the Radio tab's tree. Returns False if download_id isn't
        (or is no longer) an active recording."""
        if download_id not in self._recordings:
            return False
        self._stop_recording(download_id)
        return True

    def is_recording_active(self, download_id: int) -> bool:
        """Side-effect-free check for the Downloads tab's Remove button --
        lets it tell a genuinely still-recording row (which Remove should
        refuse, pointing at Stop Recording instead) apart from a STALE
        radio_recording row with nothing actually running for it anymore
        (left behind by a crash, or an older version's tracking), which
        should be removable like any other row."""
        return download_id in self._recordings

    def _on_add_custom(self, event: wx.CommandEvent) -> None:
        dlg = wx.TextEntryDialog(self, "Enter station URL:", "Add Custom Station")
        if dlg.ShowModal() == wx.ID_OK:
            url = dlg.GetValue().strip()
            if url:
                name_dlg = wx.TextEntryDialog(self, "Enter station name:", "Station Name")
                if name_dlg.ShowModal() == wx.ID_OK:
                    name = name_dlg.GetValue().strip() or url
                    self.station_db.add_custom(name, url)
                    self.tree.add_custom_section(self.station_db.get_custom_stations())
                    wx.MessageBox(f"Custom station '{name}' added.", "Success", wx.OK | wx.ICON_INFORMATION)
                name_dlg.Destroy()
        dlg.Destroy()

    def _display_custom_stations(self) -> None:
        """Display custom stations in the list."""
        stations = self._repo.get_custom_stations()
        self._station_list.Clear()
        self._station_data = []
        for s in stations:
            display = f"{s['name']}  [{s.get('country','')}]"
            self._station_list.Append(display)
            self._station_data.append(s)

    def display_search_results(self, results: list[dict]) -> None:
        """Display search results from global search."""
        self._station_list.Clear()
        self._station_data = []
        for r in results:
            display = f"{r['name']}  [{r.get('country','')}]  {r.get('language','')}  {r.get('bitrate','')}k"
            self._station_list.Append(display)
            self._station_data.append(r)
