"""Windows "run at startup" registration via the per-user Run key.

Uses HKEY_CURRENT_USER so it never needs elevation, matching the rest of
the app's no-admin-required install/update story.
"""

import logging
import os
import sys

logger = logging.getLogger("radiomaster")

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "RadioMaster+"


def _startup_command() -> str | None:
    """The command to register, or None when running from source (nothing
    meaningful to launch on boot in that case)."""
    if not getattr(sys, "frozen", False):
        return None
    return f'"{sys.executable}"'


def set_run_on_startup(enabled: bool) -> None:
    """Add or remove the per-user Run key entry. No-op (not an error) when
    running from source, since there's no installed .exe to point at."""
    command = _startup_command()
    if command is None:
        return
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, command)
            else:
                try:
                    winreg.DeleteValue(key, _VALUE_NAME)
                except FileNotFoundError:
                    pass
    except OSError as e:
        logger.warning(f"Could not update startup registry entry: {e}")


def is_run_on_startup() -> bool:
    """Whether the Run key entry currently exists (used to reconcile the
    Settings checkbox with actual registry state, e.g. after a manual
    registry edit or a reinstall to a different path)."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_QUERY_VALUE) as key:
            winreg.QueryValueEx(key, _VALUE_NAME)
            return True
    except OSError:
        return False
