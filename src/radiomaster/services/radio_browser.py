"""Free Radio Browser API client for fetching station data."""

import socket
import requests
import logging
from typing import Any

logger = logging.getLogger("radiomaster")

# Fallback mirrors if DNS discovery fails
DEFAULT_BASE_URLS = [
    "https://de1.api.radio-browser.info",
    "https://all.api.radio-browser.info",
    "https://at1.api.radio-browser.info",
]


def _discover_servers() -> list[str]:
    """Discover live Radio Browser mirrors via DNS."""
    servers: list[str] = []
    try:
        infos = socket.getaddrinfo("all.api.radio-browser.info", 443, proto=socket.IPPROTO_TCP)
    except OSError:
        return servers
    for ip in {info[4][0] for info in infos}:
        try:
            host, _, _ = socket.gethostbyaddr(ip)
        except OSError:
            continue
        servers.append(f"https://{host}")
    return servers


class RadioBrowserClient:
    """Client for the Free Radio Browser community API."""

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "RadioMaster+/1.0",
            "Content-Type": "application/json",
        })
        discovered = _discover_servers()
        seen: dict[str, None] = {}
        for url in discovered + DEFAULT_BASE_URLS:
            seen.setdefault(url, None)
        self._base_urls = list(seen.keys())

    def _get(self, path: str, params: dict | None = None, timeout: int = 15) -> list[dict[str, Any]]:
        """Try each base URL until one succeeds."""
        for base in self._base_urls:
            try:
                resp = self._session.get(f"{base}{path}", params=params, timeout=timeout)
                if resp.status_code == 200:
                    return resp.json()
            except Exception:
                continue
        return []

    def fetch_stations(self, limit: int = 10000, offset: int = 0) -> list[dict[str, Any]]:
        """Fetch all stations from the API."""
        return self._get(f"/json/stations?limit={limit}&offset={offset}", timeout=60)

    def search_stations(self, query: str, limit: int = 100) -> list[dict[str, Any]]:
        """Search for stations by name."""
        return self._get(f"/json/stations/byname/{query}?limit={limit}")

    def get_by_country(self, country: str, limit: int = 500) -> list[dict[str, Any]]:
        """Get stations by country."""
        return self._get(f"/json/stations/bycountry/{country}?limit={limit}")

    def get_by_language(self, language: str, limit: int = 500) -> list[dict[str, Any]]:
        """Get stations by language."""
        return self._get(f"/json/stations/bylanguage/{language}?limit={limit}")

    def get_by_tag(self, tag: str, limit: int = 500) -> list[dict[str, Any]]:
        """Get stations by genre/tag."""
        return self._get(f"/json/stations/bytag/{tag}?limit={limit}")

    def get_countries(self) -> list[str]:
        """Get list of available countries."""
        data = self._get("/json/countries")
        return [c["name"] for c in data if c.get("name")]

    def get_languages(self) -> list[str]:
        """Get list of available languages."""
        data = self._get("/json/languages")
        return [l["name"] for l in data if l.get("name")]

    def get_tags(self) -> list[str]:
        """Get list of available tags/genres."""
        data = self._get("/json/tags")
        return [t["name"] for t in data if t.get("name")]
