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

        Remembers and restores the Active list's selection (by the
        download's real database id, not row position) across the
        rebuild -- the 3-second auto-refresh timer used to call this and
        wipe whatever was selected every single time via DeleteAllItems,
        so clicking "Stop Recording" (or anything else that needs a
        selection) almost always hit "Select a recording first" even
        though something genuinely was selected a moment before.
        """
        from radiomaster.database.repository import DownloadRepository
        repo = DownloadRepository(self._db)

        selected_idx = self._active_list.GetFirstSelected()
        selected_id = (
            self._active_rows[selected_idx]["id"]
            if selected_idx != wx.NOT_FOUND and selected_idx < len(self._active_rows)
            else None
        )

        # Active/queued downloads
        self._active_list.DeleteAllItems()
        self._active_rows = repo.get_queued()
        for d in self._active_rows:
            idx = self._active_list.InsertItem(self._active_list.GetItemCount(), d.get("title", "Unknown"))
            self._active_list.SetItem(idx, 1, f"{d.get('progress', 0):.0f}%")
            self._active_list.SetItem(idx, 2, d.get("status", "queued"))

        if selected_id is not None:
            for i, d in enumerate(self._active_rows):
                if d["id"] == selected_id:
                    self._active_list.Select(i)
                    break

        # History (completed/failed downloads)
        self._history_list.DeleteAllItems()
        all_downloads = self._db.fetchall(
            "SELECT * FROM downloads WHERE status IN ('completed', 'failed') ORDER BY id DESC LIMIT 50"
        )
        for d in all_downloads:
            idx = self._history_list.InsertItem(self._history_list.GetItemCount(), d.get("title", "Unknown"))
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
