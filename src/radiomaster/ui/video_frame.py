"""Separate video playback frame for YouTube and local video files."""

import wx
from typing import Any, Callable
from radiomaster.utils.accessibility import set_accessible_name


class VideoFrame(wx.Frame):
    """Resizable frame for video playback."""

    def __init__(self, parent: wx.Window | None, title: str = "Video Player") -> None:
        super().__init__(parent, title=title, size=(800, 600),
                         style=wx.DEFAULT_FRAME_STYLE | wx.FRAME_FLOAT_ON_PARENT)
        self._setup_ui()
        self._setup_accelerators()
        self._bind_events()

        self._on_fullscreen_cb: Callable[[], None] | None = None
        self._on_close_cb: Callable[[], None] | None = None

        self.Centre()

    def _setup_ui(self) -> None:
        """Create the video frame layout."""
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # Video display area (placeholder - FFplay handles its own window)
        self._video_panel = wx.Panel(self, style=wx.SUNKEN_BORDER)
        self._video_panel.SetBackgroundColour(wx.BLACK)
        set_accessible_name(self._video_panel, "Video Display")
        main_sizer.Add(self._video_panel, 1, wx.EXPAND)

        # Info bar
        info_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self._title_text = wx.StaticText(self, label="")
        set_accessible_name(self._title_text, "Video Title")
        info_sizer.Add(self._title_text, 1, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)

        self._time_text = wx.StaticText(self, label="00:00:00 / 00:00:00")
        set_accessible_name(self._time_text, "Video Time")
        info_sizer.Add(self._time_text, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
        main_sizer.Add(info_sizer, 0, wx.EXPAND)

        # Control bar
        ctrl_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self._btn_play = wx.Button(self, label="▶", size=(40, 30))
        set_accessible_name(self._btn_play, "Play")
        ctrl_sizer.Add(self._btn_play, 0, wx.RIGHT, 2)

        self._btn_stop = wx.Button(self, label="■", size=(40, 30))
        set_accessible_name(self._btn_stop, "Stop")
        ctrl_sizer.Add(self._btn_stop, 0, wx.RIGHT, 2)

        self._btn_fullscreen = wx.Button(self, label="⛶", size=(40, 30))
        set_accessible_name(self._btn_fullscreen, "Fullscreen")
        ctrl_sizer.Add(self._btn_fullscreen, 0, wx.RIGHT, 8)

        # Position slider
        self._position_slider = wx.Slider(self, value=0, minValue=0, maxValue=1000,
                                          size=(200, -1), style=wx.SL_HORIZONTAL)
        set_accessible_name(self._position_slider, "Position")
        ctrl_sizer.Add(self._position_slider, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)

        # Volume
        ctrl_sizer.Add(wx.StaticText(self, label="Vol:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._volume_slider = wx.Slider(self, value=80, minValue=0, maxValue=100,
                                        size=(80, -1), style=wx.SL_HORIZONTAL)
        set_accessible_name(self._volume_slider, "Volume")
        ctrl_sizer.Add(self._volume_slider, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)

        main_sizer.Add(ctrl_sizer, 0, wx.EXPAND | wx.ALL, 4)

        self.SetSizer(main_sizer)

    def _setup_accelerators(self) -> None:
        """Set up keyboard accelerators.

        Deliberately no bare Space entry: a wx.AcceleratorTable on the
        Frame intercepts Space globally, before it ever reaches a focused
        control -- so a focused button wouldn't activate on Space, and
        typing a space anywhere would be swallowed as a play/pause toggle.
        Play/Pause is already reachable via the transport button and the
        F11/Escape accelerators below.
        """
        entries = [
            (wx.ACCEL_NORMAL, wx.WXK_F11, wx.NewIdRef()),
            (wx.ACCEL_NORMAL, wx.WXK_ESCAPE, wx.NewIdRef()),
        ]
        self.SetAcceleratorTable(wx.AcceleratorTable(entries))

    def _bind_events(self) -> None:
        """Bind control events."""
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self._btn_play.Bind(wx.EVT_BUTTON, lambda e: self._toggle_play())
        self._btn_stop.Bind(wx.EVT_BUTTON, lambda e: self._on_stop())
        self._btn_fullscreen.Bind(wx.EVT_BUTTON, lambda e: self._toggle_fullscreen())

    def _on_close(self, event: wx.CloseEvent) -> None:
        """Handle frame close."""
        if self._on_close_cb:
            self._on_close_cb()
        self.Destroy()

    def _toggle_play(self) -> None:
        """Toggle play/pause."""
        if self._btn_play.GetLabel() == "▶":
            self._btn_play.SetLabel("⏸")
            set_accessible_name(self._btn_play, "Pause")
        else:
            self._btn_play.SetLabel("▶")
            set_accessible_name(self._btn_play, "Play")

    def _on_stop(self) -> None:
        """Stop playback."""
        self._btn_play.SetLabel("▶")
        set_accessible_name(self._btn_play, "Play")

    def _toggle_fullscreen(self) -> None:
        """Toggle fullscreen mode."""
        if self.IsFullScreen():
            self.ShowFullScreen(False)
            self._btn_fullscreen.SetLabel("⛶")
        else:
            self.ShowFullScreen(True)
            self._btn_fullscreen.SetLabel("⛶ Exit")

    def set_title(self, title: str) -> None:
        """Set the video title."""
        self._title_text.SetLabel(title)
        self.SetTitle(f"Video Player - {title}")

    def set_time(self, elapsed: float, total: float) -> None:
        """Set the time display."""
        from radiomaster.utils.helpers import format_time
        self._time_text.SetLabel(f"{format_time(elapsed)} / {format_time(total)}")
        if total > 0:
            self._position_slider.SetRange(0, int(total))
            self._position_slider.SetValue(int(elapsed))

    def on_fullscreen(self, cb: Callable[[], None]) -> None:
        self._on_fullscreen_cb = cb

    def on_close(self, cb: Callable[[], None]) -> None:
        self._on_close_cb = cb
