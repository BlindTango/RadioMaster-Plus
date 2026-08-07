"""Play/Pause, Stop, Record, Mute, Volume row with accessible toggling labels."""

from __future__ import annotations

from typing import Callable, Optional

import wx


class PlayerControls(wx.Panel):
    def __init__(self, parent):
        super().__init__(parent)

        self.play_btn = wx.Button(self, label="\u25b6 Play")
        self.play_btn.SetName("Play")
        self.play_btn.SetToolTip("Play or pause the selected station")
        self.stop_btn = wx.Button(self, label="\u23f9 Stop")
        self.stop_btn.SetName("Stop")
        self.stop_btn.SetToolTip("Stop playback")
        self.record_btn = wx.Button(self, label="\u25cf Record Off")
        self.record_btn.SetName("Record Off")
        self.record_btn.SetToolTip("Toggle recording of the current stream")
        self.mute_btn = wx.Button(self, label="\U0001F507 Mute Off")
        self.mute_btn.SetName("Mute Off")
        self.mute_btn.SetToolTip("Toggle mute")

        self.volume_label = wx.StaticText(self, label="Volume:")
        self.volume_slider = wx.Slider(self, value=100, minValue=0, maxValue=100,
                                        style=wx.SL_HORIZONTAL)
        self.volume_slider.SetName("Volume")
        self.volume_slider.SetToolTip("Playback volume")
        self.volume_value_label = wx.StaticText(self, label="100%")

        self.pan_label = wx.StaticText(self, label="Pan:")
        self.pan_slider = wx.Slider(self, value=50, minValue=0, maxValue=100,
                                     style=wx.SL_HORIZONTAL)
        self.pan_slider.SetName("Pan")
        self.pan_slider.SetToolTip("Stereo pan — 0% full left, 50% centre, 100% full right")
        self.pan_value_label = wx.StaticText(self, label="50%")

        button_row = wx.BoxSizer(wx.HORIZONTAL)
        for btn in (self.play_btn, self.stop_btn, self.record_btn, self.mute_btn):
            btn.SetFocusFromKbd()
            button_row.Add(btn, 0, wx.ALL, 4)

        volume_row = wx.BoxSizer(wx.HORIZONTAL)
        volume_row.Add(self.volume_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 4)
        volume_row.Add(self.volume_slider, 1, wx.EXPAND | wx.RIGHT, 4)
        volume_row.Add(self.volume_value_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)

        pan_row = wx.BoxSizer(wx.HORIZONTAL)
        pan_row.Add(self.pan_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 4)
        pan_row.Add(self.pan_slider, 1, wx.EXPAND | wx.RIGHT, 4)
        pan_row.Add(self.pan_value_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(button_row, 0, wx.EXPAND)
        outer.Add(volume_row, 0, wx.EXPAND)
        outer.Add(pan_row, 0, wx.EXPAND)
        self.SetSizer(outer)

        self._on_play_cb: Optional[Callable[[], None]] = None
        self._on_stop_cb: Optional[Callable[[], None]] = None
        self._on_record_cb: Optional[Callable[[], None]] = None
        self._on_mute_cb: Optional[Callable[[], None]] = None
        self._on_volume_cb: Optional[Callable[[int], None]] = None
        self._on_pan_cb: Optional[Callable[[int], None]] = None

        self.play_btn.Bind(wx.EVT_BUTTON, self._on_play_clicked)
        self.stop_btn.Bind(wx.EVT_BUTTON, self._on_stop_clicked)
        self.record_btn.Bind(wx.EVT_BUTTON, self._on_record_clicked)
        self.mute_btn.Bind(wx.EVT_BUTTON, self._on_mute_clicked)
        self.volume_slider.Bind(wx.EVT_SLIDER, self._on_volume_slider)
        self.pan_slider.Bind(wx.EVT_SLIDER, self._on_pan_slider)

    def _on_play_clicked(self, event: wx.CommandEvent) -> None:
        if self._on_play_cb:
            self._on_play_cb()

    def _on_stop_clicked(self, event: wx.CommandEvent) -> None:
        if self._on_stop_cb:
            self._on_stop_cb()

    def _on_record_clicked(self, event: wx.CommandEvent) -> None:
        if self._on_record_cb:
            self._on_record_cb()

    def _on_mute_clicked(self, event: wx.CommandEvent) -> None:
        if self._on_mute_cb:
            self._on_mute_cb()

    def _on_volume_slider(self, event: wx.Event) -> None:
        value = self.volume_slider.GetValue()
        self.volume_value_label.SetLabel(f"{value}%")
        if self._on_volume_cb:
            self._on_volume_cb(value)

    def _on_pan_slider(self, event: wx.Event) -> None:
        value = self.pan_slider.GetValue()
        self.pan_value_label.SetLabel(f"{value}%")
        if self._on_pan_cb:
            self._on_pan_cb(value)

    # --- callback setters ---
    @property
    def on_play(self) -> Optional[Callable[[], None]]:
        return self._on_play_cb

    @on_play.setter
    def on_play(self, cb: Optional[Callable[[], None]]) -> None:
        self._on_play_cb = cb

    @property
    def on_stop(self) -> Optional[Callable[[], None]]:
        return self._on_stop_cb

    @on_stop.setter
    def on_stop(self, cb: Optional[Callable[[], None]]) -> None:
        self._on_stop_cb = cb

    @property
    def on_record(self) -> Optional[Callable[[], None]]:
        return self._on_record_cb

    @on_record.setter
    def on_record(self, cb: Optional[Callable[[], None]]) -> None:
        self._on_record_cb = cb

    @property
    def on_mute(self) -> Optional[Callable[[], None]]:
        return self._on_mute_cb

    @on_mute.setter
    def on_mute(self, cb: Optional[Callable[[], None]]) -> None:
        self._on_mute_cb = cb

    @property
    def on_volume_changed(self) -> Optional[Callable[[int], None]]:
        return self._on_volume_cb

    @on_volume_changed.setter
    def on_volume_changed(self, cb: Optional[Callable[[int], None]]) -> None:
        self._on_volume_cb = cb

    @property
    def on_pan_changed(self) -> Optional[Callable[[int], None]]:
        return self._on_pan_cb

    @on_pan_changed.setter
    def on_pan_changed(self, cb: Optional[Callable[[int], None]]) -> None:
        self._on_pan_cb = cb

    def set_playing(self, is_playing: bool) -> None:
        self.play_btn.SetLabel("\u23f8 Pause" if is_playing else "\u25b6 Play")
        self.play_btn.SetName("Pause" if is_playing else "Play")

    def set_recording(self, is_recording: bool) -> None:
        label = "\u25cf Recording On" if is_recording else "\u25cf Record Off"
        self.record_btn.SetLabel(label)
        self.record_btn.SetName(label)

    def set_muted(self, is_muted: bool) -> None:
        label = "\U0001F507 Mute On" if is_muted else "\U0001F507 Mute Off"
        self.mute_btn.SetLabel(label)
        self.mute_btn.SetName(label)

    def set_volume(self, percent: int) -> None:
        percent = max(0, min(100, percent))
        self.volume_slider.SetValue(percent)
        self.volume_value_label.SetLabel(f"{percent}%")

    def set_pan(self, percent: int) -> None:
        percent = max(0, min(100, percent))
        self.pan_slider.SetValue(percent)
        self.pan_value_label.SetLabel(f"{percent}%")
