"""wx.CallAfter that survives its target window being destroyed first.

Worker threads (downloads, network checks, playback monitors) post UI
updates via wx.CallAfter -- but those threads keep running (however
briefly) through app shutdown, and wx.CallAfter just queues the call for
whenever the main thread's event loop next processes it. If the window's
Destroy() cascade already ran by the time a queued call is processed, the
target widget's underlying C++ object is gone even though the Python
wrapper object is still alive (still referenced by the closure) -- calling
any method on it is a use-after-free.

`window` should be the widget that owns/produces the callback (or any
ancestor of every widget the callback touches) -- `bool(window)` on a wx
object reflects whether its C++ peer still exists, unlike a plain Python
truthiness check.
"""

from __future__ import annotations

from typing import Callable

import wx


def call_after_safe(window: wx.Window, func: Callable, *args) -> None:
    def run():
        if window:
            func(*args)
    wx.CallAfter(run)
