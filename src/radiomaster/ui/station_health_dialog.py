"""Station Health Check dialog: scan the station catalog for dead
streams, name mismatches, broken websites, geo-blocks, and stale format
claims -- then hide the broken ones.

The scan itself lives in MainWindow's StationHealthService (NOT here):
closing this dialog leaves a running scan going (status bar shows
progress), and reopening reattaches to it. This dialog is just the
control surface and results view.
"""

from __future__ import annotations

import logging
import queue
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


class _HealthResultsList(wx.ListCtrl):
    """Native virtual list: expose text on demand, without inserting 50,000 rows."""

    def __init__(self, parent):
        self.rows: list[tuple[str, tuple[str, str, str]]] = []
        super().__init__(parent, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_VIRTUAL)

    def OnGetItemText(self, item: int, column: int) -> str:
        if 0 <= item < len(self.rows) and 0 <= column < 3:
            return self.rows[item][1][column]
        return ""


def _build_result_view(results, filter_idx):
    """Pure worker-side filtering, sorting, and display formatting."""
    matching = [(uuid, row) for uuid, row in results if _result_matches_filter(row, filter_idx)]
    matching.sort(key=lambda pair: (
        bool(pair[1].get("stream_ok")),
        (pair[1].get("_name") or pair[1].get("name_hint") or pair[0]).casefold(),
        pair[0],
    ))
    return [(uuid, (row.get("_name") or row.get("name_hint") or uuid,
                    _problem_label(row), _format_detail(row))) for uuid, row in matching]


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
        self._closed = False
        self._view_generation = 0
        self._view_jobs = queue.Queue()
        self._save_jobs = queue.Queue()
        self._live_uuids: set[str] = set()
        self._hidden_uuids: set[str] = set()
        self._unhidden_uuids: set[str] = set()
        self._hiding = False
        self._reported_errors: set[str] = set()
        self._setup_ui()
        self._view_thread = threading.Thread(target=self._view_worker, daemon=True,
                                             name="health-filter")
        self._view_thread.start()
        # Finish accepted writes even if the application closes immediately.
        self._save_thread = threading.Thread(target=self._save_worker, name="health-save")
        self._save_thread.start()
        # Persisted results load on a worker thread: building the name
        # map iterates the entire 50k+ catalog, which took multiple
        # seconds ON THE UI THREAD at dialog open -- a visible freeze
        # before the scan even started. The list starts empty and fills
        # via call_after_safe the moment the load finishes.
        threading.Thread(target=self._load_persisted_async, daemon=True,
                         name="health-load-persisted").start()
        self._update_progress()
        self._update_button_states()
        self._drain_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_drain_timer, self._drain_timer)
        self._drain_timer.Start(500)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)
        self.Centre()

    def _on_destroy(self, event: wx.WindowDestroyEvent) -> None:
        if event.GetEventObject() is self:
            self._stop_workers()
        event.Skip()

    def Destroy(self) -> bool:
        # wx can defer native destruction until idle. Stop accepting work now,
        # rather than keeping worker queues alive until that event arrives.
        self._stop_workers()
        return super().Destroy()

    def _stop_workers(self) -> None:
        if not self._closed:
            self._closed = True
            self._view_generation += 1
            self._view_jobs.put(None)
            self._save_jobs.put(None)
            self._drain_timer.Stop()

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
        self._results_list = _HealthResultsList(self)
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
            # One set built once -- the original rebuilt a 50k-element
            # set comprehension INSIDE the loop for every custom/favorite
            # station, an O(n*m) stall even on this worker thread.
            seen = {s.uuid for s in stations}
            for custom in self._db.get_custom_stations():
                if custom.uuid not in seen:
                    stations.append(custom)
                    seen.add(custom.uuid)
            for fav in self._db.get_favorite_stations():
                if fav.uuid not in seen:
                    stations.append(fav)
                    seen.add(fav.uuid)
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
        """Consume a bounded batch; filtering and database writes run on workers."""
        if self._closed:
            return
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
                self._live_uuids.add(r.uuid)
                if r.is_problem:
                    self._results[r.uuid] = row
                else:
                    self._results.pop(r.uuid, None)
            self._save_jobs.put(rows)
            self._refresh_results()
        self._update_progress()
        # Completion: every station checked (or skipped), workers
        # exited, and this final batch drained -- announce exactly once.
        if (not self._finished_announced and self._service.is_finished()
                and not self._save_jobs.unfinished_tasks):
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
    def _load_persisted_async(self) -> None:
        try:
            names = {station.uuid: station.name for station in self._db.all_stations()}
            for station in self._db.get_custom_stations() + self._db.get_favorite_stations():
                names.setdefault(station.uuid, station.name)
            hidden = self._db.hidden_uuids()
            for uuid, name, _reason in self._db.hidden_stations():
                names.setdefault(uuid, name)
            loaded = {}
            for row in self._db.health_results(problems_only=True):
                row["_name"] = names.get(row["uuid"], row["uuid"])
                loaded[row["uuid"]] = row
            call_after_safe(self, self._apply_persisted_results, loaded, hidden)
        except Exception as error:
            logging.getLogger("radiomaster").exception("Could not load station health results")
            call_after_safe(self, self._show_results_error, "load", str(error))

    def _apply_persisted_results(self, loaded: dict[str, dict[str, Any]],
                                 hidden: set[str]) -> None:
        if self._closed:
            return
        # A slow initial load must not overwrite a newer scan/recheck or restore
        # a result the user hid while the database was being read.
        self._results.update({uuid: row for uuid, row in loaded.items()
                              if uuid not in self._live_uuids})
        self._hidden_uuids.update(hidden - self._unhidden_uuids)
        self._refresh_results()

    def _refresh_results(self) -> None:
        if self._closed:
            return
        self._view_generation += 1
        # Keep only the latest request while a filter worker is busy.
        try:
            while True:
                self._view_jobs.get_nowait()
        except queue.Empty:
            pass
        visible = tuple((uuid, row) for uuid, row in self._results.items()
                        if uuid not in self._hidden_uuids)
        self._view_jobs.put((self._view_generation, visible,
                             self._filter_choice.GetSelection()))

    def _view_worker(self) -> None:
        while True:
            job = self._view_jobs.get()
            if job is None or self._closed:
                return
            generation, snapshot, filter_idx = job
            try:
                rows = _build_result_view(snapshot, filter_idx)
            except Exception as error:
                logging.getLogger("radiomaster").exception("Could not filter station health results")
                call_after_safe(self, self._show_results_error, "filter", str(error))
                continue
            if generation == self._view_generation and not self._closed:
                call_after_safe(self, self._apply_result_view, generation, rows)

    def _apply_result_view(self, generation, rows) -> None:
        if self._closed or generation != self._view_generation:
            return
        ctrl = self._results_list
        selected_uuid = self._selected_uuid()
        same_order = (len(rows) == len(ctrl.rows)
                      and all(a[0] == b[0] for a, b in zip(rows, ctrl.rows)))
        ctrl.Freeze()
        try:
            if not same_order:
                ctrl.SetItemState(-1, 0, wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED)
            ctrl.rows = rows
            ctrl.SetItemCount(len(rows))
            if selected_uuid and not same_order:
                index = next((i for i, row in enumerate(rows) if row[0] == selected_uuid), None)
                if index is not None:
                    ctrl.Select(index)
                    ctrl.Focus(index)
                    ctrl.EnsureVisible(index)
            ctrl.Refresh()
        finally:
            ctrl.Thaw()
        if self._selected_uuid():
            self._on_result_selected(None)
        else:
            self._detail_text.ChangeValue("")
        self._update_button_states()

    def _save_worker(self) -> None:
        # Flush batches already accepted even if the dialog has been closed.
        while True:
            rows = self._save_jobs.get()
            try:
                if rows is None:
                    return
                self._db.record_health_results(rows)
            except Exception as error:
                logging.getLogger("radiomaster").exception("Could not save station health results")
                if not self._closed:
                    call_after_safe(self, self._show_results_error, "save", str(error))
            finally:
                self._save_jobs.task_done()

    def _show_results_error(self, action: str, detail: str) -> None:
        if self._closed or action in self._reported_errors:
            return
        self._reported_errors.add(action)
        wx.MessageBox(f"Could not {action} station health results.\n\n{detail}",
                      "Station Health Check", wx.OK | wx.ICON_ERROR, self)

    def _station_name(self, uuid: str) -> str:
        row = self._results.get(uuid, {})
        return row.get("_name") or row.get("name_hint") or uuid

    def _selected_uuid(self) -> str | None:
        idx = self._results_list.GetFirstSelected()
        if idx == wx.NOT_FOUND:
            return None
        rows = self._results_list.rows
        uuid = rows[idx][0] if 0 <= idx < len(rows) else None
        return uuid if uuid in self._results and uuid not in self._hidden_uuids else None

    def _on_result_selected(self, event) -> None:
        uuid = self._selected_uuid()
        if not uuid:
            self._detail_text.ChangeValue("")
            self._update_button_states()
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
        text = "\n".join(lines)
        if self._detail_text.GetValue() != text:
            self._detail_text.ChangeValue(text)
        self._update_button_states()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _update_button_states(self) -> None:
        running = self._service.running
        self._btn_start.Enable(not running)
        self._btn_stop.Enable(running)
        has_selection = self._selected_uuid() is not None
        self._btn_hide.Enable(has_selection and not self._hiding)
        self._btn_recheck.Enable(has_selection and not running)
        self._btn_play.Enable(has_selection)
        self._btn_hide_dead.Enable(not self._hiding and any(not row.get("stream_ok")
                                       for uuid, row in self._results.items()
                                       if uuid not in self._hidden_uuids))

    def _on_hide_selected(self, event: wx.CommandEvent) -> None:
        if self._hiding:
            return
        uuid = self._selected_uuid()
        if not uuid:
            return
        name = self._station_name(uuid)
        if wx.MessageBox(f"Hide '{name}' from all station lists?",
                         "Hide Station", wx.YES_NO | wx.ICON_QUESTION, self) != wx.YES:
            return
        self._hide_stations_async([uuid], _problem_label(self._results.get(uuid, {})))

    def _on_hide_all_dead(self, event: wx.CommandEvent) -> None:
        if self._hiding:
            return
        dead = [uuid for uuid, row in self._results.items()
                if not row.get("stream_ok") and uuid not in self._hidden_uuids]
        if not dead:
            return
        if wx.MessageBox(f"Hide all {len(dead)} stations with dead streams?",
                         "Hide Dead Stations", wx.YES_NO | wx.ICON_QUESTION, self) != wx.YES:
            return
        self._hide_stations_async(dead, "Dead stream")

    def _hide_stations_async(self, dead: list[str], reason: str) -> None:
        self._hiding = True
        self._update_button_states()
        # Batched off the UI thread: hiding hundreds of dead stations
        # one INSERT-per-call on the UI thread was itself a multi-second
        # stall (each call is its own transaction with a disk sync).
        def hide_all():
            try:
                self._db.hide_stations(dead, reason=reason)
            except Exception as error:
                call_after_safe(self, self._hide_failed, str(error))
            else:
                call_after_safe(self, self._after_hide_all, dead)

        threading.Thread(target=hide_all, name="health-hide-all").start()

    def _hide_failed(self, detail: str) -> None:
        if self._closed:
            return
        self._hiding = False
        self._update_button_states()
        self._show_results_error("hide", detail)

    def _after_hide_all(self, dead: list[str]) -> None:
        if self._closed:
            return
        self._hiding = False
        for uuid in dead:
            self._live_uuids.add(uuid)
            self._hidden_uuids.add(uuid)
            self._unhidden_uuids.discard(uuid)
        self._update_button_states()
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
        if self._closed:
            return
        row = result.to_row()
        row["_name"] = result.station_name
        self._live_uuids.add(result.uuid)
        self._save_jobs.put([row])
        if result.is_problem:
            self._results[result.uuid] = row
        else:
            self._results.pop(result.uuid, None)
        self._refresh_results()

    def _on_play_selected(self, event: wx.CommandEvent) -> None:
        uuid = self._selected_uuid()
        if not uuid:
            return
        parent = self.GetParent()

        # Catalog lookup off the UI thread: finding one station means
        # iterating the entire 50k+ catalog, which froze the dialog for
        # seconds on the UI thread.
        def find_and_play():
            station = None
            for s in self._db.all_stations(limit=200000):
                if s.uuid == uuid:
                    station = s
                    break
            if station is None:
                for s in self._db.get_custom_stations() + self._db.get_favorite_stations():
                    if s.uuid == uuid:
                        station = s
                        break
            if station is None:
                call_after_safe(self, lambda: wx.MessageBox(
                    "Could not find this station in the catalog.",
                    "Not Found", wx.OK | wx.ICON_WARNING, self))
                return
            if parent and hasattr(parent, "_radio_panel"):
                call_after_safe(self, self._play_found, station)

        threading.Thread(target=find_and_play, daemon=True,
                         name="health-play-lookup").start()

    def _play_found(self, station) -> None:
        parent = self.GetParent()
        self.EndModal(wx.ID_OK)
        wx.CallAfter(lambda: parent._radio_panel._play_station(station))

    def _on_manage_hidden(self, event: wx.CommandEvent) -> None:
        dlg = _HiddenStationsDialog(self, self._db)
        dlg.ShowModal()
        self._hidden_uuids.difference_update(dlg.unhidden_uuids)
        self._unhidden_uuids.update(dlg.unhidden_uuids)
        dlg.Destroy()
        # A station unhidden from there may reappear in results.
        self._refresh_results()


class _HiddenStationsDialog(wx.Dialog):
    """List of hidden stations with Unhide / Unhide All."""

    def __init__(self, parent: wx.Window, station_db: StationDB) -> None:
        super().__init__(parent, title="Hidden Stations", size=(520, 380))
        self._db = station_db
        self.unhidden_uuids: set[str] = set()
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
        self.unhidden_uuids.add(self._uuids[idx])
        self._refresh()

    def _on_unhide_all(self, event: wx.CommandEvent) -> None:
        count = self._db.unhide_all()
        self.unhidden_uuids.update(self._uuids)
        if count:
            wx.MessageBox(f"Unhid {count} stations.", "Done",
                          wx.OK | wx.ICON_INFORMATION, self)
        self._refresh()
