"""Preset updates must reach an already active native effect."""

import ctypes
import threading
from unittest.mock import MagicMock

import pytest

from radiomaster.engine.bass_host import BassHost, _ReverbParameters
from radiomaster.engine.bass_radio_engine import BassRadioEngine
from radiomaster.ui.effects_data import BUILTIN_PRESETS


def test_reverb_preset_updates_existing_handle_and_survives_new_stream():
    host = BassHost.__new__(BassHost)
    host._lock = threading.RLock()
    host._handle = 1
    host._dll = MagicMock()
    host._dll.BASS_ChannelSetFX.return_value = 42
    host._fx_names = set()
    host._fx_handles = {}
    host._fx_params = {}
    applied = []

    def capture(handle, pointer):
        value = ctypes.cast(pointer, ctypes.POINTER(_ReverbParameters)).contents
        applied.append((handle, value.fReverbMix, value.fReverbTime))
        return True

    host._dll.BASS_FXSetParameters.side_effect = capture
    backend = BassRadioEngine.__new__(BassRadioEngine)
    backend._rate = 1.0

    def request(command):
        if command["cmd"] == "set_fx":
            host.set_fx(command["fx"], command["params"])
        return {}

    backend._request = request
    effects = {"reverb": {"enabled": True, "params": {}}}
    for preset in ("Stadium", "Small Room"):
        effects["reverb"]["params"] = BUILTIN_PRESETS["reverb"][preset]
        backend.apply_effects(effects)

    assert len(applied) == 2
    assert applied[1][0] == applied[0][0] == 42
    assert applied[1][1] < applied[0][1]  # less wet signal
    assert applied[1][2] < applied[0][2]  # shorter reverberation
    host._dll.BASS_ChannelSetFX.assert_called_once()
    host._dll.BASS_ChannelRemoveFX.assert_not_called()

    # Reapplying unchanged settings should not disturb the active effect.
    backend.apply_effects(effects)
    assert len(applied) == 2

    host._fx_handles = {}
    host._apply_fx(2)
    assert applied[-1] == applied[1]


@pytest.mark.parametrize("preset", BUILTIN_PRESETS["reverb"].values())
def test_reverb_presets_fit_native_parameter_ranges(preset):
    from radiomaster.engine.bass_host import _reverb_parameters

    params = _reverb_parameters(preset)
    assert -96 <= params.fReverbMix <= 0
    assert 0.001 <= params.fReverbTime <= 3000
    assert 0.001 <= params.fHighFreqRTRatio <= 0.999
