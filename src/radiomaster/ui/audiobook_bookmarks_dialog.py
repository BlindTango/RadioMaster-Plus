"""List of the current audiobook's bookmarks with Go To and Delete."""

from __future__ import annotations

from typing import Any, Callable

import wx

from radiomaster.utils.accessibility import set_accessible_name


def format_position(seconds: float) -> str:
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class AudiobookBookmarksDialog(wx.Dialog):
    """Shows bookmarks; ``on_goto(bookmark)`` is called for Go To, and
    ``on_delete(bookmark_id)`` for Delete."""

    def __init__(self, parent: wx.Window, bookmarks: list[dict[str, Any]],
                 on_goto: Callable[[dict[str, Any]], None],
                 on_delete: Callable[[int], None]) -> None:
        super().__init__(parent, title="Audiobook Bookmarks",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._bookmarks = list(bookmarks)
        self._on_goto = on_goto
        self._on_delete = on_delete

        sizer = wx.BoxSizer(wx.VERTICAL)
        label = wx.StaticText(self, label="Bookmarks:")
        sizer.Add(label, 0, wx.ALL, 8)
        self._list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self._list.InsertColumn(0, "Chapter", width=280)
        self._list.InsertColumn(1, "Position", width=100)
        set_accessible_name(self._list, "Bookmarks")
        sizer.Add(self._list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        btns = wx.BoxSizer(wx.HORIZONTAL)
        self._goto_btn = wx.Button(self, label="&Go To")
        self._delete_btn = wx.Button(self, wx.ID_ANY, "&Delete")
        close_btn = wx.Button(self, wx.ID_CANCEL, "&Close")
        for b in (self._goto_btn, self._delete_btn, close_btn):
            btns.Add(b, 0, wx.RIGHT, 6)
        sizer.Add(btns, 0, wx.ALL, 8)
        self.SetSizerAndFit(sizer)
        self.SetMinSize((480, 320))
        self.SetEscapeId(wx.ID_CANCEL)

        self._goto_btn.Bind(wx.EVT_BUTTON, self._on_goto_click)
        self._delete_btn.Bind(wx.EVT_BUTTON, self._on_delete_click)
        self._list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_goto_click)
        self._fill()

    def _fill(self, select: int = 0) -> None:
        self._list.DeleteAllItems()
        for i, bm in enumerate(self._bookmarks):
            self._list.InsertItem(i, bm.get("title") or "Bookmark")
            self._list.SetItem(i, 1, format_position(bm.get("position") or 0))
        has = bool(self._bookmarks)
        self._goto_btn.Enable(has)
        self._delete_btn.Enable(has)
        if has:
            select = min(select, len(self._bookmarks) - 1)
            self._list.Select(select)
            self._list.Focus(select)
        self._list.SetFocus()

    def _selected(self) -> int:
        return self._list.GetFirstSelected()

    def _on_goto_click(self, event: wx.CommandEvent) -> None:
        idx = self._selected()
        if idx < 0:
            return
        self._on_goto(self._bookmarks[idx])
        self.EndModal(wx.ID_OK)

    def _on_delete_click(self, event: wx.CommandEvent) -> None:
        idx = self._selected()
        if idx < 0:
            return
        bm = self._bookmarks.pop(idx)
        self._on_delete(bm["id"])
        self._fill(idx)
