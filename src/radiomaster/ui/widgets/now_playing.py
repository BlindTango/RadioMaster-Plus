"""Read-only station name / now-playing text fields."""

from __future__ import annotations

import wx


class ReadOnlyFocusableTextCtrl(wx.TextCtrl):
    """A TE_READONLY wx.TextCtrl is focusable via mouse/SetFocus() but wx
    excludes it from Tab-key navigation by default. Override so screen
    reader users can Tab to it and use arrow keys to read its content."""

    def AcceptsFocusFromKeyboard(self) -> bool:
        return True


class NowPlayingPanel(wx.Panel):
    def __init__(self, parent):
        super().__init__(parent)

        station_label = wx.StaticText(self, label="Station:")
        self.station_field = ReadOnlyFocusableTextCtrl(self, style=wx.TE_READONLY)

        now_label = wx.StaticText(self, label="Now Playing:")
        self.now_playing_field = ReadOnlyFocusableTextCtrl(self, style=wx.TE_READONLY)

        grid = wx.FlexGridSizer(2, 2, 4, 8)
        grid.AddGrowableCol(1, 1)
        grid.Add(station_label, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.station_field, 1, wx.EXPAND)
        grid.Add(now_label, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.now_playing_field, 1, wx.EXPAND)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(grid, 1, wx.EXPAND | wx.ALL, 4)
        self.SetSizer(outer)

    def set_station(self, name: str) -> None:
        self.station_field.ChangeValue(name)

    def set_now_playing(self, text: str) -> None:
        self.now_playing_field.ChangeValue(text)
