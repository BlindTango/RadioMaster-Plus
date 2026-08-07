"""Global search bar widget for searching across all content types."""

import wx
from typing import Any, Callable
from radiomaster.utils.accessibility import set_accessible_name, set_search_ctrl_accessible_name


class SearchBar(wx.Panel):
    """Search bar with scope selection for searching across content types."""

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent)
        self._on_search_cb: Callable[[str, str], None] | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Create the search bar layout."""
        sizer = wx.BoxSizer(wx.HORIZONTAL)

        # Search icon/label
        sizer.Add(wx.StaticText(self, label="Search:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)

        # Search input
        self._search_ctrl = wx.SearchCtrl(self, style=wx.TE_PROCESS_ENTER, size=(300, -1))
        set_search_ctrl_accessible_name(self._search_ctrl, "Global Search")
        self._search_ctrl.ShowSearchButton(True)
        self._search_ctrl.ShowCancelButton(True)
        sizer.Add(self._search_ctrl, 1, wx.RIGHT, 4)

        # Scope selector
        self._scope_choice = wx.Choice(self, choices=[
            "All", "Radio", "Podcasts", "YouTube", "Media", "Audiobooks"
        ])
        set_accessible_name(self._scope_choice, "Search Scope")
        self._scope_choice.SetSelection(0)
        sizer.Add(self._scope_choice, 0, wx.RIGHT, 4)

        # Search button
        self._btn_search = wx.Button(self, label="Go")
        set_accessible_name(self._btn_search, "Search")
        sizer.Add(self._btn_search, 0)

        self.SetSizer(sizer)

        # Bind events
        self._search_ctrl.Bind(wx.EVT_SEARCHCTRL_SEARCH_BTN, self._on_search)
        self._search_ctrl.Bind(wx.EVT_TEXT_ENTER, self._on_search)
        self._search_ctrl.Bind(wx.EVT_SEARCHCTRL_CANCEL_BTN, self._on_cancel)
        self._btn_search.Bind(wx.EVT_BUTTON, self._on_search)

    def _on_search(self, event: wx.Event) -> None:
        """Execute search."""
        query = self._search_ctrl.GetValue().strip()
        scope = self._scope_choice.GetStringSelection().lower()
        if query and self._on_search_cb:
            self._on_search_cb(query, scope)

    def _on_cancel(self, event: wx.Event) -> None:
        """Clear search."""
        self._search_ctrl.Clear()

    def on_search(self, cb: Callable[[str, str], None]) -> None:
        """Set the search callback."""
        self._on_search_cb = cb


    def set_query(self, query: str) -> None:
        """Set the search query programmatically."""
        self._search_ctrl.SetValue(query)

    def set_scope(self, scope: str) -> None:
        """Set the search scope."""
        idx = self._scope_choice.FindString(scope.capitalize())
        if idx != wx.NOT_FOUND:
            self._scope_choice.SetSelection(idx)
