"""Downloads tab panel showing active downloads and history."""

import wx
from typing import Any
from radiomaster.database.connection import DatabaseManager
from radiomaster.utils.accessibility import set_accessible_name


class DownloadsPanel(wx.Panel):
    """Panel for managing downloads."""

    def __init__(self, parent: wx.Window, db: DatabaseManager) -> None:
        super().__init__(parent)
        self._db = db
        self._setup_ui()
        self._load_data()

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
        """Load download data from the repository."""
        from radiomaster.database.repository import DownloadRepository
        repo = DownloadRepository(self._db)

        # Active/queued downloads
        self._active_list.DeleteAllItems()
        for d in repo.get_queued():
            idx = self._active_list.InsertItem(self._active_list.GetItemCount(), d.get("title", "Unknown"))
            self._active_list.SetItem(idx, 1, f"{d.get('progress', 0):.0f}%")
            self._active_list.SetItem(idx, 2, d.get("status", "queued"))

        # History (completed/failed downloads)
        self._history_list.DeleteAllItems()
        all_downloads = self._db.fetchall(
            "SELECT * FROM downloads WHERE status IN ('completed', 'failed') ORDER BY id DESC LIMIT 50"
        )
        for d in all_downloads:
            idx = self._history_list.InsertItem(self._history_list.GetItemCount(), d.get("title", "Unknown"))
            self._history_list.SetItem(idx, 1, d.get("created_at", ""))
            self._history_list.SetItem(idx, 2, d.get("status", ""))
