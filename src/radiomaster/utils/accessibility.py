"""Helpers for giving controls a screen-reader name distinct from their label."""

from __future__ import annotations

import wx


class _NamedAccessible(wx.Accessible):
    def __init__(self, window: wx.Window, name: str) -> None:
        super().__init__(window)
        self._name = name

    def GetName(self, childId):
        return (wx.ACC_OK, self._name)

    def set_name(self, name: str) -> None:
        self._name = name


# wx.Window.SetAccessible() does not take a reference-counted hold on the
# Python object it's given, so without keeping one alive somewhere, a
# _NamedAccessible can be garbage-collected the moment set_accessible_name()
# returns, leaving the C++ side pointing at freed memory (undefined
# behavior, not a clean failure -- intermittently "worked" depending on
# whether that freed memory happened to be overwritten yet). Storing it as
# an attribute on `window` itself doesn't reliably fix this: wx.Window
# objects obtained via GetChildren() are transient per-call Python wrapper
# objects around the same underlying C++ window (confirmed via id() --
# each GetChildren() call can mint a new wrapper), so an attribute set on
# one wrapper is invisible on the next. A plain module-level list, keyed by
# nothing in particular (never popped -- these live for the app's runtime
# anyway, same as the widgets they name), sidesteps wrapper identity
# entirely.
_KEEPALIVE: list[wx.Accessible] = []


def set_accessible_name(window: wx.Window, name: str) -> _NamedAccessible:
    """Set the name a screen reader announces for *window*.

    wx.Window.SetName() only sets wx's internal window name (used for
    FindWindowByName) — it does NOT change the MSAA/UIA Name that NVDA and
    other screen readers actually read. For native controls that Name comes
    from the control's own Label/window text (or an adjacent StaticText),
    so e.g. a button whose visible label is a glyph like "▶" keeps
    announcing that glyph no matter what SetName() is given. Overriding via
    wx.Accessible is what's actually required to change it.
    """
    accessible = _NamedAccessible(window, name)
    window.SetAccessible(accessible)
    _KEEPALIVE.append(accessible)  # see _KEEPALIVE's comment above
    window.SetName(name)
    return accessible


def context_menu_pos(ctrl: wx.Window, event: wx.ContextMenuEvent) -> wx.Point:
    """Client-coordinate position to pass to ctrl.PopupMenu() for an
    EVT_CONTEXT_MENU event.

    wx already fires EVT_CONTEXT_MENU for a right-click, the Menu/
    Applications key, AND Shift+F10 -- no separate keyboard handling is
    needed for those. The one thing that differs is position: a real
    right-click gives real screen coordinates via event.GetPosition(), but
    the keyboard-triggered cases have no mouse location at all and report
    wx.DefaultPosition -- falling back to the selected row's own position
    (or the control's top-left) keeps the menu from popping up at (0, 0)
    on the whole screen when triggered from the keyboard.
    """
    pos = event.GetPosition()
    if pos != wx.DefaultPosition:
        return ctrl.ScreenToClient(pos)
    if isinstance(ctrl, wx.ListCtrl):
        row = ctrl.GetFirstSelected()
        if row != -1:
            rect = ctrl.GetItemRect(row)
            return wx.Point(rect.x + rect.width // 3, rect.y + rect.height // 2)
    return wx.Point(10, 10)


def set_search_ctrl_accessible_name(search_ctrl: wx.SearchCtrl, name: str) -> None:
    """Set the announced name for a wx.SearchCtrl.

    wx.SearchCtrl is a composite: on MSW it's a container window plus a
    native child TextCtrl (the part that actually gets keyboard focus and
    is what NVDA reads) plus button children for the search-icon/clear
    "x". set_accessible_name() on the SearchCtrl itself only names the
    outer container -- Tabbing in still lands on the unnamed inner
    TextCtrl, which is what a screen reader actually announces. Name both.
    """
    set_accessible_name(search_ctrl, name)
    for child in search_ctrl.GetChildren():
        if isinstance(child, wx.TextCtrl):
            set_accessible_name(child, name)
            break
