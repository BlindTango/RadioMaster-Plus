"""Helpers for giving controls a screen-reader name distinct from their label."""

from __future__ import annotations

import wx


class _NamedAccessible(wx.Accessible):
    def __init__(self, window: wx.Window, name: str) -> None:
        super().__init__(window)
        self._name = name

    def GetName(self, childId):
        return (wx.ACC_OK, self._name)


def set_accessible_name(window: wx.Window, name: str) -> None:
    """Set the name a screen reader announces for *window*.

    wx.Window.SetName() only sets wx's internal window name (used for
    FindWindowByName) — it does NOT change the MSAA/UIA Name that NVDA and
    other screen readers actually read. For native controls that Name comes
    from the control's own Label/window text (or an adjacent StaticText),
    so e.g. a button whose visible label is a glyph like "▶" keeps
    announcing that glyph no matter what SetName() is given. Overriding via
    wx.Accessible is what's actually required to change it.
    """
    window.SetAccessible(_NamedAccessible(window, name))
    window.SetName(name)
