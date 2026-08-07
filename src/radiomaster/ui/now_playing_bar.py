"""Now Playing bar with transport controls, time display, and position slider."""

import wx
import os
from typing import Callable
from PIL import Image
from io import BytesIO
import requests

from radiomaster.utils.accessibility import set_accessible_name


class NowPlayingBar(wx.Panel):
    """Bottom bar showing current playback info and transport controls."""

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self._setup_ui()
        self._bind_events()

        self._on_play_cb: Callable[[], None] | None = None
        self._on_pause_cb: Callable[[], None] | None = None
        self._on_stop_cb: Callable[[], None] | None = None
        self._on_next_cb: Callable[[], None] | None = None
        self._on_prev_cb: Callable[[], None] | None = None
        self._on_first_cb: Callable[[], None] | None = None
        self._on_last_cb: Callable[[], None] | None = None
        self._on_ffwd_cb: Callable[[], None] | None = None
        self._on_rewind_cb: Callable[[], None] | None = None
        self._on_record_cb: Callable[[], None] | None = None
        self._on_mute_cb: Callable[[], None] | None = None
        self._on_seek_cb: Callable[[int], None] | None = None
        self._on_volume_cb: Callable[[float], None] | None = None
        self._on_rate_cb: Callable[[float], None] | None = None
        self._on_pan_cb: Callable[[float], None] | None = None

    def _setup_ui(self) -> None:
        """Create the now playing UI layout.

        Transport controls are placed FIRST so they are reachable via Tab
        immediately after navigating content (categories, stations, etc.).
        """
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # === Transport controls row (FIRST in tab order) ===
        # wx.WrapSizer instead of a plain horizontal BoxSizer: this row holds
        # 14 fixed-width controls (8 transport buttons + 3 label/slider pairs
        # + Effects/Record/Mute). On anything narrower than ~1000px — a
        # non-maximized window, a smaller monitor, high-DPI scaling — a plain
        # BoxSizer pushes the tail of the row (Pan slider, Effects, Record,
        # Mute) past the window's right edge, making them unreachable by
        # mouse, keyboard, and screen reader alike. WrapSizer wraps overflow
        # onto additional lines instead of clipping it off-window.
        controls_sizer = wx.WrapSizer(wx.HORIZONTAL)

        # These buttons show compact transport glyphs as their visible Label,
        # but wx.Window.SetName() does NOT change what a screen reader
        # announces for a native control (that follows the Label) \u2014 use
        # set_accessible_name() so NVDA reads "First Track" etc instead of
        # the raw glyph.
        self._btn_first = wx.Button(self, label="|\u25c0", size=(40, 30), id=wx.NewIdRef())
        set_accessible_name(self._btn_first, "First Track")
        controls_sizer.Add(self._btn_first, 0, wx.RIGHT, 2)

        self._btn_rewind = wx.Button(self, label="\u25c0\u25c0\u25c0", size=(40, 30), id=wx.NewIdRef())
        set_accessible_name(self._btn_rewind, "Rewind")
        controls_sizer.Add(self._btn_rewind, 0, wx.RIGHT, 2)

        self._btn_prev = wx.Button(self, label="\u25c0\u25c0", size=(40, 30), id=wx.NewIdRef())
        set_accessible_name(self._btn_prev, "Previous Track")
        controls_sizer.Add(self._btn_prev, 0, wx.RIGHT, 2)

        self._btn_play = wx.Button(self, label="\u25b6", size=(50, 30), id=wx.NewIdRef())
        set_accessible_name(self._btn_play, "Play")
        controls_sizer.Add(self._btn_play, 0, wx.RIGHT, 2)

        self._btn_stop = wx.Button(self, label="\u25a0", size=(40, 30), id=wx.NewIdRef())
        set_accessible_name(self._btn_stop, "Stop")
        controls_sizer.Add(self._btn_stop, 0, wx.RIGHT, 2)

        self._btn_next = wx.Button(self, label="\u25b6\u25b6", size=(40, 30), id=wx.NewIdRef())
        set_accessible_name(self._btn_next, "Next Track")
        controls_sizer.Add(self._btn_next, 0, wx.RIGHT, 2)

        self._btn_ffwd = wx.Button(self, label="\u25b6\u25b6\u25b6", size=(40, 30), id=wx.NewIdRef())
        set_accessible_name(self._btn_ffwd, "Fast Forward")
        controls_sizer.Add(self._btn_ffwd, 0, wx.RIGHT, 2)

        self._btn_last = wx.Button(self, label="\u25b6|", size=(40, 30), id=wx.NewIdRef())
        set_accessible_name(self._btn_last, "Last Track")
        controls_sizer.Add(self._btn_last, 0, wx.RIGHT, 8)

        # Volume
        controls_sizer.Add(wx.StaticText(self, label="Vol:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._volume_slider = wx.Slider(self, value=80, minValue=0, maxValue=100,
                                        size=(100, -1), style=wx.SL_HORIZONTAL)
        self._volume_slider.SetName("Volume")
        controls_sizer.Add(self._volume_slider, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)

        # Rate (playback speed)
        controls_sizer.Add(wx.StaticText(self, label="Rate:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        self._rate_slider = wx.Slider(self, value=100, minValue=50, maxValue=300,
                         size=(100, -1), style=wx.SL_HORIZONTAL)
        self._rate_slider.SetName("Rate")
        # Defaults to a ~30-unit (0.3x) step on arrow keys/PgUp/PgDn/track
        # clicks over this 50-300 range -- too coarse to find a comfortable
        # speed. 5 (0.05x) per arrow press, 10 (0.1x) per page/track click.
        self._rate_slider.SetLineSize(5)
        self._rate_slider.SetPageSize(10)
        controls_sizer.Add(self._rate_slider, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)

        # Pan (stereo balance)
        controls_sizer.Add(wx.StaticText(self, label="Pan:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        self._pan_slider = wx.Slider(self, value=0, minValue=-100, maxValue=100,
                         size=(100, -1), style=wx.SL_HORIZONTAL)
        self._pan_slider.SetName("Pan")
        controls_sizer.Add(self._pan_slider, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)

        # Record button
        self._btn_record = wx.Button(self, label="\u25cf Record Off", size=(60, 30), id=wx.NewIdRef())
        set_accessible_name(self._btn_record, "Record Off")
        controls_sizer.Add(self._btn_record, 0, wx.LEFT, 4)

        # Mute button
        self._btn_mute = wx.Button(self, label="\U0001F507 Mute Off", size=(60, 30), id=wx.NewIdRef())
        set_accessible_name(self._btn_mute, "Mute Off")
        controls_sizer.Add(self._btn_mute, 0, wx.LEFT, 4)

        main_sizer.Add(controls_sizer, 0, wx.EXPAND | wx.ALL, 4)

        # === Info row (SECOND) ===
        info_sizer = wx.BoxSizer(wx.HORIZONTAL)

        # Cover art
        self._cover_art = wx.StaticBitmap(self, size=(48, 48))
        info_sizer.Add(self._cover_art, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 4)

        # Station/Media edit box
        info_sizer.Add(wx.StaticText(self, label="Station/Media:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        self._station_text = wx.TextCtrl(self, style=wx.TE_READONLY, size=(200, -1))
        self._station_text.SetName("Station or Media")
        info_sizer.Add(self._station_text, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)

        # Track/Show edit box
        info_sizer.Add(wx.StaticText(self, label="Track/Show:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        self._track_text = wx.TextCtrl(self, style=wx.TE_READONLY, size=(200, -1))
        self._track_text.SetName("Track or Show")
        info_sizer.Add(self._track_text, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)

        # Time display
        self._time_label = wx.StaticText(self, label="00:00:00 / 00:00:00 / 00:00:00")
        info_sizer.Add(self._time_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 8)

        main_sizer.Add(info_sizer, 0, wx.EXPAND)

        # === Position slider (THIRD) ===
        self._position_slider = wx.Slider(self, value=0, minValue=0, maxValue=1000,
                                          style=wx.SL_HORIZONTAL | wx.SL_AUTOTICKS)
        self._position_slider.SetName("Playback Position")
        main_sizer.Add(self._position_slider, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 4)

        self.SetSizer(main_sizer)

    def _bind_events(self) -> None:
        """Bind control events."""
        # Note: buttons are keyboard-focusable by default; do not call
        # SetFocusFromKbd() here. That method grabs actual keyboard focus
        # immediately (not just tab-stop eligibility), so calling it on every
        # button in turn left the *last* one called (Mute) holding focus —
        # which wx.Panel.SetFocus() then restores to whenever focus enters
        # this bar via Tab, instead of landing on the first control.
        self._btn_first.Bind(wx.EVT_BUTTON, lambda e: self._on_first_cb() if self._on_first_cb else None)
        self._btn_rewind.Bind(wx.EVT_BUTTON, lambda e: self._on_rewind_cb() if self._on_rewind_cb else None)
        self._btn_prev.Bind(wx.EVT_BUTTON, lambda e: self._on_prev_cb() if self._on_prev_cb else None)
        self._btn_play.Bind(wx.EVT_BUTTON, self._on_play_pause)
        self._btn_stop.Bind(wx.EVT_BUTTON, lambda e: self._on_stop_cb() if self._on_stop_cb else None)
        self._btn_next.Bind(wx.EVT_BUTTON, lambda e: self._on_next_cb() if self._on_next_cb else None)
        self._btn_ffwd.Bind(wx.EVT_BUTTON, lambda e: self._on_ffwd_cb() if self._on_ffwd_cb else None)
        self._btn_last.Bind(wx.EVT_BUTTON, lambda e: self._on_last_cb() if self._on_last_cb else None)
        self._btn_record.Bind(wx.EVT_BUTTON, lambda e: self._on_record_cb() if self._on_record_cb else None)
        self._btn_mute.Bind(wx.EVT_BUTTON, lambda e: self._on_mute_cb() if self._on_mute_cb else None)
        self._position_slider.Bind(wx.EVT_SLIDER, self._on_slider_seek)
        self._volume_slider.Bind(wx.EVT_SLIDER, self._on_volume_change)
        self._rate_slider.Bind(wx.EVT_SLIDER, self._on_rate_change)
        self._pan_slider.Bind(wx.EVT_SLIDER, self._on_pan_change)

    def _on_play_pause(self, event: wx.CommandEvent) -> None:
        """Toggle play/pause.

        Delegates entirely to the play callback, which decides what to do
        from the engine's real current state. This used to branch on the
        button's own displayed label instead -- but the label is only a
        reflection of the last state notification, and it can go stale:
        e.g. engine.pause() silently no-ops if the engine is mid-reconnect
        (state briefly "buffering", not "playing"), leaving the label
        saying "pause" while nothing actually changed. The next click then
        read that stale label and did the wrong thing -- the button
        appeared permanently out of sync with actual playback.
        """
        if self._on_play_cb:
            self._on_play_cb()

    def _on_slider_seek(self, event: wx.CommandEvent) -> None:
        """Handle position slider change."""
        if self._on_seek_cb:
            self._on_seek_cb(self._position_slider.GetValue())

    def _on_volume_change(self, event: wx.CommandEvent) -> None:
        """Handle volume slider change."""
        if self._on_volume_cb:
            self._on_volume_cb(self._volume_slider.GetValue() / 100.0)
    
    def _on_rate_change(self, event: wx.CommandEvent) -> None:
        """Handle rate slider change (0.5x to 3.0x)."""
        if self._on_rate_cb:
            # Slider value 100 = 1.0x, map 50-300 to 0.5-3.0
            rate = self._rate_slider.GetValue() / 100.0
            self._on_rate_cb(rate)
    
    def _on_pan_change(self, event: wx.CommandEvent) -> None:
        """Handle pan slider change (-1.0 to 1.0)."""
        if self._on_pan_cb:
            pan = self._pan_slider.GetValue() / 100.0
            self._on_pan_cb(pan)

    def set_playing(self, is_playing: bool) -> None:
        """Update play/pause button state."""
        self._btn_play.SetLabel("⏸" if is_playing else "▶")
        set_accessible_name(self._btn_play, "Pause" if is_playing else "Play")

    def set_seekable(self, seekable: bool) -> None:
        """Enable/disable Fast Forward, Rewind, and the position slider --
        there's nothing to seek to on a live radio stream (no fixed
        timeline), so these are greyed out whenever the current content
        has no real duration."""
        self._btn_ffwd.Enable(seekable)
        self._btn_rewind.Enable(seekable)
        self._position_slider.Enable(seekable)

    def set_history_state(self, has_previous: bool, has_next: bool) -> None:
        """Enable/disable First/Previous and Next/Last based on whether
        there's anywhere for them to go in the current station history."""
        self._btn_first.Enable(has_previous)
        self._btn_prev.Enable(has_previous)
        self._btn_next.Enable(has_next)
        self._btn_last.Enable(has_next)

    def set_stoppable(self, stoppable: bool) -> None:
        """Enable/disable Stop -- nothing to stop when nothing is playing
        or paused (e.g. at launch, before anything's ever been played)."""
        self._btn_stop.Enable(stoppable)

    def set_station(self, text: str) -> None:
        """Set the station/media name."""
        self._station_text.SetValue(text)

    def set_track(self, text: str) -> None:
        """Set the track/show name."""
        self._track_text.SetValue(text)

    def set_time(self, elapsed: float, total: float) -> None:
        """Set the time display and position slider."""
        from radiomaster.utils.helpers import format_time
        remaining = total - elapsed if total > 0 else 0
        self._time_label.SetLabel(
            f"{format_time(elapsed)} / {format_time(total)} / {format_time(remaining)}"
        )
        if total > 0:
            self._position_slider.SetRange(0, int(total))
            self._position_slider.SetValue(int(elapsed))

    def set_volume(self, volume: float) -> None:
        """Set the volume slider position (0.0 to 1.0)."""
        self._volume_slider.SetValue(int(volume * 100))

    def set_rate(self, rate: float) -> None:
        """Set the rate slider position (0.5x to 3.0x)."""
        self._rate_slider.SetValue(int(rate * 100))

    def set_pan(self, pan: float) -> None:
        """Set the pan slider position (-1.0 to 1.0)."""
        self._pan_slider.SetValue(int(pan * 100))

    def set_cover_art(self, image_data: bytes | None = None, file_path: str | None = None) -> None:
        """Set the cover art image from raw bytes or a file path.

        Args:
            image_data: Raw image bytes (e.g. from a network fetch or mutagen).
            file_path: Local file path to an image.
        """
        try:
            if image_data:
                img = Image.open(BytesIO(image_data))
            elif file_path and os.path.isfile(file_path):
                img = Image.open(file_path)
            else:
                self._clear_cover_art()
                return

            img = img.convert("RGBA")
            img = img.resize((48, 48), Image.LANCZOS)

            # Convert PIL Image to wx.Bitmap
            width, height = img.size
            data = img.tobytes()
            wx_image = wx.Image(width, height)
            wx_image.SetData(data[:width * height * 3])
            wx_image.SetAlpha(data[width * height * 3:])
            self._cover_art.SetBitmap(wx.Bitmap(wx_image))
        except Exception:
            self._clear_cover_art()

    def _clear_cover_art(self) -> None:
        """Reset cover art to a blank placeholder."""
        self._cover_art.SetBitmap(wx.NullBitmap)

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

    def on_seek(self, cb: Callable[[int], None]) -> None:
        self._on_seek_cb = cb

    def on_volume(self, cb: Callable[[float], None]) -> None:
        self._on_volume_cb = cb
    
    def on_rate(self, cb: Callable[[float], None]) -> None:
        """Set callback for playback rate changes."""
        self._on_rate_cb = cb
    
    def on_pan(self, cb: Callable[[float], None]) -> None:
        """Set callback for pan changes."""
        self._on_pan_cb = cb

    def on_record(self, cb: Callable[[], None]) -> None:
        """Set callback for record toggle."""
        self._on_record_cb = cb

    def on_mute(self, cb: Callable[[], None]) -> None:
        """Set callback for mute toggle."""
        self._on_mute_cb = cb

    def set_recording(self, is_recording: bool) -> None:
        """Update record button state."""
        label = "\u25cf Recording On" if is_recording else "\u25cf Record Off"
        self._btn_record.SetLabel(label)
        set_accessible_name(self._btn_record, "Recording On" if is_recording else "Record Off")

    def set_muted(self, is_muted: bool) -> None:
        """Update mute button state."""
        label = "\U0001F507 Mute On" if is_muted else "\U0001F507 Mute Off"
        self._btn_mute.SetLabel(label)
        set_accessible_name(self._btn_mute, "Mute On" if is_muted else "Mute Off")
