"""Live, per-process volume control via WASAPI audio sessions.

ffplay has no way to change its own volume after it starts short of
restarting it with a new -volume flag (there's no live filter-graph reload,
and its interactive volume-up/down keys only work through a real SDL
window, which -nodisp never creates -- writing bytes to its stdin pipe, as
this code used to do, reaches nothing). Windows itself tracks a separate
volume for every process's audio session though, independent of what the
process asked for, and lets any other process adjust it live via
ISimpleAudioVolume -- this is the same mechanism the Windows Volume Mixer
uses per-app. That gives genuine no-restart volume control: find the
ffplay child's session by its PID and set the level directly.
"""

from __future__ import annotations

import ctypes
from ctypes import POINTER, byref, c_float, c_void_p
from typing import Optional

import comtypes
from comtypes import GUID, COMMETHOD, IUnknown, HRESULT

CLSCTX_ALL = 23

CLSID_MMDeviceEnumerator = GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
IID_IMMDeviceEnumerator = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
IID_IAudioSessionManager2 = GUID("{77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F}")
IID_IAudioSessionControl2 = GUID("{BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D}")
IID_ISimpleAudioVolume = GUID("{87CE5498-68D6-44E5-9215-6DA47EF883D8}")

EDataFlow_eRender = 0
ERole_eConsole = 0


class ISimpleAudioVolume(IUnknown):
    _iid_ = IID_ISimpleAudioVolume
    _methods_ = [
        COMMETHOD([], HRESULT, "SetMasterVolume",
                  (["in"], c_float, "level"),
                  (["in"], POINTER(GUID), "context")),
        COMMETHOD([], HRESULT, "GetMasterVolume",
                  (["out"], POINTER(c_float), "level")),
        COMMETHOD([], HRESULT, "SetMute",
                  (["in"], ctypes.c_int, "mute"),
                  (["in"], POINTER(GUID), "context")),
        COMMETHOD([], HRESULT, "GetMute",
                  (["out"], POINTER(ctypes.c_int), "mute")),
    ]


class IAudioSessionControl2(IUnknown):
    _iid_ = IID_IAudioSessionControl2
    _methods_ = [
        COMMETHOD([], HRESULT, "GetState", (["out"], POINTER(ctypes.c_int), "state")),
        COMMETHOD([], HRESULT, "GetDisplayName", (["out"], POINTER(ctypes.c_wchar_p), "name")),
        COMMETHOD([], HRESULT, "SetDisplayName",
                  (["in"], ctypes.c_wchar_p, "name"), (["in"], POINTER(GUID), "context")),
        COMMETHOD([], HRESULT, "GetIconPath", (["out"], POINTER(ctypes.c_wchar_p), "path")),
        COMMETHOD([], HRESULT, "SetIconPath",
                  (["in"], ctypes.c_wchar_p, "path"), (["in"], POINTER(GUID), "context")),
        COMMETHOD([], HRESULT, "GetGroupingParam", (["out"], POINTER(GUID), "group")),
        COMMETHOD([], HRESULT, "SetGroupingParam",
                  (["in"], POINTER(GUID), "group"), (["in"], POINTER(GUID), "context")),
        COMMETHOD([], HRESULT, "RegisterAudioSessionNotification", (["in"], c_void_p, "client")),
        COMMETHOD([], HRESULT, "UnregisterAudioSessionNotification", (["in"], c_void_p, "client")),
        COMMETHOD([], HRESULT, "GetSessionIdentifier", (["out"], POINTER(ctypes.c_wchar_p), "id")),
        COMMETHOD([], HRESULT, "GetSessionInstanceIdentifier",
                  (["out"], POINTER(ctypes.c_wchar_p), "id")),
        COMMETHOD([], HRESULT, "GetProcessId", (["out"], POINTER(ctypes.c_ulong), "pid")),
        COMMETHOD([], HRESULT, "IsSystemSoundsSession"),
        COMMETHOD([], HRESULT, "SetDuckingPreference", (["in"], ctypes.c_int, "optOut")),
    ]


class IAudioSessionEnumerator(IUnknown):
    _iid_ = GUID("{E2F5BB11-0570-40CA-ACDD-3AA01277DEE8}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetCount", (["out"], POINTER(ctypes.c_int), "count")),
        COMMETHOD([], HRESULT, "GetSession",
                  (["in"], ctypes.c_int, "index"),
                  (["out"], POINTER(POINTER(IUnknown)), "session")),
    ]


class IAudioSessionManager2(IUnknown):
    _iid_ = IID_IAudioSessionManager2
    _methods_ = [
        COMMETHOD([], HRESULT, "GetAudioSessionControl",
                  (["in"], POINTER(GUID), "category"),
                  (["in"], ctypes.c_int, "streamFlags"),
                  (["out"], POINTER(POINTER(IUnknown)), "control")),
        COMMETHOD([], HRESULT, "GetSimpleAudioVolume",
                  (["in"], POINTER(GUID), "category"),
                  (["in"], ctypes.c_int, "streamFlags"),
                  (["out"], POINTER(POINTER(IUnknown)), "volume")),
        COMMETHOD([], HRESULT, "GetSessionEnumerator",
                  (["out"], POINTER(POINTER(IAudioSessionEnumerator)), "enum")),
        COMMETHOD([], HRESULT, "RegisterSessionNotification", (["in"], c_void_p, "client")),
        COMMETHOD([], HRESULT, "UnregisterSessionNotification", (["in"], c_void_p, "client")),
        COMMETHOD([], HRESULT, "RegisterDuckNotification",
                  (["in"], ctypes.c_wchar_p, "sessionID"), (["in"], c_void_p, "client")),
        COMMETHOD([], HRESULT, "UnregisterDuckNotification", (["in"], c_void_p, "client")),
    ]


class IMMDevice(IUnknown):
    _iid_ = GUID("{D666063F-1587-4E43-81F1-B948E807363F}")
    _methods_ = [
        COMMETHOD([], HRESULT, "Activate",
                  (["in"], POINTER(GUID), "iid"),
                  (["in"], ctypes.c_ulong, "clsCtx"),
                  (["in"], c_void_p, "activationParams"),
                  (["out"], POINTER(POINTER(IUnknown)), "iface")),
        COMMETHOD([], HRESULT, "OpenPropertyStore",
                  (["in"], ctypes.c_ulong, "access"),
                  (["out"], POINTER(POINTER(IUnknown)), "store")),
        COMMETHOD([], HRESULT, "GetId", (["out"], POINTER(ctypes.c_wchar_p), "id")),
        COMMETHOD([], HRESULT, "GetState", (["out"], POINTER(ctypes.c_ulong), "state")),
    ]


class IMMDeviceEnumerator(IUnknown):
    _iid_ = IID_IMMDeviceEnumerator
    _methods_ = [
        COMMETHOD([], HRESULT, "EnumAudioEndpoints",
                  (["in"], ctypes.c_int, "dataFlow"),
                  (["in"], ctypes.c_ulong, "stateMask"),
                  (["out"], POINTER(POINTER(IUnknown)), "devices")),
        COMMETHOD([], HRESULT, "GetDefaultAudioEndpoint",
                  (["in"], ctypes.c_int, "dataFlow"),
                  (["in"], ctypes.c_int, "role"),
                  (["out"], POINTER(POINTER(IMMDevice)), "device")),
        COMMETHOD([], HRESULT, "GetDevice",
                  (["in"], ctypes.c_wchar_p, "id"),
                  (["out"], POINTER(POINTER(IMMDevice)), "device")),
        COMMETHOD([], HRESULT, "RegisterEndpointNotificationCallback", (["in"], c_void_p, "client")),
        COMMETHOD([], HRESULT, "UnregisterEndpointNotificationCallback", (["in"], c_void_p, "client")),
    ]


def _find_simple_volume_for_pid(pid: int) -> Optional["ISimpleAudioVolume"]:
    """Return the ISimpleAudioVolume for the audio session owned by *pid*,
    or None if that process has no active render session yet (e.g. ffplay
    hasn't opened its WASAPI stream yet -- callers should retry briefly)."""
    enumerator = comtypes.CoCreateInstance(
        CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, comtypes.CLSCTX_INPROC_SERVER
    )
    device = enumerator.GetDefaultAudioEndpoint(EDataFlow_eRender, ERole_eConsole)
    mgr_ptr = device.Activate(IID_IAudioSessionManager2, CLSCTX_ALL, None)
    mgr = mgr_ptr.QueryInterface(IAudioSessionManager2)
    session_enum = mgr.GetSessionEnumerator()
    count = session_enum.GetCount()
    for i in range(count):
        session_ptr = session_enum.GetSession(i)
        try:
            ctl2 = session_ptr.QueryInterface(IAudioSessionControl2)
        except comtypes.COMError:
            continue
        try:
            session_pid = ctl2.GetProcessId()
        except comtypes.COMError:
            continue
        if session_pid == pid:
            return session_ptr.QueryInterface(ISimpleAudioVolume)
    return None


def set_process_volume(pid: int, level: float) -> bool:
    """Set *pid*'s WASAPI session volume (0.0-1.0) live, no restart needed.

    Returns False (caller should fall back to relaunching with a new
    -volume flag) if the session can't be found or COM isn't usable --
    e.g. this thread has no STA apartment, or ffplay hasn't opened its
    audio stream yet.
    """
    try:
        comtypes.CoInitialize()
    except OSError:
        pass  # already initialized on this thread
    try:
        volume = _find_simple_volume_for_pid(pid)
        if volume is None:
            return False
        volume.SetMasterVolume(max(0.0, min(1.0, level)), None)
        return True
    except (comtypes.COMError, OSError):
        return False
