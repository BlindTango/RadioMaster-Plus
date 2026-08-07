"""Path resolution for RadioMaster+."""

import os
from platformdirs import user_config_dir, user_data_dir, user_cache_dir

from radiomaster import __app_name__


def get_paths() -> dict[str, str]:
    """Get platform-appropriate paths for config, data, and cache.

    If the ``--portable`` flag was passed on the command line, or if a
    ``portable.txt`` file exists next to the application, paths are
    resolved relative to the application directory instead of using
    platformdirs.
    """
    app_name = __app_name__.replace("+", "Plus")

    # Check for portable mode
    import sys
    portable = "--portable" in sys.argv or os.path.exists(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "portable.txt")
    )

    if portable:
        base = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data")
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
