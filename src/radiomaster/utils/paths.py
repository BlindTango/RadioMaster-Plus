"""Path resolution for RadioMaster+."""

import os
import sys
from platformdirs import user_config_dir, user_data_dir, user_cache_dir

from radiomaster import __app_name__


def _app_dir() -> str:
    """Directory the application actually lives in: the .exe's own folder
    for a packaged/frozen build, the repo root when running from source.

    Deliberately NOT derived from this module's own __file__ the same way
    for both cases -- that assumes a fixed source-tree depth
    (src/radiomaster/utils/paths.py, 3 levels up to the repo root), which
    does not hold once PyInstaller has extracted this module into its own
    bundle layout. Using __file__ there landed "../../../portable.txt" and
    the portable data folder somewhere inside the bundle's temp/_internal
    structure instead of next to RadioMaster+.exe -- so a portable install
    silently fell back to the regular per-user AppData/Music paths every
    time, defeating the entire point of "portable". Same pattern already
    used in utils/tools.py for locating the bundled ffmpeg/yt-dlp.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.join(os.path.dirname(__file__), "..", "..", "..")


def get_resource_path(*parts: str) -> str:
    """Resolve a path under resources/ (icon, themes, default shortcuts...)
    for both a source run and a PyInstaller bundle.

    Mirrors utils/tools.py's _get_tools_dir(): PyInstaller's COLLECT step
    puts bundled datas in _internal/ for a onedir build, so _MEIPASS/resources
    doesn't exist there -- check _internal/resources first, then the bundle
    root, before falling back to the source tree.
    """
    if hasattr(sys, "_MEIPASS"):
        meipass = sys._MEIPASS
        internal = os.path.join(meipass, "_internal", "resources", *parts)
        if os.path.exists(internal):
            return internal
        root = os.path.join(meipass, "resources", *parts)
        if os.path.exists(root):
            return root
    return os.path.join(_app_dir(), "resources", *parts)


def _is_writable(path: str) -> bool:
    """Whether we can actually write into ``path`` (creating it if needed).

    Used instead of a ``portable.txt`` marker file to decide whether this is
    a portable install: a marker file requires the installer and the app to
    agree on a convention (and silently does nothing if the installer forgets
    to write it, or if the folder is copied by hand without it). A real
    write-probe is self-sufficient -- if the app's own folder is writable
    (a portable copy on a USB drive, or "install for current user only" into
    a user-owned folder), it stays portable automatically; if it isn't
    (a standard Program Files install), it falls back to the per-user
    platformdirs paths on its own, with no installer coordination required.
    """
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".write_test")
        with open(probe, "w") as f:
            f.write("x")
        os.remove(probe)
        return True
    except OSError:
        return False


def get_paths() -> dict[str, str]:
    """Get platform-appropriate paths for config, data, and cache.

    Portable mode is detected by actually probing whether the application's
    own directory is writable -- see ``_is_writable()`` -- rather than by a
    marker file or command-line flag.
    """
    app_name = __app_name__.replace("+", "Plus")

    app_dir = _app_dir()
    portable = "--portable" in sys.argv or _is_writable(app_dir)

    if portable:
        base = os.path.join(app_dir, "data")
        return {
            "config": os.path.join(base, "config"),
            "data": os.path.join(base, "data"),
            "cache": os.path.join(base, "cache"),
            "downloads": os.path.join(base, "downloads"),
            "recordings": os.path.join(base, "recordings"),
            "logs": os.path.join(base, "logs"),
        }

    return {
        "config": user_config_dir(app_name, app_name),
        "data": user_data_dir(app_name, app_name),
        "cache": user_cache_dir(app_name, app_name),
        "downloads": os.path.join(os.path.expanduser("~"), "Music", app_name),
        "recordings": os.path.join(os.path.expanduser("~"), "Music", app_name, "Recordings"),
        "logs": os.path.join(user_data_dir(app_name, app_name), "logs"),
    }


def get_recordings_dir() -> str:
    """Settings > Recordings > Recording Location, self-healing against a
    stale saved value.

    That setting is only ever written once, when Settings is saved -- if
    it happened to be saved while running non-portable (e.g. installed to
    Program Files, or before being moved to a portable location), the
    Music-folder path it captured then keeps being used forever after,
    even once the app is genuinely running portable and get_paths() would
    otherwise resolve inside the app's own folder as documented ("The app
    itself is portable by default regardless of install type"). Comparing
    the saved value against *both* modes' auto-computed defaults (not just
    the current one) tells an actual deliberate custom folder (respected
    always) apart from a stale snapshot of whichever default happened to
    be live the one time Settings was opened.
    """
    from radiomaster.utils.config import ConfigManager
    config = ConfigManager.get_instance()
    saved = config.get("recordings", "recording_path", default="").strip()
    current_default = str(get_paths()["recordings"])
    if not saved:
        return current_default

    app_name = __app_name__.replace("+", "Plus")
    music_default = os.path.join(os.path.expanduser("~"), "Music", app_name, "Recordings")
    stale_defaults = {os.path.normcase(os.path.normpath(current_default)),
                       os.path.normcase(os.path.normpath(music_default))}
    if os.path.normcase(os.path.normpath(saved)) in stale_defaults \
            and os.path.normpath(saved) != os.path.normpath(current_default):
        return current_default
    return saved
