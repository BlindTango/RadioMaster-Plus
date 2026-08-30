"""Playlist widget for managing playlists and their items."""

import wx
from typing import Any, Callable
from radiomaster.database.connection import DatabaseManager
from radiomaster.database.repository import PlaylistRepository
from radiomaster.utils.accessibility import set_accessible_name


class PlaylistWidget(wx.Panel):
    """Widget for creating, managing, and playing playlists."""

    def __init__(self, parent: wx.Window, db: DatabaseManager) -> None:
        super().__init__(parent)
        self._db = db
        self._repo = PlaylistRepository(db)
        self._on_play_item_cb: Callable[[dict[str, Any]], None] | None = None
        self._setup_ui()
        self._load_playlists()

    def _setup_ui(self) -> None:
        """Create the playlist widget layout."""
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # Playlist selector
        selector_sizer = wx.BoxSizer(wx.HORIZONTAL)
        selector_sizer.Add(wx.StaticText(self, label="Playlist:"), 0, wx.ALIGN_CENTER_VERTICAL)

        self._playlist_choice = wx.Choice(self)
        set_accessible_name(self._playlist_choice, "Playlist Selector")
        selector_sizer.Add(self._playlist_choice, 1, wx.LEFT | wx.RIGHT, 4)

        self._btn_new = wx.Button(self, label="New...")
        set_accessible_name(self._btn_new, "New Playlist")
        selector_sizer.Add(self._btn_new, 0, wx.RIGHT, 4)

        self._btn_delete = wx.Button(self, label="Delete")
        set_accessible_name(self._btn_delete, "Delete Playlist")
        selector_sizer.Add(self._btn_delete, 0)

        main_sizer.Add(selector_sizer, 0, wx.EXPAND | wx.ALL, 4)

        # Playlist items
        self._item_list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        set_accessible_name(self._item_list, "Playlist Items")
        self._item_list.AppendColumn("#", width=40)
        self._item_list.AppendColumn("Title", width=250)
        self._item_list.AppendColumn("Duration", width=70)
        main_sizer.Add(self._item_list, 1, wx.EXPAND | wx.ALL, 4)

        # Controls
        ctrl_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self._btn_play = wx.Button(self, label="Play")
        set_accessible_name(self._btn_play, "Play Item")
        ctrl_sizer.Add(self._btn_play, 0, wx.RIGHT, 4)

        self._btn_remove = wx.Button(self, label="Remove")
        set_accessible_name(self._btn_remove, "Remove Item")
        ctrl_sizer.Add(self._btn_remove, 0, wx.RIGHT, 4)

        self._btn_clear = wx.Button(self, label="Clear")
        set_accessible_name(self._btn_clear, "Clear Playlist")
        ctrl_sizer.Add(self._btn_clear, 0, wx.RIGHT, 4)

        self._btn_shuffle = wx.Button(self, label="Shuffle")
        set_accessible_name(self._btn_shuffle, "Shuffle")
        ctrl_sizer.Add(self._btn_shuffle, 0)

        main_sizer.Add(ctrl_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 4)

        self.SetSizer(main_sizer)

        # Bind events
        self._playlist_choice.Bind(wx.EVT_CHOICE, self._on_playlist_select)
        self._btn_new.Bind(wx.EVT_BUTTON, self._on_new)
        self._btn_delete.Bind(wx.EVT_BUTTON, self._on_delete)
        self._btn_play.Bind(wx.EVT_BUTTON, self._on_play)
        self._btn_remove.Bind(wx.EVT_BUTTON, self._on_remove)
        self._btn_clear.Bind(wx.EVT_BUTTON, self._on_clear)
        self._btn_shuffle.Bind(wx.EVT_BUTTON, self._on_shuffle)
        self._item_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_play)

    def _load_playlists(self) -> None:
        """Load playlists into the choice control."""
        self._playlist_choice.Clear()
        playlists = self._repo.get_all()
        for p in playlists:
            self._playlist_choice.Append(p["name"], p["id"])
        if playlists:
            self._playlist_choice.SetSelection(0)
            self._load_items(playlists[0]["id"])

    def _load_items(self, playlist_id: int) -> None:
        """Load items for a playlist."""
        self._item_list.DeleteAllItems()
        items = self._repo.get_items(playlist_id)
        for i, item in enumerate(items):
            idx = self._item_list.AppendItem(str(i + 1))
            self._item_list.SetItem(idx, 1, item.get("title", ""))
            self._item_list.SetItem(idx, 2, self._format_duration(item.get("duration", 0)))

    def _format_duration(self, seconds: float) -> str:
        """Format duration for display."""
        if not seconds:
            return ""
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    def _on_playlist_select(self, event: wx.CommandEvent) -> None:
        """Handle playlist selection."""
        idx = self._playlist_choice.GetSelection()
        if idx != wx.NOT_FOUND:
            playlist_id = self._playlist_choice.GetClientData(idx)
            if playlist_id is not None:
                self._load_items(playlist_id)

    def _on_new(self, event: wx.CommandEvent) -> None:
        """Create a new playlist."""
        dlg = wx.TextEntryDialog(self, "Enter playlist name:", "New Playlist")
        if dlg.ShowModal() == wx.ID_OK:
            name = dlg.GetValue().strip()
            if name:
                self._repo.create(name)
                self._load_playlists()
        dlg.Destroy()

    def _on_delete(self, event: wx.CommandEvent) -> None:
        """Delete the selected playlist."""
        idx = self._playlist_choice.GetSelection()
        if idx != wx.NOT_FOUND:
            dlg = wx.MessageDialog(self, "Delete this playlist?", "Confirm",
                                   wx.YES_NO | wx.ICON_QUESTION)
            if dlg.ShowModal() == wx.ID_YES:
                playlist_id = self._playlist_choice.GetClientData(idx)
                if playlist_id is not None:
                    self._db.execute("DELETE FROM playlists WHERE id = ?", (playlist_id,))
                    self._db.commit()
                    self._load_playlists()
            dlg.Destroy()

    def _on_play(self, event: wx.Event) -> None:
        """Play the selected item."""
        idx = self._item_list.GetFirstSelected()
        if idx >= 0 and self._on_play_item_cb:
            playlist_idx = self._playlist_choice.GetSelection()
            if playlist_idx != wx.NOT_FOUND:
                playlist_id = self._playlist_choice.GetClientData(playlist_idx)
                if playlist_id is not None:
                    items = self._repo.get_items(playlist_id)
                    if idx < len(items):
                        self._on_play_item_cb(items[idx])

    def _on_remove(self, event: wx.CommandEvent) -> None:
        """Remove the selected item from the playlist."""
        idx = self._item_list.GetFirstSelected()
        if idx >= 0:
            self._item_list.DeleteItem(idx)

    def _on_clear(self, event: wx.CommandEvent) -> None:
        """Clear all items from the playlist."""
        self._item_list.DeleteAllItems()

    def _on_shuffle(self, event: wx.CommandEvent) -> None:
        """Shuffle the playlist items."""
        import random
        items = []
        for i in range(self._item_list.GetItemCount()):
            items.append({
                "title": self._item_list.GetItemText(i, 1),
                "duration": self._item_list.GetItemText(i, 2),
            })
        random.shuffle(items)
        self._item_list.DeleteAllItems()
        for i, item in enumerate(items):
            idx = self._item_list.AppendItem(str(i + 1))
            self._item_list.SetItem(idx, 1, item["title"])
            self._item_list.SetItem(idx, 2, item["duration"])

    def add_item(self, title: str, duration: float = 0.0) -> None:
        """Add an item to the current playlist."""
        idx = self._item_list.AppendItem(str(self._item_list.GetItemCount() + 1))
        self._item_list.SetItem(idx, 1, title)
        self._item_list.SetItem(idx, 2, self._format_duration(duration))

    def on_play_item(self, cb: Callable[[dict[str, Any]], None]) -> None:
        """Set callback for when an item is played."""
        self._on_play_item_cb = cb
