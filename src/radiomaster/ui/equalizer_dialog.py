"""Equalizer dialog with 10-band graphic equalizer and preset management."""

import wx
from typing import Any, Callable
from radiomaster.utils.accessibility import set_accessible_name


EQ_BANDS = ["32", "64", "125", "250", "500", "1k", "2k", "4k", "8k", "16k"]
EQ_PRESETS: dict[str, dict[str, int]] = {
    "Flat": {},
    "Rock": {"32": 0, "64": 2, "125": 3, "250": 4, "500": 5, "1k": 4, "2k": 3, "4k": 2, "8k": 1, "16k": 0},
    "Pop": {"32": -1, "64": 0, "125": 2, "250": 3, "500": 4, "1k": 3, "2k": 2, "4k": 1, "8k": 0, "16k": -1},
    "Jazz": {"32": 2, "64": 3, "125": 2, "250": 4, "500": 5, "1k": 3, "2k": 2, "4k": 1, "8k": 2, "16k": 3},
    "Classical": {"32": 2, "64": 3, "125": 2, "250": 1, "500": 0, "1k": 0, "2k": 1, "4k": 2, "8k": 3, "16k": 4},
    "Dance": {"32": 4, "64": 3, "125": 2, "250": 5, "500": 6, "1k": 4, "2k": 2, "4k": 1, "8k": 0, "16k": -1},
    "Bass Boost": {"32": 6, "64": 5, "125": 4, "250": 2, "500": 0, "1k": 0, "2k": 0, "4k": 0, "8k": 0, "16k": 0},
    "Vocal": {"32": -2, "64": -1, "125": 0, "250": 2, "500": 4, "1k": 5, "2k": 4, "4k": 3, "8k": 1, "16k": 0},
}


class EqualizerDialog(wx.Dialog):
    """10-band graphic equalizer dialog with preset management."""

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent, title="Equalizer", size=(500, 400))
        self._band_sliders: dict[str, wx.Slider] = {}
        self._current_preset = "Flat"
        self._custom_presets: dict[str, dict[str, int]] = {}

        self._on_preset_cb: Callable[[str, dict[str, int]], None] | None = None
        self._on_bands_changed_cb: Callable[[dict[str, int]], None] | None = None

        self._setup_ui()
        self._apply_preset("Flat")
        self.Centre()

    def _setup_ui(self) -> None:
        """Create the equalizer layout."""
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # Preset selector
        preset_sizer = wx.BoxSizer(wx.HORIZONTAL)
        preset_sizer.Add(wx.StaticText(self, label="Preset:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._preset_choice = wx.Choice(self, choices=list(EQ_PRESETS.keys()))
        set_accessible_name(self._preset_choice, "Equalizer Preset")
        self._preset_choice.SetSelection(0)
        preset_sizer.Add(self._preset_choice, 0, wx.LEFT, 8)

        self._btn_save_preset = wx.Button(self, label="Save as Preset...")
        set_accessible_name(self._btn_save_preset, "Save Preset")
        preset_sizer.Add(self._btn_save_preset, 0, wx.LEFT, 8)

        self._btn_delete_preset = wx.Button(self, label="Delete Preset")
        set_accessible_name(self._btn_delete_preset, "Delete Preset")
        preset_sizer.Add(self._btn_delete_preset, 0, wx.LEFT, 8)

        main_sizer.Add(preset_sizer, 0, wx.EXPAND | wx.ALL, 8)

        # Band sliders
        bands_panel = wx.Panel(self)
        bands_sizer = wx.BoxSizer(wx.HORIZONTAL)

        for band in EQ_BANDS:
            band_sizer = wx.BoxSizer(wx.VERTICAL)

            # Label
            band_sizer.Add(wx.StaticText(bands_panel, label=band, style=wx.ALIGN_CENTER),
                           0, wx.ALIGN_CENTER | wx.BOTTOM, 4)

            # Slider (-12 to +12 dB)
            slider = wx.Slider(bands_panel, value=0, minValue=-12, maxValue=12,
                               size=(30, 200), style=wx.SL_VERTICAL | wx.SL_INVERSE | wx.SL_AUTOTICKS)
            set_accessible_name(slider, f"EQ {band} Hz")
            slider.SetTickFreq(3, 1)
            self._band_sliders[band] = slider
            band_sizer.Add(slider, 1, wx.ALIGN_CENTER | wx.EXPAND)

            # Value label
            self._band_labels: dict[str, wx.StaticText] = {}
            value_label = wx.StaticText(bands_panel, label="0 dB", style=wx.ALIGN_CENTER)
            self._band_labels[band] = value_label
            band_sizer.Add(value_label, 0, wx.ALIGN_CENTER | wx.TOP, 4)

            bands_sizer.Add(band_sizer, 1, wx.EXPAND | wx.ALL, 2)

        bands_panel.SetSizer(bands_sizer)
        main_sizer.Add(bands_panel, 1, wx.EXPAND | wx.ALL, 8)

        # Enable/Disable checkbox
        self._enable_check = wx.CheckBox(self, label="Enable Equalizer")
        set_accessible_name(self._enable_check, "Enable Equalizer")
        self._enable_check.SetValue(True)
        main_sizer.Add(self._enable_check, 0, wx.LEFT | wx.RIGHT, 8)

        # Buttons
        btn_sizer = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        main_sizer.Add(btn_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 8)

        self.SetSizer(main_sizer)

        # Bind events
        self._preset_choice.Bind(wx.EVT_CHOICE, self._on_preset_select)
        self._btn_save_preset.Bind(wx.EVT_BUTTON, self._on_save_preset)
        self._btn_delete_preset.Bind(wx.EVT_BUTTON, self._on_delete_preset)
        for slider in self._band_sliders.values():
            slider.Bind(wx.EVT_SLIDER, self._on_band_change)

    def _on_preset_select(self, event: wx.CommandEvent) -> None:
        """Handle preset selection."""
        preset = self._preset_choice.GetStringSelection()
        self._apply_preset(preset)

    def _apply_preset(self, name: str) -> None:
        """Apply a preset's band values."""
        all_presets = {**EQ_PRESETS, **self._custom_presets}
        preset = all_presets.get(name, {})
        self._current_preset = name
        for band in EQ_BANDS:
            value = preset.get(band, 0)
            self._band_sliders[band].SetValue(value)
            self._band_labels[band].SetLabel(f"{value:+d} dB")

    def _on_band_change(self, event: wx.CommandEvent) -> None:
        """Handle band slider change."""
        slider = event.GetEventObject()
        for band, s in self._band_sliders.items():
            if s == slider:
                self._band_labels[band].SetLabel(f"{slider.GetValue():+d} dB")
                break
        # Clear preset selection when manually adjusting
        self._preset_choice.SetSelection(wx.NOT_FOUND)
        if self._on_bands_changed_cb:
            self._on_bands_changed_cb(self.get_band_values())

    def _on_save_preset(self, event: wx.CommandEvent) -> None:
        """Save current settings as a new preset."""
        dlg = wx.TextEntryDialog(self, "Enter preset name:", "Save Preset")
        if dlg.ShowModal() == wx.ID_OK:
            name = dlg.GetValue().strip()
            if name:
                self._custom_presets[name] = self.get_band_values()
                self._preset_choice.Append(name)
                self._preset_choice.SetStringSelection(name)
        dlg.Destroy()

    def _on_delete_preset(self, event: wx.CommandEvent) -> None:
        """Delete the selected custom preset."""
        name = self._preset_choice.GetStringSelection()
        if name and name not in EQ_PRESETS:
            dlg = wx.MessageDialog(self, f"Delete preset '{name}'?", "Confirm",
                                   wx.YES_NO | wx.ICON_QUESTION)
            if dlg.ShowModal() == wx.ID_YES:
                self._custom_presets.pop(name, None)
                idx = self._preset_choice.FindString(name)
                if idx != wx.NOT_FOUND:
                    self._preset_choice.Delete(idx)
                self._preset_choice.SetSelection(0)
                self._apply_preset("Flat")
            dlg.Destroy()

    def get_band_values(self) -> dict[str, int]:
        """Get current band values."""
        return {band: slider.GetValue() for band, slider in self._band_sliders.items()}

    def is_enabled(self) -> bool:
        """Check if equalizer is enabled."""
        return self._enable_check.GetValue()

    def on_preset(self, cb: Callable[[str, dict[str, int]], None]) -> None:
        self._on_preset_cb = cb

    def on_bands_changed(self, cb: Callable[[dict[str, int]], None]) -> None:
        self._on_bands_changed_cb = cb
