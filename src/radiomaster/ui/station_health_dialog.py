"""Station Health Check dialog: scan the station catalog for dead
streams, name mismatches, broken websites, geo-blocks, and stale format
claims -- then hide the broken ones.

The scan itself lives in MainWindow's StationHealthService (NOT here):
closing this dialog leaves a running scan going (status bar shows
progress), and reopening reattaches to it. This dialog is just the
control surface and results view.
"""

from __future__ import annotations

import threading
from typing import Any

import wx

from radiomaster.services.station_db import StationDB
from radiomaster.services.station_health import HealthResult, StationHealthService
from radiomaster.utils.accessibility import set_accessible_name
from radiomaster.utils.wx_safe import call_after_safe

# Problem-type filter values (index into the filter Choice).
_FILTER_ALL = 0
_FILTER_DEAD = 1
_FILTER_NAME = 2
_FILTER_WEBSITE = 3
_FILTER_GEO = 4
_FILTER_FORMAT = 5

_FILTER_LABELS = [
    "All problems", "Dead streams", "Name mismatches",
    "Website down", "Geo-blocked", "Format mismatches",
]


def _problem_label(result: dict[str, Any]) -> str:
    """Short problem type for the list's Problem column."""
    if not result.get("stream_ok"):
        return "Geo-blocked" if result.get("geo_blocked") else "Dead stream"
    if result.get("name_ok") == 0:
        return "Name mismatch"
    if result.get("website_ok") == 0:
        return "Website down"
    if result.get("format_mismatch"):
        return "Format mismatch"
    return "Other"


def _format_detail(result: dict[str, Any]) -> str:
    """The Details column: the stream's actual format when known, else
    the check's detail text."""
    parts: list[str] = []
    if result.get("codec"):
        parts.append(result["codec"].upper())
    if result.get("sample_rate"):
        parts.append(f"{result['sample_rate'] / 1000:.1f} kHz")
    if result.get("channels"):
        parts.append({1: "Mono", 2: "Stereo"}.get(result["channels"], f"{result['channels']}ch"))
    if result.get("bit_rate"):
        parts.append(f"{result['bit_rate'] // 1000} kbps")
    if parts:
        return ", ".join(parts)
    return result.get("detail", "")


def _result_matches_filter(result: dict[str, Any], filter_idx: int) -> bool:
    if filter_idx == _FILTER_ALL:
        return True
    if filter_idx == _FILTER_DEAD:
        return not result.get("stream_ok")
    if filter_idx == _FILTER_NAME:
        return result.get("name_ok") == 0
    if filter_idx == _FILTER_WEBSITE:
        return result.get("website_ok") == 0
    if filter_idx == _FILTER_GEO:
        return bool(result.get("geo_blocked"))
    if filter_idx == _FILTER_FORMAT:
        return bool(result.get("format_mismatch"))
    return False


class StationHealthDialog(wx.Dialog):
    """Control surface + results view for the station health scan."""

    def __init__(self, parent: wx.Window, station_db: StationDB,
                 service: StationHealthService,
                 on_scan_finished: Any | None = None) -> None:
        super().__init__(parent, title="Station Health Check", size=(760, 540))
        self._db = station_db
        self._service = service
        self._on_scan_finished = on_scan_finished
        # uuid -> health row dict, for every problem seen this session
        # plus everything persisted from earlier scans.
        self._results: dict[str, dict[str, Any]] = {}
        self._counts = {"checked": 0, "dead": 0, "name": 0, "website": 0,
                        "geo": 0, "format": 0}
        self._finished_announced = False
        # uuid <-> stable row index mapping (SetItemData must be an int)
        self._uuid_slots: dict[str, int] = {}
        self._setup_ui()
        self._load_persisted_results()
        self._refresh_results()
        self._update_progress()
        self._update_button_states()
        self._drain_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_drain_timer, self._drain_timer)
        self._drain_timer.Start(500)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)
        self.Centre()

    def _on_destroy(self, event: wx.WindowDestroyEvent) -> None:
        if event.GetEventObject() is self:
            self._drain_timer.Stop()
        event.Skip()

    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        sizer = wx.BoxSizer(wx.VERTICAL)

        # -- Controls row ----------------------------------------------
        controls = wx.BoxSizer(wx.HORIZONTAL)
        self._btn_start = wx.Button(self, label="&Start Scan")
        set_accessible_name(self._btn_start, "Start Scan")
        self._btn_start.Bind(wx.EVT_BUTTON, self._on_start)
        controls.Add(self._btn_start, 0, wx.RIGHT, 4)

        self._btn_stop = wx.Button(self, label="S&top Scan")
        set_accessible_name(self._btn_stop, "Stop Scan")
        self._btn_stop.Bind(wx.EVT_BUTTON, lambda e: self._service.stop())
        controls.Add(self._btn_stop, 0, wx.RIGHT, 8)

        controls.Add(wx.StaticText(self, label="Parallel connections:"), 0,
                     wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self._workers_spin = wx.SpinCtrl(self, value="10", min=1, max=20, size=(60, -1))
        set_accessible_name(self._workers_spin, "Parallel Connections")
        controls.Add(self._workers_spin, 0, wx.RIGHT, 8)

        self._skip_recent = wx.CheckBox(self, label="Skip stations checked in the last 7 days")
        set_accessible_name(self._skip_recent, "Skip Recently Checked Stations")
        self._skip_recent.SetValue(True)
        controls.Add(self._skip_recent, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.Add(controls, 0, wx.EXPAND | wx.ALL, 6)

        # -- Progress ---------------------------------------------------
        self._progress_label = wx.StaticText(self, label="No scan running.")
        set_accessible_name(self._progress_label, "Scan Progress")
        sizer.Add(self._progress_label, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 6)
        self._gauge = wx.Gauge(self, wx.ID_ANY, 100)
        sizer.Add(self._gauge, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 4)

        # -- Filter -----------------------------------------------------
        filter_row = wx.BoxSizer(wx.HORIZONTAL)
        filter_row.Add(wx.StaticText(self, label="Show:"), 0,
                       wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self._filter_choice = wx.Choice(self, choices=_FILTER_LABELS)
        set_accessible_name(self._filter_choice, "Problem Filter")
        self._filter_choice.Bind(wx.EVT_CHOICE, lambda e: self._refresh_results())
        self._filter_choice.SetSelection(0)
        filter_row.Add(self._filter_choice, 0)
        sizer.Add(filter_row, 0, wx.EXPAND | wx.ALL, 6)

        # -- Results list ------------------------------------------------
        self._results_list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        set_accessible_name(self._results_list, "Health Check Results")
        self._results_list.InsertColumn(0, "Station", width=240)
        self._results_list.InsertColumn(1, "Problem", width=120)
        self._results_list.InsertColumn(2, "Details", width=330)
        self._results_list.Bind(wx.EVT_SIZE, self._on_list_resize)
        self._results_list.Bind(wx.EVT_LIST_ITEM_SELECTED,
                                lambda e: self._update_button_states())
        self._results_list.Bind(wx.EVT_LIST_ITEM_DESELECTED,
                                lambda e: self._update_button_states())
        self._results_list.Bind(wx.EVT_KEY_DOWN, self._on_list_key)
        sizer.Add(self._results_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)

        # -- Detail pane -------------------------------------------------
        self._detail_text = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY
                                        | wx.TE_NOHIDESEL)
        set_accessible_name(self._detail_text, "Selected Station Details")
        self._detail_text.SetMinSize((-1, 80))
        sizer.Add(self._detail_text, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 6)
        self._results_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_result_selected)
        self._results_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_result_selected)

        # -- Action buttons ----------------------------------------------
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        self._btn_hide = wx.Button(self, label="&Hide Selected")
        set_accessible_name(self._btn_hide, "Hide Selected Station")
        self._btn_hide.Bind(wx.EVT_BUTTON, self._on_hide_selected)
        buttons.Add(self._btn_hide, 0, wx.RIGHT, 4)

        self._btn_hide_dead = wx.Button(self, label="Hide All &Dead")
        set_accessible_name(self._btn_hide_dead, "Hide All Dead Stations")
        self._btn_hide_dead.Bind(wx.EVT_BUTTON, self._on_hide_all_dead)
        buttons.Add(self._btn_hide_dead, 0, wx.RIGHT, 4)

        self._btn_recheck = wx.Button(self, label="&Recheck Selected")
        set_accessible_name(self._btn_recheck, "Recheck Selected Station")
        self._btn_recheck.Bind(wx.EVT_BUTTON, self._on_recheck_selected)
        buttons.Add(self._btn_recheck, 0, wx.RIGHT, 4)

        self._btn_play = wx.Button(self, label="&Play")
        set_accessible_name(self._btn_play, "Play Selected Station")
        self._btn_play.Bind(wx.EVT_BUTTON, self._on_play_selected)
        buttons.Add(self._btn_play, 0, wx.RIGHT, 4)

        self._btn_hidden = wx.Button(self, label="Manage &Hidden...")
        set_accessible_name(self._btn_hidden, "Manage Hidden Stations")
        self._btn_hidden.Bind(wx.EVT_BUTTON, self._on_manage_hidden)
        buttons.Add(self._btn_hidden, 0, wx.RIGHT, 4)

        close_btn = wx.Button(self, label="Close", id=wx.ID_CLOSE)
        set_accessible_name(close_btn, "Close")
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CANCEL))
        buttons.Add(close_btn, 0)
        sizer.Add(buttons, 0, wx.EXPAND | wx.ALL, 6)

        self.SetSizer(sizer)
        # wx.ID_CLOSE doesn't get automatic Escape handling -- bind it.
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)

    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CANCEL)
        else:
            event.Skip()

    def _on_list_resize(self, event: wx.SizeEvent) -> None:
        event.Skip()
        width = self._results_list.GetClientSize().width
        self._results_list.SetColumnWidth(2, max(100, width - 240 - 120 - 8))

    def _on_list_key(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_DELETE:
            self._on_hide_selected(event)
        else:
            event.Skip()

    # ------------------------------------------------------------------
    # Scan lifecycle
    # ------------------------------------------------------------------
    def _on_start(self, event: wx.CommandEvent) -> None:
        if self._service.running:
            wx.MessageBox("A scan is already running.", "Scan Running",
                          wx.OK | wx.ICON_INFORMATION, self)
            return
        # Build the work list on a worker thread: all_stations() on a
        # 50k+ catalog takes a moment, and the UI must not freeze.
        skip_recent = self._skip_recent.GetValue()
        workers = self._workers_spin.GetValue()

        def build_and_start():
            stations = self._db.all_stations()
            for custom in self._db.get_custom_stations():
                if custom.uuid not in {s.uuid for s in stations}:
                    stations.append(custom)
            for fav in self._db.get_favorite_stations():
                if fav.uuid not in {s.uuid for s in stations}:
                    stations.append(fav)
            if skip_recent:
                recent = self._db.recently_checked_uuids(7)
                stations = [s for s in stations if s.uuid not in recent]
            hidden = self._db.hidden_uuids()
            stations = [s for s in stations if s.uuid not in hidden]
            call_after_safe(self, self._start_service, stations, workers)

        threading.Thread(target=build_and_start, daemon=True,
                         name="health-scan-prepare").start()

    def _start_service(self, stations, workers) -> None:
        if not stations:
            wx.MessageBox("No stations to check (everything was checked "
                          "recently or is hidden).", "Nothing to Check",
                          wx.OK | wx.ICON_INFORMATION, self)
            return
        self._service.__init__(workers=workers)  # reconfigure worker count
        self._finished_announced = False
        self._counts = {"checked": 0, "dead": 0, "name": 0, "website": 0,
                        "geo": 0, "format": 0}
        self._service.start(stations)
        self._update_button_states()

    def _on_drain_timer(self, event: wx.TimerEvent) -> None:
        """Drain finished results, persist them in one batch, update
        the list in place -- the DownloadsPanel pattern, so the
        accessibility tree is never churned by a full rebuild."""
        results = self._service.drain_results(500)
        if results:
            rows = []
            for r in results:
                row = r.to_row()
                row["_name"] = r.station_name  # display-only, stripped before persisting
                rows.append(row)
                self._counts["checked"] += 1
                if not r.stream_ok:
                    self._counts["dead"] += 1
                    if r.geo_blocked:
                        self._counts["geo"] += 1
                if r.name_ok is False:
                    self._counts["name"] += 1
                if r.website_ok is False:
                    self._counts["website"] += 1
                if r.format_mismatch:
                    self._counts["format"] += 1
                if r.is_problem:
                    self._results[r.uuid] = row
            self._db.record_health_results(rows)
            self._refresh_results()
        self._update_progress()
        # Completion: every station checked (or skipped), workers
        # exited, and this final batch drained -- announce exactly once.
        if not self._finished_announced and self._service.is_finished():
            self._finished_announced = True
            self._announce_completion(stopped=self._service.stopped)

    def _announce_completion(self, stopped: bool = False) -> None:
        c = self._counts
        verb = "stopped" if stopped else "complete"
        summary = (f"Scan {verb}: {c['checked']} checked, {c['dead']} dead streams, "
                   f"{c['name']} name mismatches, {c['website']} websites down, "
                   f"{c['geo']} geo-blocked, {c['format']} format mismatches.")
        self._progress_label.SetLabel(summary)
        if self._on_scan_finished:
            self._on_scan_finished(summary)
        wx.CallAfter(lambda: wx.MessageBox(summary, "Scan " + verb.title(),
                                           wx.OK | wx.ICON_INFORMATION, self)
                     if self and self.IsShown() else None)
        self._update_button_states()

    def _update_progress(self) -> None:
        if not self._service.running and self._service.done == 0:
            self._gauge.SetValue(0)
            return
        total = max(1, self._service.total)
        pct = int(100 * self._service.done / total)
        self._gauge.SetValue(pct)
        eta = self._service.eta_seconds()
        eta_text = ""
        if eta is not None and eta > 60:
            eta_text = f" — ETA {int(eta // 3600)}h {int((eta % 3600) // 60)}m"
        elif eta is not None:
            eta_text = f" — ETA {int(eta)}s"
        problems = (self._counts["dead"] + self._counts["name"]
                    + self._counts["website"] + self._counts["geo"]
                    + self._counts["format"])
        self._progress_label.SetLabel(
            f"Checked {self._service.done:,} / {self._service.total:,} ({pct}%)"
            f" — {problems:,} problems{eta_text}"
        )

    # ------------------------------------------------------------------
    # Results list
    # ------------------------------------------------------------------
    def _load_persisted_results(self) -> None:
        """Past-scan problems, so the dialog is useful before any scan
        this session. Names are joined from the catalog (the health
        table deliberately doesn't duplicate them)."""
        names: dict[str, str] = {}
        for s in self._db.all_stations():
            names[s.uuid] = s.name
        for s in self._db.get_custom_stations():
            names.setdefault(s.uuid, s.name)
        for s in self._db.get_favorite_stations():
            names.setdefault(s.uuid, s.name)
        for row in self._db.health_results(problems_only=True):
            row["_name"] = names.get(row["uuid"], row["uuid"])
            self._results[row["uuid"]] = row

    def _refresh_results(self) -> None:
        """Rebuild the visible rows for the current filter. A full
        rebuild only happens when new problem rows arrived (rare --
        problems are a small fraction of checks); selection is restored
        by uuid afterward."""
        selected_uuid = self._selected_uuid()
        self._results_list.DeleteAllItems()
        filter_idx = self._filter_choice.GetSelection()
        # Sort: dead first (most actionable), then by name.
        def sort_key(item):
            uuid, row = item
            dead = 0 if row.get("stream_ok") else 1
            return (dead, self._station_name(uuid).lower())
        for uuid, row in sorted(self._results.items(), key=sort_key):
            if not _result_matches_filter(row, filter_idx):
                continue
            idx = self._results_list.InsertItem(self._results_list.GetItemCount(),
                                                 self._station_name(uuid))
            self._results_list.SetItem(idx, 1, _problem_label(row))
            self._results_list.SetItem(idx, 2, _format_detail(row))
            self._results_list.SetItemData(idx, self._list_index_for_uuid(uuid))
        if selected_uuid:
            for i in range(self._results_list.GetItemCount()):
                if self._results_list.GetItemData(i) == self._uuid_index(selected_uuid):
                    self._results_list.Select(i)
                    self._results_list.EnsureVisible(i)
                    break
        self._update_button_states()

    # uuid <-> stable int slot for SetItemData (instance-level: a
    # class-level dict would leak slots across dialog instances).
    def _list_index_for_uuid(self, uuid: str) -> int:
        if uuid not in self._uuid_slots:
            self._uuid_slots[uuid] = len(self._uuid_slots)
        return self._uuid_slots[uuid]

    def _uuid_index(self, uuid: str) -> int:
        return self._list_index_for_uuid(uuid)

    def _uuid_for_index(self, index: int) -> str | None:
        for uuid, slot in self._uuid_slots.items():
            if slot == index:
                return uuid
        return None

    def _station_name(self, uuid: str) -> str:
        row = self._results.get(uuid, {})
        return row.get("_name") or row.get("name_hint") or uuid

    def _selected_uuid(self) -> str | None:
        idx = self._results_list.GetFirstSelected()
        if idx == wx.NOT_FOUND:
            return None
        return self._uuid_for_index(self._results_list.GetItemData(idx))

    def _on_result_selected(self, event) -> None:
        uuid = self._selected_uuid()
        if not uuid:
            return
        row = self._results.get(uuid, {})
        lines = [f"Station: {self._station_name(uuid)}"]
        if row.get("stream_ok"):
            actual = _format_detail(row)
            if actual:
                lines.append(f"Actual format: {actual}")
            db_parts = []
            if row.get("db_codec"):
                db_parts.append(str(row["db_codec"]).upper())
            if row.get("db_bitrate"):
                db_parts.append(f"{row['db_bitrate']} kbps")
            if db_parts:
                lines.append(f"Database says: {', '.join(db_parts)}")
        if row.get("detail"):
            lines.append(f"Detail: {row['detail']}")
        if row.get("geo_blocked"):
            lines.append("This station appears to be geo-restricted from your location.")
        lines.append(f"Checked: {row.get('checked_at', 'unknown')}")
        self._detail_text.SetValue("\n".join(lines))

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _update_button_states(self) -> None:
        running = self._service.running
        self._btn_start.Enable(not running)
        self._btn_stop.Enable(running)
        has_selection = self._selected_uuid() is not None
        self._btn_hide.Enable(has_selection)
        self._btn_recheck.Enable(has_selection and not running)
        self._btn_play.Enable(has_selection)
        self._btn_hide_dead.Enable(self._counts["dead"] > 0)

    def _on_hide_selected(self, event: wx.CommandEvent) -> None:
        uuid = self._selected_uuid()
        if not uuid:
            return
        name = self._station_name(uuid)
        if wx.MessageBox(f"Hide '{name}' from all station lists?",
                         "Hide Station", wx.YES_NO | wx.ICON_QUESTION, self) != wx.YES:
            return
        self._db.hide_station(uuid, reason=_problem_label(self._results.get(uuid, {})))
        self._results.pop(uuid, None)
        self._refresh_results()

    def _on_hide_all_dead(self, event: wx.CommandEvent) -> None:
        dead = [uuid for uuid, row in self._results.items() if not row.get("stream_ok")]
        if not dead:
            return
        if wx.MessageBox(f"Hide all {len(dead)} stations with dead streams?",
                         "Hide Dead Stations", wx.YES_NO | wx.ICON_QUESTION, self) != wx.YES:
            return
        for uuid in dead:
            self._db.hide_station(uuid, reason="Dead stream")
            self._results.pop(uuid, None)
        self._refresh_results()

    def _on_recheck_selected(self, event: wx.CommandEvent) -> None:
        uuid = self._selected_uuid()
        if not uuid or self._service.running:
            return
        # Find the station in the catalog and check it synchronously on
        # a worker thread, then update the row.
        def recheck():
            station = None
            for s in self._db.all_stations():
                if s.uuid == uuid:
                    station = s
                    break
            if station is None:
                for s in self._db.get_custom_stations() + self._db.get_favorite_stations():
                    if s.uuid == uuid:
                        station = s
                        break
            if station is None:
                return
            from radiomaster.services.station_health import check_station
            result = check_station(station)
            call_after_safe(self, self._apply_recheck, result)

        threading.Thread(target=recheck, daemon=True, name="health-recheck").start()

    def _apply_recheck(self, result: HealthResult) -> None:
        row = result.to_row()
        self._db.record_health_results([row])
        if result.is_problem:
            self._results[result.uuid] = row
        else:
            self._results.pop(result.uuid, None)
        self._refresh_results()

    def _on_play_selected(self, event: wx.CommandEvent) -> None:
        uuid = self._selected_uuid()
        if not uuid:
            return
        # Play through the main window's engine via the parent hook.
        parent = self.GetParent()
        station = None
        for s in self._db.all_stations(limit=200000):
            if s.uuid == uuid:
                station = s
                break
        if station is None:
            wx.MessageBox("Could not find this station in the catalog.",
                          "Not Found", wx.OK | wx.ICON_WARNING, self)
            return
        if parent and hasattr(parent, "_radio_panel"):
            self.EndModal(wx.ID_OK)
            wx.CallAfter(lambda: parent._radio_panel._play_station(station))

    def _on_manage_hidden(self, event: wx.CommandEvent) -> None:
        dlg = _HiddenStationsDialog(self, self._db)
        dlg.ShowModal()
        dlg.Destroy()
        # A station unhidden from there may reappear in results.
        self._refresh_results()


class _HiddenStationsDialog(wx.Dialog):
    """List of hidden stations with Unhide / Unhide All."""

    def __init__(self, parent: wx.Window, station_db: StationDB) -> None:
        super().__init__(parent, title="Hidden Stations", size=(520, 380))
        self._db = station_db
        sizer = wx.BoxSizer(wx.VERTICAL)
        self._list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        set_accessible_name(self._list, "Hidden Stations")
        self._list.InsertColumn(0, "Station", width=260)
        self._list.InsertColumn(1, "Reason", width=200)
        sizer.Add(self._list, 1, wx.EXPAND | wx.ALL, 6)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        self._btn_unhide = wx.Button(self, label="&Unhide Selected")
        set_accessible_name(self._btn_unhide, "Unhide Selected Station")
        self._btn_unhide.Bind(wx.EVT_BUTTON, self._on_unhide)
        buttons.Add(self._btn_unhide, 0, wx.RIGHT, 4)
        self._btn_unhide_all = wx.Button(self, label="Unhide &All")
        set_accessible_name(self._btn_unhide_all, "Unhide All Stations")
        self._btn_unhide_all.Bind(wx.EVT_BUTTON, self._on_unhide_all)
        buttons.Add(self._btn_unhide_all, 0, wx.RIGHT, 4)
        close_btn = wx.Button(self, label="Close", id=wx.ID_CLOSE)
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CANCEL))
        buttons.Add(close_btn, 0)
        sizer.Add(buttons, 0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(sizer)
        self._list.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda e: self._update_buttons())
        self._list.Bind(wx.EVT_LIST_ITEM_DESELECTED, lambda e: self._update_buttons())
        self._refresh()

    def _refresh(self) -> None:
        self._list.DeleteAllItems()
        hidden = self._db.hidden_stations()
        for _uuid, name, reason in hidden:
            idx = self._list.InsertItem(self._list.GetItemCount(), name)
            self._list.SetItem(idx, 1, reason)
            self._list.SetItemData(idx, self._list.GetItemCount() - 1)
        self._uuids = [row[0] for row in hidden]
        self._update_buttons()

    def _update_buttons(self) -> None:
        has_selection = self._list.GetFirstSelected() != wx.NOT_FOUND
        self._btn_unhide.Enable(has_selection)
        self._btn_unhide_all.Enable(self._list.GetItemCount() > 0)

    def _on_unhide(self, event: wx.CommandEvent) -> None:
        idx = self._list.GetFirstSelected()
        if idx == wx.NOT_FOUND:
            return
        self._db.unhide_station(self._uuids[idx])
        self._refresh()

    def _on_unhide_all(self, event: wx.CommandEvent) -> None:
        count = self._db.unhide_all()
        if count:
            wx.MessageBox(f"Unhid {count} stations.", "Done",
                          wx.OK | wx.ICON_INFORMATION, self)
        self._refresh()
