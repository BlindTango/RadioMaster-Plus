"""Parameter-editing dialog for a single effect -- just the slider rows,
no enable toggle or preset list. Used by PresetManagerDialog's New/Edit
actions to get concrete parameter values for a preset.
"""

import wx
from typing import Any, Callable, Optional
from radiomaster.utils.accessibility import set_accessible_name
from radiomaster.ui.effects_data import PARAM_DEFS, EFFECT_LABELS


class EffectParamsDialog(wx.Dialog):
    """A slider per adjustable parameter of one effect.

    *on_live_change*, when given, fires on every slider move with the
    dialog's current full param dict -- e.g. wired to
    PlaybackEngine.apply_effect_params so dragging a slider is audible
    immediately (matching the Equalizer dialog's own live-preview
    behavior), instead of a New/Edit Preset session being silent until
    OK is clicked, with no way to tell whether the values being picked
    are actually what you want."""

    def __init__(self, parent: wx.Window | None, effect_id: str, current_params: dict[str, Any],
                 title: str | None = None,
                 on_live_change: Optional[Callable[[dict[str, float]], None]] = None) -> None:
        self._effect_id = effect_id
        self._param_defs = PARAM_DEFS[effect_id]
        self._on_live_change = on_live_change
        # No fixed size: the number of parameters ranges from 2 (Distortion)
        # to 10 (Equalizer) -- a size picked for the middle of that range
        # left Equalizer's rows clipped at the bottom (needed 398px tall,
        # given only 340). SetSizerAndFit() below sizes to actual content
        # instead.
        super().__init__(parent, title=title or f"{EFFECT_LABELS[effect_id]} Parameters")
        self._controls: dict[str, wx.Slider] = {}
        self._labels: dict[str, wx.StaticText] = {}
        self._scales: dict[str, float] = {}
        self._setup_ui(current_params)
        self.Centre()

    def _setup_ui(self, current_params: dict[str, Any]) -> None:
        sizer = wx.BoxSizer(wx.VERTICAL)

        for param_label, key, min_val, max_val, default in self._param_defs:
            row = wx.BoxSizer(wx.HORIZONTAL)
            row.Add(wx.StaticText(self, label=param_label, size=(170, -1)),
                    0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)

            current = float(current_params.get(key, default))
            scale = 100 if (max_val - min_val) < 10 else 10 if (max_val - min_val) < 100 else 1
            self._scales[key] = scale
            slider = wx.Slider(self, value=int(current * scale),
                                minValue=int(min_val * scale), maxValue=int(max_val * scale),
                                size=(180, -1), style=wx.SL_HORIZONTAL)
            set_accessible_name(slider, param_label)
            self._controls[key] = slider
            row.Add(slider, 1, wx.ALIGN_CENTER_VERTICAL)

            value_label = wx.StaticText(self, label=f"{current:g}")
            self._labels[key] = value_label
            row.Add(value_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)

            slider.Bind(wx.EVT_SLIDER, self._on_param_change)
            sizer.Add(row, 0, wx.EXPAND | wx.ALL, 4)

        btn_sizer = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        sizer.Add(btn_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 8)

        self.SetSizerAndFit(sizer)

    def _on_param_change(self, event: wx.CommandEvent) -> None:
        slider = event.GetEventObject()
        for key, s in self._controls.items():
            if s is slider:
                self._labels[key].SetLabel(f"{slider.GetValue() / self._scales[key]:g}")
                break
        if self._on_live_change:
            self._on_live_change(self.get_params())

    def get_params(self) -> dict[str, float]:
        """Get current parameter values."""
        return {key: slider.GetValue() / self._scales[key] for key, slider in self._controls.items()}
