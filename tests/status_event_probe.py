"""Run native event-loop checks in a fresh wx process, isolated from app fixtures."""
import wx
from radiomaster.ui.status_bar import StatusBar


def check_events():
    import ctypes
    from ctypes import wintypes
    import time
    import win32gui

    app = wx.App.Get() or wx.App(False)
    frame = wx.Frame(None)
    bar = StatusBar(frame)
    frame.SetStatusBar(bar)
    frame.Show()
    wx.Yield()
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(
        None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND,
        wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD,
    )
    events = []
    handle = bar.GetHandle()

    def capture(hook, event, hwnd, obj, child, thread, timestamp):
        if hwnd == handle:
            events.append((event, obj, child))

    callback = callback_type(capture)
    user32.SetWinEventHook.argtypes = [
        wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE, callback_type,
        wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
    ]
    user32.SetWinEventHook.restype = wintypes.HANDLE
    user32.UnhookWinEvent.argtypes = [wintypes.HANDLE]
    hook = user32.SetWinEventHook(0x800C, 0x800E, None, callback, 0, 0, 0)
    try:
        assert hook
        for index in range(100):
            bar.set_time_info(index, 120)
            bar.set_buffering(index)
            bar.set_source(f"Source {index}")
            bar.set_format(f"Format {index}")
            bar.set_status(f"Progress {index}")
        time.sleep(.15)
        win32gui.PumpWaitingMessages()
        wx.Yield()
        assert events == []
        assert "Elapsed 1:39" in bar._accessible.GetName(3)[1]
        assert bar._accessible.GetName(5) == (wx.ACC_OK, "Format 99")
        # Underlying native fields must stay blank: writing here recreates the flood.
        assert all(wx.StatusBar.GetStatusText(bar, i) == "" for i in range(5))
    finally:
        if hook:
            user32.UnhookWinEvent(hook)
        frame.Destroy()
        app.ProcessPendingEvents()


if __name__ == "__main__":
    check_events()
