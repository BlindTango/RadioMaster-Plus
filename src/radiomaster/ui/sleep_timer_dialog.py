"""Sleep Timer dialog for scheduling auto-stop of playback."""

import wx
from typing import Callable
from radiomaster.utils.accessibility import set_accessible_name


class SleepTimerDialog(wx.Dialog):
    """Dialog to configure and start/stop the sleep timer."""

    def __init__(self, parent: wx.Window,
                 on_start: Callable[[float, str], None],
                 on_stop: Callable[[], None],
                 is_active: bool = False,
                 remaining: float = 0.0) -> None:
        super().__init__(parent, title="Sleep Timer", size=(400, 300))
        self._on_start = on_start
        self._on_stop = on_stop
        self._is_active = is_active
        self._remaining = remaining
        self._setup_ui()
        self._update_state()

    def _setup_ui(self) -> None:
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Status
        self._status_label = wx.StaticText(self, label="Timer is not running")
        sizer.Add(self._status_label, 0, wx.ALL, 8)

        # Duration
        dur_sizer = wx.BoxSizer(wx.HORIZONTAL)
        dur_sizer.Add(wx.StaticText(self, label="Duration (minutes):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._duration_spin = wx.SpinCtrl(self, value="15", min=1, max=480)
        set_accessible_name(self._duration_spin, "Sleep Timer Duration")
        dur_sizer.Add(self._duration_spin, 0, wx.LEFT, 4)
        sizer.Add(dur_sizer, 0, wx.ALL, 8)

        # Mode
        mode_sizer = wx.BoxSizer(wx.HORIZONTAL)
        mode_sizer.Add(wx.StaticText(self, label="Mode:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._mode_choice = wx.Choice(self, choices=[
            "Countdown",
            "End of Track",
            "End of Playlist",
        ])
        self._mode_choice.SetSelection(0)
        set_accessible_name(self._mode_choice, "Sleep Timer Mode")
        mode_sizer.Add(self._mode_choice, 0, wx.LEFT, 4)
        sizer.Add(mode_sizer, 0, wx.ALL, 8)

        # Buttons
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self._btn_start = wx.Button(self, label="Start Timer")
        set_accessible_name(self._btn_start, "Start Sleep Timer")
        btn_sizer.Add(self._btn_start, 0, wx.RIGHT, 4)

        self._btn_stop = wx.Button(self, label="Stop Timer")
        set_accessible_name(self._btn_stop, "Stop Sleep Timer")
        btn_sizer.Add(self._btn_stop, 0, wx.RIGHT, 4)

        self._btn_close = wx.Button(self, label="Close")
        set_accessible_name(self._btn_close, "Close Sleep Timer")
        btn_sizer.Add(self._btn_close, 0)

        sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 8)

        self.SetSizer(sizer)

        self._btn_start.Bind(wx.EVT_BUTTON, self._on_start_click)
        self._btn_stop.Bind(wx.EVT_BUTTON, self._on_stop_click)
        self._btn_close.Bind(wx.EVT_BUTTON, lambda e: self.Close())
        # The Close button uses a plain custom ID rather than wx.ID_CANCEL,
        # so wx's automatic "Escape triggers Cancel" dialog behavior doesn't
        # apply here -- bind it explicitly so Escape still closes the dialog.
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)

    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.Close()
        else:
            event.Skip()

    def _update_state(self) -> None:
        if self._is_active:
            mins = int(self._remaining // 60)
            secs = int(self._remaining % 60)
            self._status_label.SetLabel(f"Timer running — {mins}:{secs:02d} remaining")
            self._btn_start.Disable()
            self._btn_stop.Enable()
            self._duration_spin.Disable()
            self._mode_choice.Disable()
        else:
            self._status_label.SetLabel("Timer is not running")
            self._btn_start.Enable()
            self._btn_stop.Disable()
            self._duration_spin.Enable()
            self._mode_choice.Enable()

    def _on_start_click(self, event: wx.CommandEvent) -> None:
        minutes = self._duration_spin.GetValue()
        mode_map = {0: "countdown", 1: "end_of_track", 2: "end_of_playlist"}
        mode = mode_map.get(self._mode_choice.GetSelection(), "countdown")
        self._on_start(float(minutes), mode)
        self._is_active = True
        self._remaining = minutes * 60.0
        self._update_state()

    def _on_stop_click(self, event: wx.CommandEvent) -> None:
        self._on_stop()
        self._is_active = False
        self._remaining = 0.0
        self._update_state()
