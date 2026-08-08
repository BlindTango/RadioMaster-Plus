"""Radio tab panel with station browser, search, playback controls, and custom stations."""

from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
import time
from datetime import datetime
from typing import Callable, Optional

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


class RadioPanel(scrolled.ScrolledPanel):
    """Radio browsing and playback panel."""

    def __init__(self, parent, station_api: StationAPI, station_db: StationDB,
                 station_updater: StationUpdater, engine: PlaybackEngine,
                 set_status: Callable[[str], None]):
        super().__init__(parent)
        self.station_api = station_api
        self.station_db = station_db
        self.station_updater = station_updater
        self.engine = engine
        self.set_status = set_status
        self._selected_station: Optional[Station] = None
        self._search_seq = 0
        self._now_playing_generation = 0

        # Manual (Record button / hotkey) recording -- separate from the
        # timed SchedulerService recordings, this just ffmpeg-copies
        # whatever's currently selected to a file until toggled off again.
        self._record_process: Optional[subprocess.Popen] = None
        self._record_station_name: Optional[str] = None

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
        self.refresh_btn = wx.Button(self, label="&Refresh Database")

        search_row = wx.BoxSizer(wx.HORIZONTAL)
        search_row.Add(search_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        search_row.Add(self.search_ctrl, 1, wx.EXPAND | wx.RIGHT, 4)
        search_row.Add(self.search_btn, 0)

        action_row = wx.BoxSizer(wx.HORIZONTAL)
        action_row.Add(self.add_custom_btn, 0, wx.RIGHT, 6)
        action_row.Add(self.refresh_btn, 0)

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
        self.refresh_btn.Bind(wx.EVT_BUTTON, self._on_refresh)
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
            pass

    def _on_station_activated(self, station: Station) -> None:
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
        fade_seconds = ConfigManager.get_instance().get("playback.crossfade_duration", default=0)
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
            time.sleep(25)

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

    def _on_record(self) -> None:
        """Toggle recording of the selected station's stream to a file.

        Previously this only updated the status text and never actually
        started ffmpeg -- pressing Record did nothing and no file was ever
        written.
        """
        if self._record_process is not None:
            self._stop_recording()
            return

        station = self._selected_station or self.tree.get_selected_station()
        if not station:
            wx.MessageBox("Select a station first.", "No Station Selected",
                          wx.OK | wx.ICON_INFORMATION)
            return

        safe_name = re.sub(r'[<>:"/\\|?*]', "_", station.name).strip() or "station"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        recordings_dir = get_paths()["recordings"]
        os.makedirs(recordings_dir, exist_ok=True)
        output_path = os.path.join(recordings_dir, f"{safe_name}_{timestamp}.mp3")

        cmd = [get_ffmpeg(), "-y", "-i", station.url, "-c", "copy", output_path]
        try:
            self._record_process = subprocess.Popen(
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

        self._record_station_name = station.name
        self.set_status(f"Status: Recording {station.name}")

    def _stop_recording(self) -> None:
        process = self._record_process
        self._record_process = None
        station_name = self._record_station_name
        self._record_station_name = None

        def worker():
            try:
                process.terminate()
                process.wait(timeout=5)
            except Exception:
                process.kill()

        threading.Thread(target=worker, daemon=True).start()
        self.set_status(f"Status: Stopped recording {station_name}")

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

    def _on_refresh(self, event: wx.CommandEvent) -> None:
        """Manually refresh the station database."""
        self.refresh_btn.Disable()
        self.refresh_btn.SetLabel("Downloading...")
        self.set_status("Status: Updating station database...")

        def progress_cb(bytes_read: int, total) -> None:
            if total:
                percent = min(100, int(bytes_read * 100 / total))
                text = f"Status: Updating station database... {percent}%"
            else:
                text = f"Status: Updating station database... ({bytes_read // 1024} KB)"
            wx.CallAfter(self.set_status, text)

        def worker():
            result = self.station_updater.update_now(progress_cb=progress_cb)
            if result.ok:
                wx.CallAfter(self._apply_sections)
                wx.CallAfter(wx.MessageBox,
                    f"Updated {result.changed} stations ({result.unchanged} unchanged).",
                    "Refresh Complete", wx.OK | wx.ICON_INFORMATION)
            else:
                wx.CallAfter(wx.MessageBox, f"Update failed: {result.error}",
                             "Refresh Error", wx.OK | wx.ICON_ERROR)
            wx.CallAfter(self.refresh_btn.Enable)
            wx.CallAfter(self.refresh_btn.SetLabel, "&Refresh Database")

        threading.Thread(target=worker, daemon=True).start()

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
