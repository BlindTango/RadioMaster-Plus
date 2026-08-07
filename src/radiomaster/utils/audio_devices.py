"""Enumerate Windows audio output (render) devices for playback device selection.

ffplay has no CLI flag for choosing an output device -- it goes through SDL2,
which reads the device to open from the SDL_AUDIO_DEVICE_NAME environment
variable set on the ffplay process (see playback_engine.py). The name has to
match SDL's own enumerated device name *exactly*, which is the same string
Windows shows in Settings > Sound: "{endpoint} ({adapter})", with a "N- "
prefix inserted before the adapter name when multiple devices share the same
endpoint+adapter pair (Windows' own disambiguation convention). That
disambiguation numbering is computed across *all* registered devices
(including disconnected/disabled ones), not just the active ones -- verified
empirically against the real bundled ffplay.exe.
"""

from __future__ import annotations

import winreg
from collections import defaultdict
from typing import Any

_RENDER_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render"
_PKEY_FRIENDLY_NAME = "{a45c254e-df1c-4efd-8020-67d146a850e0},2"
_PKEY_ADAPTER_NAME = "{b3f8fa53-0004-438e-9003-51a46e139bfc},6"
_DEVICE_STATE_ACTIVE = 0x1
_DEVICE_STATE_MASK = 0xF


def list_audio_output_devices() -> list[dict[str, str]]:
    """Return active audio output devices as [{"guid": ..., "name": ...}, ...].

    ``name`` is the exact string to hand to SDL_AUDIO_DEVICE_NAME.
    Returns an empty list if devices can't be enumerated (non-Windows,
    registry access denied, etc.) -- callers should treat that as
    "device selection unavailable, use the system default".
    """
    try:
        all_devices = _read_registry_devices()
    except OSError:
        return []

    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for d in all_devices:
        groups[(d["short_name"], d["adapter_name"])].append(d)

    result = []
    for (short_name, adapter_name), group in groups.items():
        multiple = len(group) > 1
        for idx, d in enumerate(group, start=1):
            if not d["active"]:
                continue
            if adapter_name:
                prefix = f"{idx}- " if multiple else ""
                display = f"{short_name} ({prefix}{adapter_name})"
            else:
                display = short_name
            result.append({"guid": d["guid"], "name": display})
    return result


def _read_registry_devices() -> list[dict[str, Any]]:
    devices = []
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _RENDER_KEY) as render_key:
        i = 0
        while True:
            try:
                guid = winreg.EnumKey(render_key, i)
            except OSError:
                break
            i += 1
            try:
                with winreg.OpenKey(render_key, guid) as dev_key:
                    state, _ = winreg.QueryValueEx(dev_key, "DeviceState")
                    with winreg.OpenKey(dev_key, "Properties") as props_key:
                        short_name = _query_or_empty(props_key, _PKEY_FRIENDLY_NAME)
                        adapter_name = _query_or_empty(props_key, _PKEY_ADAPTER_NAME)
                    if short_name:
                        devices.append({
                            "guid": guid,
                            "short_name": short_name,
                            "adapter_name": adapter_name,
                            "active": (state & _DEVICE_STATE_MASK) == _DEVICE_STATE_ACTIVE,
                        })
            except OSError:
                continue
    return devices


def _query_or_empty(key: "winreg.HKEYType", value_name: str) -> str:
    try:
        value, _ = winreg.QueryValueEx(key, value_name)
        return value or ""
    except OSError:
        return ""
