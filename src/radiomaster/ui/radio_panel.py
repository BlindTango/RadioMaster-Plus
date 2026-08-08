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

    # Each poll opens a fresh connection to the stream and reads real
    # audio bytes up to the station's icy-metaint boundary just to reach
    # the metadata block (see StreamReader.get_icy_metadata) -- not free,
    # so this can't be tightened arbitrarily without meaningfully adding
    # to a station's bandwidth bill. 8s (rather than the previous 25s)
    # caps how long a radio song-change can go undetected -- and with it,
    # how far the LRC sync offset in MainWindow._lyrics_song_start_position
    # can lag behind the song's real start -- while staying a reasonable
    # request rate for a single listening session.
    NOW_PLAYING_POLL_SECONDS = 8

    def _poll_now_playing(self, url: str, generation: int) -> None:
        from radiomaster.engine.stream_reader import StreamReader
        last_song = None
        while generation == self._now_playing_generation:
            metadata = StreamReader.get_icy_metadata(url, timeout=8)
            if generation != self._now_playing_generation:
                return
            song = metadata.get("current_song", "")
            if song and song != last_song:
                last_song = song
                wx.CallAfter(self.now_playing.set_now_playing, song)
                artist, title = _parse_icy_song(song)
                if title and self.on_now_playing_changed:
                    wx.CallAfter(self.on_now_playing_changed, artist, title)
            time.sleep(self.NOW_PLAYING_POLL_SECONDS)

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

        safe_name = re.sub(r'[<>:"/\\|?*]', "_", station.name).strip() or "station"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        recordings_dir = get_paths()["recordings"]
        os.makedirs(recordings_dir, exist_ok=True)
        output_path = os.path.join(recordings_dir, f"{safe_name}_{timestamp}.mp3")

        cmd = [get_ffmpeg(), "-y", "-i", station.url, "-c", "copy", output_path]
        try:
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except Exception as e:
            log.error(f"Failed to start recording: {e}")
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
                source_type="radio_recording", format="mp3",
            )
            repo.update_progress(download_id, 0, status="downloading")
        # Falls back to the process's own id() when there's no db (keeps
        # this panel usable standalone, e.g. in tests) -- guaranteed
        # unique among currently-alive Popen objects either way.
        key_id = download_id if download_id is not None else id(process)

        self._recordings[key_id] = {
            "process": process, "station_name": station.name, "station_key": key,
        }
        self.set_status(f"Status: Recording {station.name}")
        if self.on_recording_changed:
            self.on_recording_changed(self.is_station_recording(self._selected_station))

    def _stop_recording(self, key_id: int) -> None:
        entry = self._recordings.pop(key_id, None)
        if entry is None:
            return
        process = entry["process"]
        station_name = entry["station_name"]
        if self._db:
            from radiomaster.database.repository import DownloadRepository
            DownloadRepository(self._db).update_progress(key_id, 100, status="completed")
        if self.on_recording_changed:
            self.on_recording_changed(self.is_station_recording(self._selected_station))

        def worker():
            try:
                process.terminate()
                process.wait(timeout=5)
            except Exception:
                process.kill()

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
