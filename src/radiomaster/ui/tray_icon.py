"""System tray icon backing Settings > General's Minimize/Close to tray and
Show notifications options.

MainWindow owns the single instance, created lazily the first time the
window is actually hidden to the tray (not at startup) so nothing changes
for users who leave both settings off.
"""

import wx
import wx.adv


class TrayIcon(wx.adv.TaskBarIcon):
    def __init__(self, frame: wx.Frame) -> None:
        super().__init__()
        self._frame = frame
        icon = frame.GetIcon()
        if icon.IsOk():
            self.SetIcon(icon, frame.GetTitle() or "RadioMaster+")
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_DCLICK, self._on_restore)

    def CreatePopupMenu(self) -> wx.Menu:
        menu = wx.Menu()

        show_item = menu.Append(wx.ID_ANY, "&Show RadioMaster+")
        self.Bind(wx.EVT_MENU, self._on_restore, show_item)
        menu.AppendSeparator()

        play_pause_item = menu.Append(wx.ID_ANY, "&Play/Pause")
        self.Bind(wx.EVT_MENU, self._on_play_pause, play_pause_item)

        stop_item = menu.Append(wx.ID_ANY, "&Stop")
        self.Bind(wx.EVT_MENU, self._on_stop, stop_item)
        menu.AppendSeparator()

        exit_item = menu.Append(wx.ID_ANY, "E&xit")
        self.Bind(wx.EVT_MENU, self._on_exit, exit_item)
        return menu

    def _on_restore(self, event: wx.Event) -> None:
        self._frame.restore_from_tray()

    def _on_play_pause(self, event: wx.Event) -> None:
        self._frame._on_transport_play_pause()

    def _on_stop(self, event: wx.Event) -> None:
        self._frame._on_stop_accel()

    def _on_exit(self, event: wx.Event) -> None:
        self._frame.request_exit()
