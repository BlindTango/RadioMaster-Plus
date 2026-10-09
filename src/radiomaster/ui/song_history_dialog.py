"""Song History dialog: what played, newest first, with row verbs.

Borrowed from Quill Radio's song history: the list reads as sentences
("Artist - Title, at 3:42 PM"), and the context menu carries Copy,
Identify with Track Identifier, and Search Lyrics -- the three things a
listener who just heard something interesting actually wants to do.
"""

from __future__ import annotations

import wx

from radiomaster.utils.accessibility import set_accessible_name


class SongHistoryDialog(wx.Dialog):
    """Recent songs for one station (or all stations), newest first."""

    def __init__(self, parent, song_history, station_uuid=None,
                 station_name=None, on_lyrics=None):
        title = (f"Song History - {station_name}" if station_name
                 else "Song History - All Stations")
        super().__init__(parent, title=title,
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._history = song_history
        self._station_uuid = station_uuid
        self._on_lyrics = on_lyrics

        sizer = wx.BoxSizer(wx.VERTICAL)

        self._all_stations = wx.CheckBox(self, label="All stations")
        set_accessible_name(self._all_stations, "Show history for all stations")
        self._all_stations.SetValue(station_uuid is None)
        sizer.Add(self._all_stations, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)

        self._list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self._list.InsertColumn(0, "Artist", width=200)
        self._list.InsertColumn(1, "Title", width=240)
        self._list.InsertColumn(2, "Station", width=160)
        self._list.InsertColumn(3, "Time", width=100)
        set_accessible_name(self._list, "Song history")
        sizer.Add(self._list, 1, wx.EXPAND | wx.ALL, 10)

        close_btn = wx.Button(self, wx.ID_CLOSE)
        set_accessible_name(close_btn, "Close Song History")
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE))
        sizer.Add(close_btn, 0, wx.ALIGN_RIGHT | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.SetSizerAndFit(sizer)
        self.SetSize(wx.Size(760, 420))

        self._all_stations.Bind(wx.EVT_CHECKBOX, lambda e: self._reload())
        self._list.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)
        self._reload()

    def _reload(self) -> None:
        """Refresh the list; the empty case gets its own sentence as the
        single row -- never a silent empty list."""
        station = None if self._all_stations.GetValue() else self._station_uuid
        rows = self._history.recent(station_uuid=station, limit=200)
        self._list.DeleteAllItems()
        self._rows = rows
        if not rows:
            index = self._list.InsertItem(0, "")
            self._list.SetItem(index, 0, "Nothing has been recorded yet.")
            return
        for offset, row in enumerate(rows):
            index = self._list.InsertItem(offset, row.get("artist", ""))
            self._list.SetItem(index, 1, row.get("title", ""))
            self._list.SetItem(index, 2, row.get("station_name", ""))
            self._list.SetItem(index, 3, row.get("spoken_time", ""))

    def _selected_row(self):
        idx = self._list.GetFirstSelected()
        if 0 <= idx < len(getattr(self, "_rows", [])):
            return self._rows[idx]
        return None

    def _on_context_menu(self, event: wx.ContextMenuEvent) -> None:
        row = self._selected_row()
        if row is None:
            return
        menu = wx.Menu()
        copy_item = menu.Append(wx.ID_ANY, "&Copy \"Artist - Title\"")
        lyrics_item = menu.Append(wx.ID_ANY, "Search &Lyrics...")

        def on_copy(_event):
            text = f"{row.get('artist', '')} - {row.get('title', '')}".strip(" -")
            if wx.TheClipboard.Open():
                wx.TheClipboard.SetData(wx.TextDataObject(text))
                wx.TheClipboard.Close()

        def on_lyrics(_event):
            # Delegate to MainWindow's lyrics flow via the parent chain;
            # it owns the lyrics service and the Lyrics tab.
            handler = self._on_lyrics
            if handler:
                self.EndModal(wx.ID_CLOSE)
                wx.CallAfter(handler, row.get("artist", ""), row.get("title", ""))

        try:
            selected = self._list.GetPopupMenuSelectionFromUser(menu)
            action = {copy_item.GetId(): on_copy, lyrics_item.GetId(): on_lyrics}.get(selected)
        finally:
            menu.Destroy()
        if action:
            action(None)
