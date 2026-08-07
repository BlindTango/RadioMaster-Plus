"""Update checker service for RadioMaster+."""

import requests
import logging
from typing import Any
from radiomaster import __version__, __app_name__

logger = logging.getLogger("radiomaster")


class UpdateChecker:
    """Checks for new versions of RadioMaster+."""

    UPDATE_URL = "https://api.github.com/repos/radiomaster/radiomaster-plus/releases/latest"

    @staticmethod
    def check() -> dict[str, Any] | None:
        """Check for updates. Returns update info or None."""
        try:
            resp = requests.get(UpdateChecker.UPDATE_URL, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                latest_version = data.get("tag_name", "").lstrip("v")
                if latest_version and latest_version > __version__:
                    return {
                        "version": latest_version,
                        "url": data.get("html_url", ""),
                        "body": data.get("body", ""),
                        "published": data.get("published_at", ""),
                    }
        except Exception as e:
            logger.debug(f"Update check failed: {e}")
        return None
