"""Continue Listening dialog: one list of unfinished things.

Borrowed from Quill Radio: rows read as sentences ("Podcast episode,
The Daily, 12 of 45 minutes"), Resume delegates to the owning panel's
existing play path, Forget This One zeroes the position without touching
the file, and the opening summary is spoken, never silent.
"""

from __future__ import annotations

import os
import subprocess
from typing import Callable, Optional

import wx

from radiomaster.services.continue_listening import (
    ContinueItem, ContinueListeningService,
)
from radiomaster.utils.accessibility import set_accessible_name


class ContinueListeningDialog(wx.Dialog):
    """Unfinished podcast episodes, audiobooks, and media files."""

    def __init__(self, parent, service: ContinueListeningService,
                 on_resume: Optional[Callable[[ContinueItem], None]] = None):
        super().__init__(parent, title="Continue Listening",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._service = service
        self._on_resume = on_resume

        sizer = wx.BoxSizer(wx.VERTICAL)
        self._items = service.items()
        summary = service.summary_sentence(self._items)

        self._summary = wx.StaticText(self, label=summary)
        set_accessible_name(self._summary, "Continue listening summary")
        sizer.Add(self._summary, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)

        self._list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self._list.InsertColumn(0, "Kind", width=120)
        self._list.InsertColumn(1, "Title", width=240)
        self._list.InsertColumn(2, "From", width=180)
        self._list.InsertColumn(3, "Position", width=140)
        set_accessible_name(self._list, "Things you did not finish")
        sizer.Add(self._list, 1, wx.EXPAND | wx.ALL, 10)

        close_btn = wx.Button(self, wx.ID_CLOSE)
        set_accessible_name(close_btn, "Close Continue Listening")
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE))
        sizer.Add(close_btn, 0, wx.ALIGN_RIGHT | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.SetSizerAndFit(sizer)
        self.SetSize(wx.Size(760, 420))

        self._populate()
        self._list.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)
        self._list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_activated)

    def _populate(self) -> None:
        self._list.DeleteAllItems()
        for offset, item in enumerate(self._items):
            index = self._list.InsertItem(offset, item.kind)
            self._list.SetItem(index, 1, item.title)
            self._list.SetItem(index, 2, item.parent)
            self._list.SetItem(index, 3,
                               self._service.describe_position(item.position,
                                                               item.duration))

    def _selected_item(self) -> Optional[ContinueItem]:
        idx = self._list.GetFirstSelected()
        if 0 <= idx < len(self._items):
            return self._items[idx]
        return None

    def _on_activated(self, event: wx.ListEvent) -> None:
        item = self._selected_item()
        if item is not None:
            self._resume(item)

    def _resume(self, item: ContinueItem) -> None:
        if self._on_resume:
            self._on_resume(item)
            self.EndModal(wx.ID_OK)

    def _on_context_menu(self, event: wx.ContextMenuEvent) -> None:
        item = self._selected_item()
        if item is None:
            return
        menu = wx.Menu()
        resume_item = menu.Append(wx.ID_ANY, "&Resume")
        forget_item = menu.Append(wx.ID_ANY, "&Forget This One")
        menu.AppendSeparator()
        folder_item = menu.Append(wx.ID_ANY, "Open Containing &Folder")
        folder_item.Enable(bool(item.file_path)
                           and os.path.exists(item.file_path))

        menu.Bind(wx.EVT_MENU, lambda e: self._resume(item), resume_item)

        def on_forget(_event):
            self._service.forget(item)
            self._items = self._service.items()
            self._summary.SetLabel(self._service.summary_sentence(self._items))
            self._populate()

        def on_folder(_event):
            # Explorer with the file selected -- the same affordance the
            # Downloads tab offers.
            try:
                subprocess.Popen(["explorer", "/select,", os.path.normpath(item.file_path)])
            except OSError:
                pass

        menu.Bind(wx.EVT_MENU, on_forget, forget_item)
        menu.Bind(wx.EVT_MENU, on_folder, folder_item)
        self.PopupMenu(menu)
        menu.Destroy()