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


def is_portable_mode() -> bool:
    """Return whether application-owned data should travel with the app."""
    return "--portable" in sys.argv or _is_writable(_app_dir())


def path_for_storage(path: str) -> str:
    r"""Make an app-contained path portable before saving it.

    Paths outside the application directory remain absolute because they are
    deliberate user locations.  Paths inside a portable copy are saved as
    ``.\data\...`` so a changed removable-drive letter cannot invalidate
    them.
    """
    value = path.strip()
    if not value:
        return ""
    absolute = os.path.abspath(os.path.expandvars(os.path.expanduser(value)))
    if not is_portable_mode():
        return absolute
    try:
        relative = os.path.relpath(absolute, os.path.abspath(_app_dir()))
    except ValueError:  # Different Windows drives.
        return absolute
    if relative == os.pardir or relative.startswith(os.pardir + os.sep):
        return absolute
    return "." if relative == "." else os.path.join(".", relative)


def resolve_stored_path(path: str) -> str:
    """Resolve a persisted relative path against the app's current folder."""
    value = path.strip()
    if not value:
        return ""
    value = os.path.expandvars(os.path.expanduser(value))
    if not os.path.isabs(value):
        value = os.path.join(_app_dir(), value)
    return _relocate_legacy_portable_path(os.path.normpath(os.path.abspath(value)))


def _relocate_legacy_portable_path(path: str) -> str:
    r"""Repair an old absolute ``...\data\...`` path after a drive move."""
    if not is_portable_mode() or not os.path.isabs(path) or os.path.exists(path):
        return path
    drive, tail = os.path.splitdrive(os.path.normpath(path))
    current_drive = os.path.splitdrive(os.path.abspath(_app_dir()))[0]
    parts = [part for part in tail.split(os.sep) if part]
    data_indexes = [i for i, part in enumerate(parts) if part.casefold() == "data"]
    if not drive or drive.casefold() == current_drive.casefold() or not data_indexes:
        return path
    # Portable application data always begins at the final "data" component.
    return os.path.join(_app_dir(), *parts[data_indexes[-1]:])


def get_paths() -> dict[str, str]:
    """Get platform-appropriate paths for config, data, and cache.

    Portable mode is detected by actually probing whether the application's
    own directory is writable -- see ``_is_writable()`` -- rather than by a
    marker file or command-line flag.
    """
    app_name = __app_name__.replace("+", "Plus")

    app_dir = _app_dir()
    portable = is_portable_mode()

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


def _self_healing_dir(config_section: str, config_key: str, current_default: str,
                       music_default: str) -> str:
    """Shared self-healing logic for a Settings-configurable folder that
    also has an auto-computed default -- see get_recordings_dir()'s own
    original docstring for the full story: such a setting is only ever
    written when Settings is actually saved, and if that happened while
    running non-portable (e.g. installed to Program Files, or before
    being moved to a portable location), the Music-folder path it
    captured then keeps being used forever after, even once the app is
    genuinely running portable and get_paths() would otherwise resolve
    inside the app's own folder as documented ("The app itself is
    portable by default regardless of install type"). Comparing the
    saved value against *both* modes' auto-computed defaults (not just
    the current one) tells an actual deliberate custom folder (respected
    always) apart from a stale snapshot of whichever default happened to
    be live the one time Settings was opened.
    """
    from radiomaster.utils.config import ConfigManager
    config = ConfigManager.get_instance()
    stored_value = config.get(config_section, config_key, default="").strip()
    if not stored_value:
        return current_default

    saved = resolve_stored_path(stored_value)

    stale_defaults = {os.path.normcase(os.path.normpath(current_default)),
                       os.path.normcase(os.path.normpath(music_default))}
    if os.path.normcase(os.path.normpath(saved)) in stale_defaults \
            and os.path.normpath(saved) != os.path.normpath(current_default):
        saved = current_default
    portable_value = path_for_storage(saved)
    if portable_value != stored_value:
        # ConfigManager is saved on normal shutdown (and when Settings is
        # accepted), so old absolute portable values migrate automatically.
        config.set(config_section, config_key, value=portable_value)
    return saved


def get_recordings_dir() -> str:
    """Settings > Recordings > Recording Location, self-healing against a
    stale saved value (see _self_healing_dir)."""
    app_name = __app_name__.replace("+", "Plus")
    music_default = os.path.join(os.path.expanduser("~"), "Music", app_name, "Recordings")
    return _self_healing_dir("recordings", "recording_path", str(get_paths()["recordings"]), music_default)


def get_downloads_dir() -> str:
    """Settings > Downloads > Download Location, self-healing against a
    stale saved value (see _self_healing_dir). Shared by YouTube
    downloads and (as the parent of get_podcasts_dir()'s own default)
    podcast episode downloads."""
    app_name = __app_name__.replace("+", "Plus")
    music_default = os.path.join(os.path.expanduser("~"), "Music", app_name)
    return _self_healing_dir("downloads", "download_path", str(get_paths()["downloads"]), music_default)


def get_podcasts_dir() -> str:
    """Settings > Podcasts > Podcast Download Location, self-healing
    against a stale saved value (see _self_healing_dir). Defaults to a
    "Podcasts" subfolder of get_downloads_dir() rather than its own
    independent portable/installed split -- it inherits the parent
    downloads location's own self-healing instead of duplicating it."""
    current_default = os.path.join(get_downloads_dir(), "Podcasts")
    app_name = __app_name__.replace("+", "Plus")
    music_default = os.path.join(os.path.expanduser("~"), "Music", app_name, "Podcasts")
    return _self_healing_dir("podcasts", "download_path", current_default, music_default)
