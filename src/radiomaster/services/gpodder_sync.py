"""gpodder.net sync service for podcast subscriptions."""

import logging
import requests
from typing import Any

logger = logging.getLogger("radiomaster")


class GpodderSync:
    """Sync podcast subscriptions with gpodder.net."""

    API_BASE = "https://gpodder.net"

    def __init__(self, username: str = "", password: str = "") -> None:
        self._username = username
        self._password = password
        self._session = requests.Session()
        from radiomaster.utils.network import apply_to_session
        apply_to_session(self._session, "RadioMaster+/1.0")
        if username and password:
            self._session.auth = (username, password)

    def set_credentials(self, username: str, password: str) -> None:
        """Set gpodder.net credentials."""
        self._username = username
        self._password = password
        self._session.auth = (username, password)

    @staticmethod
    def _get_timeout() -> float:
        from radiomaster.utils.network import get_timeout
        return get_timeout(default=10)

    def get_subscriptions(self, device: str = "default") -> list[dict[str, Any]]:
        """Get podcast subscriptions from gpodder.net."""
        if not self._username:
            logger.warning("gpodder.net credentials not configured")
            return []
        try:
            url = f"{self.API_BASE}/subscriptions/{self._username}/{device}.json"
            resp = self._session.get(url, timeout=self._get_timeout())
            if resp.status_code == 200:
                return resp.json().get("subscriptions", [])
        except Exception as e:
            logger.error(f"Failed to get subscriptions: {e}")
        return []

    def upload_subscriptions(self, urls: list[str], device: str = "default") -> bool:
        """Upload podcast subscriptions to gpodder.net."""
        if not self._username:
            logger.warning("gpodder.net credentials not configured")
            return False
        try:
            url = f"{self.API_BASE}/subscriptions/{self._username}/{device}.json"
            resp = self._session.put(url, json={"add": urls}, timeout=self._get_timeout())
            return resp.status_code in (200, 201)
        except Exception as e:
            logger.error(f"Failed to upload subscriptions: {e}")
            return False

    def get_device_list(self) -> list[dict[str, Any]]:
        """Get list of devices associated with the account."""
        if not self._username:
            return []
        try:
            url = f"{self.API_BASE}/devices/{self._username}.json"
            resp = self._session.get(url, timeout=self._get_timeout())
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.error(f"Failed to get devices: {e}")
        return []

    def update_episode_action(self, podcast_url: str, episode_url: str,
                               action: str, device: str = "default") -> bool:
        """Update episode status (download, play, etc.)."""
        if not self._username:
            return False
        try:
            url = f"{self.API_BASE}/api/2/events/{self._username}/{device}.json"
            data = [{
                "podcast": podcast_url,
                "episode": episode_url,
                "action": action,
                "timestamp": int(__import__("time").time()),
            }]
            resp = self._session.post(url, json=data, timeout=self._get_timeout())
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"Failed to update episode action: {e}")
            return False
