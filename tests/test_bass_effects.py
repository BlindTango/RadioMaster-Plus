"""Preset updates must reach an already active native effect."""

import ctypes
import threading
from unittest.mock import MagicMock

import pytest

from radiomaster.engine.bass_host import (
    BassHost,
    _chorus_parameters,
    _compressor_parameters,
    _distortion_parameters,
    _echo_parameters,
    _flanger_parameters,
    _gargle_parameters,
    _ReverbParameters,
)
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


# ---------------------------------------------------------------------------
# Live parameter updates for every DX8 effect -- the original bug: only
# reverb had a mapper, so dragging a slider in the Chorus (or Echo,
# Flanger, Gargle, Compressor, Distortion) preset editor changed
# nothing audibly while the effect was active.
# ---------------------------------------------------------------------------

def _make_host_with_fx(fx_name, params):
    """A BassHost skeleton with one active FX handle, like the reverb
    test above -- no real BASS involved. _fx_params starts EMPTY (not
    pre-seeded with the first apply's values) so the first apply_effects
    call genuinely pushes parameters instead of hitting set_fx's
    identical-names-and-params no-op guard."""
    host = BassHost.__new__(BassHost)
    host._lock = threading.RLock()
    host._handle = 1
    host._dll = MagicMock()
    host._dll.BASS_ChannelSetFX.return_value = 42
    host._fx_names = {fx_name}
    host._fx_handles = {fx_name: 42}
    host._fx_params = {}
    return host


@pytest.mark.parametrize("effect_id", ["chorus", "echo", "flanger", "gargle",
                                       "compressor", "distortion"])
def test_slider_changes_reach_the_active_fx_handle(effect_id):
    """apply_effects() with new params must call BASS_FXSetParameters on
    the existing handle -- not remove/re-add the effect (which would
    click) and not silently ignore the change (the original bug)."""
    from radiomaster.ui.effects_data import PARAM_DEFS

    host = _make_host_with_fx(effect_id, {})
    applied = []
    host._dll.BASS_FXSetParameters.side_effect = (
        lambda handle, pointer: (applied.append(handle), True)[1]
    )
    backend = BassRadioEngine.__new__(BassRadioEngine)
    backend._rate = 1.0

    def request(command):
        if command["cmd"] == "set_fx":
            host.set_fx(command["fx"], command["params"])
        return {}

    backend._request = request
    effects = {effect_id: {"enabled": True, "params": {}}}

    # First application: defaults (empty params dict -> mapper defaults).
    backend.apply_effects(effects)
    assert len(applied) == 1
    # Second application: a genuinely different param set (every slider
    # moved to its max) must push a second update to the same handle.
    maxed = {key: max_val for _label, key, _min, max_val, _default
             in PARAM_DEFS[effect_id]}
    effects[effect_id]["params"] = maxed
    backend.apply_effects(effects)
    assert len(applied) == 2
    assert applied[0] == applied[1] == 42
    host._dll.BASS_ChannelSetFX.assert_not_called()  # never re-created
    host._dll.BASS_ChannelRemoveFX.assert_not_called()


@pytest.mark.parametrize("effect_id", ["chorus", "echo", "flanger", "gargle",
                                       "compressor", "distortion"])
def test_unchanged_params_do_not_disturb_the_active_effect(effect_id):
    """Re-applying the identical settings must be a no-op -- the set_fx
    early-return guard compares both names and params. The first apply
    (empty -> params) is a genuine change and DOES push; the second,
    identical apply must not."""
    host = _make_host_with_fx(effect_id, {})
    backend = BassRadioEngine.__new__(BassRadioEngine)
    backend._rate = 1.0

    def request(command):
        if command["cmd"] == "set_fx":
            host.set_fx(command["fx"], command["params"])
        return {}

    backend._request = request
    effects = {effect_id: {"enabled": True, "params": {"delay": 50}}}
    backend.apply_effects(effects)
    host._dll.BASS_FXSetParameters.reset_mock()
    backend.apply_effects(effects)  # identical -- must be a no-op
    host._dll.BASS_FXSetParameters.assert_not_called()


@pytest.mark.parametrize("preset", BUILTIN_PRESETS["chorus"].values())
def test_chorus_presets_fit_native_parameter_ranges(preset):
    p = _chorus_parameters(preset)
    assert 0 <= p.fWetDryMix <= 100
    assert 0 <= p.fDepth <= 100
    assert -99 <= p.fFeedback <= 99
    assert 0 <= p.fFrequency <= 10
    assert 0 <= p.fDelay <= 20


@pytest.mark.parametrize("preset", BUILTIN_PRESETS["flanger"].values())
def test_flanger_presets_fit_native_parameter_ranges(preset):
    p = _flanger_parameters(preset)
    assert 0 <= p.fWetDryMix <= 100
    assert 0 <= p.fDepth <= 100
    assert -99 <= p.fFeedback <= 99
    assert 0 <= p.fFrequency <= 10
    assert 0 <= p.fDelay <= 4


@pytest.mark.parametrize("preset", BUILTIN_PRESETS["echo"].values())
def test_echo_presets_fit_native_parameter_ranges(preset):
    p = _echo_parameters(preset)
    assert 0 <= p.fWetDryMix <= 100
    assert 0 <= p.fFeedback <= 100
    assert 1 <= p.fLeftDelay <= 2000
    assert 1 <= p.fRightDelay <= 2000


@pytest.mark.parametrize("preset", BUILTIN_PRESETS["gargle"].values())
def test_gargle_presets_fit_native_parameter_ranges(preset):
    p = _gargle_parameters(preset)
    assert 1 <= p.dwRateHz <= 1000
    assert p.dwWaveShape in (0, 1)


@pytest.mark.parametrize("preset", BUILTIN_PRESETS["compressor"].values())
def test_compressor_presets_fit_native_parameter_ranges(preset):
    p = _compressor_parameters(preset)
    assert -60 <= p.fGain <= 60
    assert 0.01 <= p.fAttack <= 500
    assert 50 <= p.fRelease <= 3000
    assert -60 <= p.fThreshold <= 0
    assert 1 <= p.fRatio <= 100


@pytest.mark.parametrize("preset", BUILTIN_PRESETS["distortion"].values())
def test_distortion_presets_fit_native_parameter_ranges(preset):
    p = _distortion_parameters(preset)
    assert -60 <= p.fGain <= 0
    assert 0 <= p.fEdge <= 100
    assert 100 <= p.fPostEQCenterFrequency <= 8000
    assert 100 <= p.fPostEQBandwidth <= 8000
    assert 100 <= p.fPreLowpassCutoff <= 8000


def test_chorus_slider_changes_are_audibly_different():
    """The actual reported bug: moving the chorus sliders must produce
    different native parameter values -- the original code never pushed
    chorus params at all, so every slider position sounded identical.
    Note fDelay is NOT asserted: DX8 chorus caps fDelay at 20 ms, so the
    app's 20-100 ms delay slider is deliberately folded into fDepth
    (see _chorus_parameters) -- fDelay alone can't distinguish presets."""
    low = _chorus_parameters({"delay": 20, "decay": 0.0, "speed": 0.1, "depth": 0.0})
    high = _chorus_parameters({"delay": 100, "decay": 1.0, "speed": 5.0, "depth": 10.0})
    assert high.fDepth > low.fDepth
    assert high.fFrequency > low.fFrequency
    assert high.fWetDryMix > low.fWetDryMix
