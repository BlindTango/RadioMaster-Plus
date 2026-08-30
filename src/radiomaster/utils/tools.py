"""Tool path resolution for portable external dependencies.

RadioMaster+ bundles ffmpeg, ffplay, ffprobe, and yt-dlp in a ``tools/``
directory next to the application.  This module resolves the correct path
to each tool whether running from source, from a PyInstaller bundle, or
from a portable installation.
"""

import os
import sys
from pathlib import Path


def _get_tools_dir() -> Path:
    """Return the path to the ``tools/`` directory.

    Resolution order:
    1. PyInstaller bundle: ``sys._MEIPASS / tools``
    2. Development / source: project root / ``tools``
    3. Portable install: ``appdir / tools``
    """
    # PyInstaller _MEIPASS — tools are in _internal/tools/
    if hasattr(sys, "_MEIPASS"):
        meipass = Path(sys._MEIPASS)
        # Check _internal/tools/ first (PyInstaller COLLECT puts datas in _internal/)
        internal_tools = meipass / "_internal" / "tools"
        if internal_tools.is_dir():
            return internal_tools
        # Fallback: meipass/tools/ (one-folder bundle root)
        root_tools = meipass / "tools"
        if root_tools.is_dir():
            return root_tools

    # Walk up from the source tree to find the project root
    # (src/radiomaster/utils/tools.py -> src/radiomaster/utils/ -> src/radiomaster/ -> src/ -> project root)
    here = Path(__file__).resolve().parent  # utils/
    for _ in range(4):
        candidate = here / "tools"
        if candidate.is_dir():
            return candidate
        here = here.parent

    # Fallback: alongside the executable
    exe_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()
    candidate = exe_dir / "tools"
    if candidate.is_dir():
        return candidate

    return Path.cwd() / "tools"


def get_tools_dir() -> str:
    """Return the path to the ``tools/`` directory as a string."""
    return str(_get_tools_dir())


def get_ffmpeg() -> str:
    """Return the path to ffmpeg.exe."""
    return str(_get_tools_dir() / "ffmpeg.exe")


def get_ffplay() -> str:
    """Return the path to ffplay.exe."""
    return str(_get_tools_dir() / "ffplay.exe")


def get_ffprobe() -> str:
    """Return the path to ffprobe.exe."""
    return str(_get_tools_dir() / "ffprobe.exe")


def get_ytdlp() -> str:
    """Return the path to yt-dlp.exe."""
    return str(_get_tools_dir() / "yt-dlp.exe")
