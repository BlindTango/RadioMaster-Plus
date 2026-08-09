"""Downloads tab panel showing active downloads and history."""

import wx
from typing import Any, Callable, Optional
from radiomaster.database.connection import DatabaseManager
from radiomaster.utils.accessibility import set_accessible_name


class DownloadsPanel(wx.Panel):
    """Panel for managing downloads."""

    def __init__(self, parent: wx.Window, db: DatabaseManager) -> None:
        super().__init__(parent)
        self._db = db
        # Row dicts parallel to _active_list's items (same order), so
        # selecting a row can look up its real "downloads" table id and
        # source_type without needing a second DB round-trip.
        self._active_rows: list[dict[str, Any]] = []
        # Set by MainWindow to RadioPanel.stop_recording_by_download_id --
        # only source_type="radio_recording" rows can be stopped from
        # here (a real youtube/podcast download has no such handle).
        self.on_stop_recording: Optional[Callable[[int], bool]] = None
        self._setup_ui()
        self._load_data()

        # Progress/status only ever changed on disk (DownloadManager
        # callbacks writing to the DB) -- without polling, this panel
        # showed whatever status a download had at the moment it was
        # first viewed, forever, until Refresh was clicked by hand.
        self._refresh_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, lambda e: self._load_data(), self._refresh_timer)
        self._refresh_timer.Start(3000)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)

    def _on_destroy(self, event: wx.WindowDestroyEvent) -> None:
        if event.GetEventObject() is self:
            self._refresh_timer.Stop()
        event.Skip()

    def _setup_ui(self) -> None:
        """Create the downloads panel layout."""
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # Active downloads
        main_sizer.Add(wx.StaticText(self, label="Active Downloads"), 0, wx.ALL, 4)

        self._active_list = wx.ListCtrl(self, style=wx.LC_REPORT)
        set_accessible_name(self._active_list, "Active Downloads")
        self._active_list.AppendColumn("Title", width=250)
        self._active_list.AppendColumn("Progress", width=100)
        self._active_list.AppendColumn("Status", width=100)
        main_sizer.Add(self._active_list, 1, wx.EXPAND | wx.ALL, 4)

        active_btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self._btn_stop_recording = wx.Button(self, label="Stop &Recording")
        set_accessible_name(self._btn_stop_recording, "Stop Selected Recording")
        self._btn_stop_recording.Bind(wx.EVT_BUTTON, self._on_stop_recording)
        active_btn_sizer.Add(self._btn_stop_recording, 1, wx.RIGHT, 2)
        # A queued/downloading row that isn't a recording (a stuck
        # podcast/YouTube download, or one you just don't want anymore)
        # had no way to leave the Active list at all short of it finishing
        # or failing on its own.
        self._btn_remove = wx.Button(self, label="Re&move")
        set_accessible_name(self._btn_remove, "Remove Selected Download")
        self._btn_remove.Bind(wx.EVT_BUTTON, self._on_remove)
        active_btn_sizer.Add(self._btn_remove, 1, wx.LEFT, 2)
        main_sizer.Add(active_btn_sizer, 0, wx.EXPAND | wx.ALL, 4)

        # History
        main_sizer.Add(wx.StaticText(self, label="Download History"), 0, wx.ALL, 4)

        self._history_list = wx.ListCtrl(self, style=wx.LC_REPORT)
        set_accessible_name(self._history_list, "Download History")
        self._history_list.AppendColumn("Title", width=250)
        self._history_list.AppendColumn("Date", width=150)
        self._history_list.AppendColumn("Status", width=100)
        main_sizer.Add(self._history_list, 1, wx.EXPAND | wx.ALL, 4)

        # Refresh button
        self._btn_refresh = wx.Button(self, label="Refresh")
        set_accessible_name(self._btn_refresh, "Refresh Downloads")
        self._btn_refresh.Bind(wx.EVT_BUTTON, lambda e: self._load_data())
        main_sizer.Add(self._btn_refresh, 0, wx.ALIGN_CENTER | wx.ALL, 4)

        self.SetSizer(main_sizer)

    def _load_data(self) -> None:
        """Load download data from the repository.

        The 3-second auto-refresh timer used to blow away and rebuild
        BOTH lists from scratch (DeleteAllItems + reinsert everything)
        on every single tick, whether anything had actually changed or
        not -- almost always just a progress percentage ticking up.
        Restoring the selected row by id afterward (added previously)
        stopped the *button clicks* from failing, but the list itself
        still visibly tore down and rebuilt every 3 seconds, which is
        exactly what made it "constantly refreshing" and hard to work
        with for a screen reader user: rebuilding the whole list churns
        the accessibility tree even when the row you're on didn't move.
        It could also actually pick the wrong row if the active set
        reordered while re-selecting only by id and you acted on the
        list a beat later, which is exactly the "stop recording B, but
        Remove says recording A is still active" symptom.

        Now: if the exact same set of active download ids is present in
        the same order as last time, only that row's Progress/Status
        cells are updated in place via SetItem -- no delete/reinsert at
        all, so the list, focus, and selection are completely
        undisturbed. A full rebuild only happens when a row genuinely
        starts, finishes, or is removed -- an actual list change, not a
        cosmetic one.
        """
        from radiomaster.database.repository import DownloadRepository
        repo = DownloadRepository(self._db)

        new_rows = repo.get_queued()
        same_rows = (
            len(new_rows) == len(self._active_rows)
            and all(a["id"] == b["id"] for a, b in zip(new_rows, self._active_rows))
        )
        self._active_rows = new_rows
        if same_rows:
            for i, d in enumerate(new_rows):
                self._active_list.SetItem(i, 1, f"{d.get('progress', 0):.0f}%")
                self._active_list.SetItem(i, 2, d.get("status", "queued"))
        else:
            selected_idx = self._active_list.GetFirstSelected()
            selected_id = (
                self._active_list.GetItemData(selected_idx) if selected_idx != wx.NOT_FOUND else None
            )
            self._active_list.DeleteAllItems()
            for i, d in enumerate(new_rows):
                idx = self._active_list.InsertItem(i, d.get("title", "Unknown"))
                self._active_list.SetItemData(idx, d["id"])
                self._active_list.SetItem(idx, 1, f"{d.get('progress', 0):.0f}%")
                self._active_list.SetItem(idx, 2, d.get("status", "queued"))
            if selected_id is not None:
                for i, d in enumerate(new_rows):
                    if d["id"] == selected_id:
                        self._active_list.Select(i)
                        break

        # History (completed/failed downloads) -- refreshed the same
        # cautious way, though it changes far less often than progress.
        new_history = self._db.fetchall(
            "SELECT * FROM downloads WHERE status IN ('completed', 'failed') ORDER BY id DESC LIMIT 50"
        )
        history_same = (
            self._history_list.GetItemCount() == len(new_history)
            and all(
                self._history_list.GetItemData(i) == d["id"]
                for i, d in enumerate(new_history)
            )
        )
        if not history_same:
            self._history_list.DeleteAllItems()
            for i, d in enumerate(new_history):
                idx = self._history_list.InsertItem(i, d.get("title", "Unknown"))
                self._history_list.SetItemData(idx, d["id"])
                self._history_list.SetItem(idx, 1, d.get("created_at", ""))
                self._history_list.SetItem(idx, 2, d.get("status", ""))

    def _on_stop_recording(self, event: wx.CommandEvent) -> None:
        idx = self._active_list.GetFirstSelected()
        if idx == wx.NOT_FOUND or idx >= len(self._active_rows):
            wx.MessageBox("Select an active recording first.", "No Selection",
                          wx.OK | wx.ICON_INFORMATION)
            return
        row = self._active_rows[idx]
        if row.get("source_type") != "radio_recording":
            wx.MessageBox("Only manual radio recordings (not other downloads) can be "
                          "stopped from here.", "Not a Recording", wx.OK | wx.ICON_INFORMATION)
            return
        if self.on_stop_recording and self.on_stop_recording(row["id"]):
            self._load_data()
        else:
            wx.MessageBox("That recording is no longer active.", "Already Stopped",
                          wx.OK | wx.ICON_INFORMATION)
            self._load_data()

    def _on_remove(self, event: wx.CommandEvent) -> None:
        idx = self._active_list.GetFirstSelected()
        if idx == wx.NOT_FOUND or idx >= len(self._active_rows):
            wx.MessageBox("Select a download first.", "No Selection",
                          wx.OK | wx.ICON_INFORMATION)
            return
        row = self._active_rows[idx]
        if row.get("source_type") == "radio_recording":
            wx.MessageBox("This is an active recording -- use Stop Recording instead "
                          "of Remove so the file it's already written gets finalized "
                          "properly.", "Active Recording", wx.OK | wx.ICON_INFORMATION)
            return
        if wx.MessageBox(
            f"Remove '{row.get('title', 'this download')}' from the queue? "
            "If it's genuinely in progress, this only removes the row -- it doesn't "
            "cancel the actual download running in the background.",
            "Remove Download", wx.YES_NO | wx.ICON_QUESTION,
        ) != wx.YES:
            return
        from radiomaster.database.repository import DownloadRepository
        DownloadRepository(self._db).delete(row["id"])
        self._load_data()
