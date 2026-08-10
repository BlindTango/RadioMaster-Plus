"""Radio tab panel with station browser, search, playback controls, and custom stations."""

from __future__ import annotations

import logging
import os
import threading
import time
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
from radiomaster.utils.accessibility import context_menu_pos

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
        # Fired with a human-readable "MP3, 44.1 kHz, Stereo, 320 kbps"
        # summary once a background ffprobe of the just-played station
        # completes (see _probe_and_report_format) -- MainWindow wires
        # this to the status bar's dedicated format field. Fired with ""
        # on stop/station-switch so a stale reading doesn't linger.
        self.on_format_detected: Optional[Callable[[str], None]] = None

        # Volume/Pan/Rate submenus on the station list's context menu
        # (see _on_station_context_menu) delegate the actual value
        # change to MainWindow instead of touching self.engine directly
        # -- MainWindow's handlers also update the transport bar's own
        # sliders and save the new value to config, which this panel has
        # no reference to do on its own. delta is signed: positive steps
        # up/right, negative steps down/left.
        self.on_volume_step: Optional[Callable[[float], None]] = None
        self.on_pan_step: Optional[Callable[[float], None]] = None
        self.on_rate_step: Optional[Callable[[float], None]] = None
        self.on_mute_toggle: Optional[Callable[[], None]] = None

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
        self.tree.set_favorite_stations(self.station_db.get_favorite_stations())

        self.tree.station_list.Bind(wx.EVT_CONTEXT_MENU, self._on_station_context_menu)

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

        # Probe the station's real broadcast format in the background --
        # the station database's own codec/bitrate fields are self-
        # reported and often missing/stale/wrong, so this asks the
        # stream itself instead. Same generation guard as Now Playing:
        # a stale probe from a station switched away from before it
        # finished must not overwrite the status bar with old data.
        if self.on_format_detected:
            self.on_format_detected("")
        threading.Thread(target=self._probe_and_report_format, args=(station.url, generation),
                          daemon=True).start()

    def _probe_and_report_format(self, url: str, generation: int) -> None:
        from radiomaster.services.stream_prober import format_stream_format, probe_stream_format
        fmt = probe_stream_format(url, timeout=10.0)
        if generation != self._now_playing_generation or not self.on_format_detected:
            return  # switched stations (or stopped) while probing
        wx.CallAfter(self.on_format_detected, format_stream_format(fmt))

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
        if self.on_format_detected:
            self.on_format_detected("")
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

    def _toggle_favorite(self, station: Station) -> None:
        if self.station_db.is_favorite(station.uuid):
            self.station_db.remove_favorite(station.uuid)
            self.set_status(f"Status: Removed '{station.name}' from Favorites")
        else:
            self.station_db.add_favorite(station)
            self.set_status(f"Status: Added '{station.name}' to Favorites")
        self.tree.set_favorite_stations(self.station_db.get_favorite_stations())

    def _on_station_context_menu(self, event: wx.ContextMenuEvent) -> None:
        """Right-click (or Shift+F10/Menu key) on a station in the list --
        the first context menu in the app, covering the actions asked
        for: play/pause/stop, add/remove favorite, record, and Volume/
        Pan/Rate submenus. Meant as the template other panels' context
        menus will follow."""
        station = self.tree.get_selected_station()
        if station is None:
            event.Skip()
            return
        menu = wx.Menu()

        same_station = self.engine.current_url == station.url
        if same_station and self.engine.state == "paused":
            play_item = menu.Append(wx.ID_ANY, "&Resume")
            self.Bind(wx.EVT_MENU, lambda e: self.engine.resume(), play_item)
        elif same_station and self.engine.state in ("playing", "buffering"):
            play_item = menu.Append(wx.ID_ANY, "&Pause")
            self.Bind(wx.EVT_MENU, lambda e: self.engine.pause(), play_item)
        else:
            play_item = menu.Append(wx.ID_ANY, "&Play")
            self.Bind(wx.EVT_MENU, lambda e: self._play_station(station), play_item)

        stop_item = menu.Append(wx.ID_ANY, "&Stop")
        stop_item.Enable(same_station and self.engine.state != "stopped")
        self.Bind(wx.EVT_MENU, lambda e: self._on_stop(), stop_item)

        menu.AppendSeparator()

        is_fav = self.station_db.is_favorite(station.uuid)
        fav_item = menu.Append(wx.ID_ANY, "Remove from &Favorites" if is_fav else "Add to &Favorites")
        self.Bind(wx.EVT_MENU, lambda e: self._toggle_favorite(station), fav_item)

        is_recording = self.is_station_recording(station)
        record_item = menu.Append(wx.ID_ANY, "Stop &Recording" if is_recording else "&Record")
        self.Bind(wx.EVT_MENU, lambda e: self._on_record(), record_item)

        menu.AppendSeparator()

        volume_menu = wx.Menu()
        vol_up = volume_menu.Append(wx.ID_ANY, "Volume &Up")
        vol_down = volume_menu.Append(wx.ID_ANY, "Volume &Down")
        mute_item = volume_menu.Append(wx.ID_ANY, "&Mute/Unmute")
        self.Bind(wx.EVT_MENU, lambda e: self.on_volume_step(0.05) if self.on_volume_step else None, vol_up)
        self.Bind(wx.EVT_MENU, lambda e: self.on_volume_step(-0.05) if self.on_volume_step else None, vol_down)
        self.Bind(wx.EVT_MENU, lambda e: self.on_mute_toggle() if self.on_mute_toggle else None, mute_item)
        menu.AppendSubMenu(volume_menu, "&Volume")

        pan_menu = wx.Menu()
        pan_left = pan_menu.Append(wx.ID_ANY, "Pan &Left")
        pan_right = pan_menu.Append(wx.ID_ANY, "Pan &Right")
        pan_center = pan_menu.Append(wx.ID_ANY, "&Center")
        self.Bind(wx.EVT_MENU, lambda e: self.on_pan_step(-0.1) if self.on_pan_step else None, pan_left)
        self.Bind(wx.EVT_MENU, lambda e: self.on_pan_step(0.1) if self.on_pan_step else None, pan_right)
        self.Bind(wx.EVT_MENU,
                  lambda e: self.on_pan_step(-self.engine.pan) if self.on_pan_step else None, pan_center)
        menu.AppendSubMenu(pan_menu, "P&an")

        rate_menu = wx.Menu()
        rate_up = rate_menu.Append(wx.ID_ANY, "Rate &Up")
        rate_down = rate_menu.Append(wx.ID_ANY, "Rate &Down")
        rate_reset = rate_menu.Append(wx.ID_ANY, "&Reset to 1.0x")
        self.Bind(wx.EVT_MENU, lambda e: self.on_rate_step(0.1) if self.on_rate_step else None, rate_up)
        self.Bind(wx.EVT_MENU, lambda e: self.on_rate_step(-0.1) if self.on_rate_step else None, rate_down)
        self.Bind(wx.EVT_MENU,
                  lambda e: self.on_rate_step(1.0 - self.engine.rate) if self.on_rate_step else None, rate_reset)
        menu.AppendSubMenu(rate_menu, "&Rate")

        self.tree.station_list.PopupMenu(menu, context_menu_pos(self.tree.station_list, event))
        menu.Destroy()

    def _on_record(self) -> None:
        """Toggle recording of the selected station's stream to a file.

        Multiple different stations can each be recording at once --
        pressing Record again for a station that ISN'T already recording
        starts a new, independent recording alongside any others; only
        pressing Record while the *selected* station's own recording is
        active stops that one specifically (matching the Recording
        Scheduler's existing "multiple simultaneous recordings" promise
        in the README).

        Uses the shared RecordingSession (see services/recording_session.py)
        -- the same engine SchedulerService's timed recordings use -- so
        Settings > Recordings > "Split recordings into tracks" and
        "Record in the station's original format when possible" behave
        identically for a manual Record as for a scheduled one.
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

        from radiomaster.services.recording_session import RecordingSession
        from radiomaster.services.stream_prober import probe_stream_format
        from radiomaster.utils.config import ConfigManager
        from radiomaster.utils.paths import get_recordings_dir
        config = ConfigManager.get_instance()
        recordings_dir = get_recordings_dir()
        rec_format = config.get("recordings.recording_format", default="mp3")
        quality = config.get("recordings.recording_quality", default="320k")
        add_metadata = config.get("recordings.add_metadata", default=True)
        split_tracks = config.get("recordings.split_tracks", default=True)
        match_source = config.get("recordings.match_source_format", default=True)

        # Probing blocks briefly here (bounded by timeout) -- acceptable
        # since starting a recording already has a moment of "Connecting"
        # latency, and skipping it would mean every match_source
        # recording silently falls back to the configured format instead
        # of the station's real one.
        source_format = probe_stream_format(station.url, timeout=6.0) if match_source else None

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
        # Falls back to a fresh object's own id() when there's no db
        # (keeps this panel usable standalone, e.g. in tests) --
        # guaranteed unique among currently-alive recordings either way.
        key_id = download_id if download_id is not None else id(object())

        def _on_segment(file_path: str, title: str) -> None:
            if not self._db:
                return
            from radiomaster.database.repository import DownloadRepository
            repo = DownloadRepository(self._db)
            if split_tracks:
                # A split-off track is a finished file the moment it's
                # renamed -- fires once per track *during* the still-
                # running recording session, not just when the whole
                # session eventually stops, so each one shows up in
                # Download History right away instead of only a single
                # generic "Recording: <station>" row at the end.
                repo.add_completed(
                    url=station.url, title=os.path.splitext(os.path.basename(file_path))[0],
                    source_type="radio_recording", file_path=file_path,
                )
            else:
                # _stop_recording already marked this row "completed"
                # synchronously (so the Downloads tab reflects Stop
                # immediately) -- but that happens before the file is
                # actually renamed, so file_path couldn't be known yet.
                # Backfilling it now is what makes a plain (non-split)
                # recording playable from Download History at all.
                repo.set_file_path(key_id, file_path)

        try:
            session = RecordingSession(
                station_url=station.url, station_name=station.name, output_dir=recordings_dir,
                rec_format=rec_format, quality=quality, add_metadata=add_metadata,
                split_tracks=split_tracks, match_source=match_source, source_format=source_format,
                on_segment_finalized=_on_segment,
            )
            session.start()
        except Exception as e:
            log.error(f"Failed to start recording: {e}")
            if download_id is not None and self._db:
                from radiomaster.database.repository import DownloadRepository
                DownloadRepository(self._db).delete(download_id)
            wx.MessageBox(f"Could not start recording: {e}", "Recording Error",
                          wx.OK | wx.ICON_ERROR)
            return

        self._recordings[key_id] = {
            "station_name": station.name, "station_key": key, "station": station,
            "session": session, "split_tracks": split_tracks,
        }
        self.set_status(f"Status: Recording {station.name}")
        if self.on_recording_changed:
            self.on_recording_changed(self.is_station_recording(self._selected_station))

    def _stop_recording(self, key_id: int) -> None:
        entry = self._recordings.pop(key_id, None)
        if entry is None:
            return
        station_name = entry["station_name"]
        if self._db:
            from radiomaster.database.repository import DownloadRepository
            repo = DownloadRepository(self._db)
            if entry.get("split_tracks"):
                # This session's placeholder row never corresponded to a
                # real file when splitting was on -- each actual track
                # already got its own completed row as it was split off
                # (see _on_segment in _on_record), including the final
                # in-progress one, which session.stop() below is about to
                # finalize. Marking this row "completed" too would just
                # leave a bogus extra "Recording: <station>" entry in
                # History alongside the real per-track ones.
                repo.delete(key_id)
            else:
                repo.update_progress(key_id, 100, status="completed")
        if self.on_recording_changed:
            self.on_recording_changed(self.is_station_recording(self._selected_station))
        # session.stop() can block for several seconds finalizing the
        # in-progress ffmpeg process(es) -- keep that off the UI thread.
        threading.Thread(target=entry["session"].stop, daemon=True).start()
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
