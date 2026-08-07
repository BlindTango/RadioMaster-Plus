"""Standalone playback controls panel.

Provides explicit buttons for play, pause, stop, next, previous, first and last
track, as well as sliders for volume, playback rate and pan. The panel mirrors
the functionality already present in :class:`NowPlayingBar` but is placed in a
more visible location (above the tab list) so users can see the controls
immediately when the application starts.
"""

import wx
from typing import Callable


class PlaybackControlsPanel(wx.Panel):
    """Panel containing playback control widgets.

    The panel does **not** perform any playback itself – it simply forwards
    user interactions via callbacks that can be bound to a :class:`PlaybackEngine`
    instance.
    """

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self._on_play_cb: Callable[[], None] | None = None
        self._on_pause_cb: Callable[[], None] | None = None
        self._on_stop_cb: Callable[[], None] | None = None
        self._on_next_cb: Callable[[], None] | None = None
        self._on_prev_cb: Callable[[], None] | None = None
        self._on_first_cb: Callable[[], None] | None = None
        self._on_last_cb: Callable[[], None] | None = None
        self._on_ffwd_cb: Callable[[], None] | None = None
        self._on_rewind_cb: Callable[[], None] | None = None
        self._on_volume_cb: Callable[[float], None] | None = None
        self._on_rate_cb: Callable[[float], None] | None = None
        self._on_pan_cb: Callable[[float], None] | None = None

        self._setup_ui()
        self._bind_events()

    # ---------------------------------------------------------------------
    # UI construction
    # ---------------------------------------------------------------------
    def _setup_ui(self) -> None:
        main_sizer = wx.BoxSizer(wx.HORIZONTAL)

        # Transport buttons
        self._btn_first = wx.Button(self, label="|◀", id=wx.NewIdRef())
        self._btn_first.SetName("First Track")
        self._btn_prev = wx.Button(self, label="◀◀", id=wx.NewIdRef())
        self._btn_prev.SetName("Previous Track")
        self._btn_play = wx.Button(self, label="▶", id=wx.NewIdRef())
        self._btn_play.SetName("Play")
        self._btn_pause = wx.Button(self, label="⏸", id=wx.NewIdRef())
        self._btn_pause.SetName("Pause")
        self._btn_stop = wx.Button(self, label="■", id=wx.NewIdRef())
        self._btn_stop.SetName("Stop")
        self._btn_rewind = wx.Button(self, label="◀◀◀", id=wx.NewIdRef())
        self._btn_rewind.SetName("Rewind")
        self._btn_ffwd = wx.Button(self, label="▶▶▶", id=wx.NewIdRef())
        self._btn_ffwd.SetName("Fast Forward")
        self._btn_next = wx.Button(self, label="▶▶", id=wx.NewIdRef())
        self._btn_next.SetName("Next Track")
        self._btn_last = wx.Button(self, label="▶|", id=wx.NewIdRef())
        self._btn_last.SetName("Last Track")

        for btn in (
            self._btn_first,
            self._btn_prev,
            self._btn_play,
            self._btn_pause,
            self._btn_stop,
            self._btn_rewind,
            self._btn_ffwd,
            self._btn_next,
            self._btn_last,
        ):
            # Ensure the button can receive focus via Tab navigation
            btn.SetFocusFromKbd()
            main_sizer.Add(btn, 0, wx.RIGHT, 2)

        # Volume slider
        main_sizer.Add(wx.StaticText(self, label="Vol:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        self._volume_slider = wx.Slider(self, value=80, minValue=0, maxValue=100, style=wx.SL_HORIZONTAL)
        self._volume_slider.SetName("Volume")
        main_sizer.Add(self._volume_slider, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)

        # Rate slider
        main_sizer.Add(wx.StaticText(self, label="Rate:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        self._rate_slider = wx.Slider(self, value=100, minValue=50, maxValue=300, style=wx.SL_HORIZONTAL)
        self._rate_slider.SetName("Playback Rate")
        main_sizer.Add(self._rate_slider, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)

        # Pan slider
        main_sizer.Add(wx.StaticText(self, label="Pan:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        self._pan_slider = wx.Slider(self, value=0, minValue=-100, maxValue=100, style=wx.SL_HORIZONTAL)
        self._pan_slider.SetName("Stereo Pan")
        main_sizer.Add(self._pan_slider, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)

        self.SetSizer(main_sizer)

    # ---------------------------------------------------------------------
    # Event binding
    # ---------------------------------------------------------------------
    def _bind_events(self) -> None:
        self._btn_play.Bind(wx.EVT_BUTTON, lambda e: self._on_play_cb() if self._on_play_cb else None)
        self._btn_pause.Bind(wx.EVT_BUTTON, lambda e: self._on_pause_cb() if self._on_pause_cb else None)
        self._btn_stop.Bind(wx.EVT_BUTTON, lambda e: self._on_stop_cb() if self._on_stop_cb else None)
        self._btn_rewind.Bind(wx.EVT_BUTTON, lambda e: self._on_rewind_cb() if self._on_rewind_cb else None)
        self._btn_ffwd.Bind(wx.EVT_BUTTON, lambda e: self._on_ffwd_cb() if self._on_ffwd_cb else None)
        self._btn_next.Bind(wx.EVT_BUTTON, lambda e: self._on_next_cb() if self._on_next_cb else None)
        self._btn_prev.Bind(wx.EVT_BUTTON, lambda e: self._on_prev_cb() if self._on_prev_cb else None)
        self._btn_first.Bind(wx.EVT_BUTTON, lambda e: self._on_first_cb() if self._on_first_cb else None)
        self._btn_last.Bind(wx.EVT_BUTTON, lambda e: self._on_last_cb() if self._on_last_cb else None)
        self._volume_slider.Bind(wx.EVT_SLIDER, self._on_volume_change)
        self._rate_slider.Bind(wx.EVT_SLIDER, self._on_rate_change)
        self._pan_slider.Bind(wx.EVT_SLIDER, self._on_pan_change)

    # ---------------------------------------------------------------------
    # Slider handlers
    # ---------------------------------------------------------------------
    def _on_volume_change(self, event: wx.CommandEvent) -> None:
        if self._on_volume_cb:
            self._on_volume_cb(self._volume_slider.GetValue() / 100.0)

    def _on_rate_change(self, event: wx.CommandEvent) -> None:
        if self._on_rate_cb:
            self._on_rate_cb(self._rate_slider.GetValue() / 100.0)

    def _on_pan_change(self, event: wx.CommandEvent) -> None:
        if self._on_pan_cb:
            self._on_pan_cb(self._pan_slider.GetValue() / 100.0)

    # ---------------------------------------------------------------------
    # Callback setters
    # ---------------------------------------------------------------------
    def on_play(self, cb: Callable[[], None]) -> None:
        self._on_play_cb = cb

    def on_pause(self, cb: Callable[[], None]) -> None:
        self._on_pause_cb = cb

    def on_stop(self, cb: Callable[[], None]) -> None:
        self._on_stop_cb = cb

    def on_next(self, cb: Callable[[], None]) -> None:
        self._on_next_cb = cb

    def on_prev(self, cb: Callable[[], None]) -> None:
        self._on_prev_cb = cb

    def on_first(self, cb: Callable[[], None]) -> None:
        self._on_first_cb = cb

    def on_last(self, cb: Callable[[], None]) -> None:
        self._on_last_cb = cb

    def on_ffwd(self, cb: Callable[[], None]) -> None:
        """Set callback for fast forward."""
        self._on_ffwd_cb = cb

    def on_rewind(self, cb: Callable[[], None]) -> None:
        """Set callback for rewind."""
        self._on_rewind_cb = cb

    def on_volume(self, cb: Callable[[float], None]) -> None:
        self._on_volume_cb = cb

    def on_rate(self, cb: Callable[[float], None]) -> None:
        self._on_rate_cb = cb

    def on_pan(self, cb: Callable[[float], None]) -> None:
        self._on_pan_cb = cb
