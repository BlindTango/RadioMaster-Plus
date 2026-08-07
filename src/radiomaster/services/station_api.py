"""Client for the Radio Browser free station database (https://www.radio-browser.info/)."""

from __future__ import annotations

import json
import logging
import socket
import time
from dataclasses import dataclass, asdict
from typing import Callable, Optional

import requests

from radiomaster import __app_name__, __version__
from radiomaster.utils.logging_setup import log_io

log = logging.getLogger("radiomaster")

DEFAULT_BASE_URLS = [
    "https://de1.api.radio-browser.info",
    "https://all.api.radio-browser.info",
    "https://at1.api.radio-browser.info",
]


def _discover_servers() -> list[str]:
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

USER_AGENT = f"{__app_name__}/{__version__}"

KNOWN_NETWORKS = [
    "BBC", "NPR", "iHeartRadio", "iHeart", "ABC", "CBC", "RTE", "RTÉ", "NRJ", "RTL",
    "Capital", "Heart", "Smooth", "Kiss", "Absolute Radio", "Absolute", "talkSPORT",
    "Virgin Radio", "SiriusXM", "Univision", "Audacy", "Radio.com", "Cumulus", "RCS",
    "Bauer", "Global", "Antenne", "Sunrise", "Classic FM", "Radio X", "LBC", "Magic",
    "Jazz FM", "Planet Rock",
]


def _strip_leading_the(name: str) -> str:
    stripped = name.strip()
    if stripped[:4].lower() == "the " and len(stripped) > 4:
        return stripped[4:].strip()
    return stripped


def _guess_network(tags: str, name: str) -> str:
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    for network in KNOWN_NETWORKS:
        network_lower = network.lower()
        if any(tag.lower() == network_lower for tag in tag_list):
            return network
        if name.lower().startswith(network_lower):
            return network
    return ""


@dataclass
class Station:
    uuid: str
    name: str
    url: str
    favicon: str = ""
    tags: str = ""
    country: str = ""
    language: str = ""
    codec: str = ""
    bitrate: int = 0
    votes: int = 0
    homepage: str = ""
    network: str = ""
    languagecodes: str = ""

    @property
    def genres(self) -> list[str]:
        return [t.strip() for t in self.tags.split(",") if t.strip()]

    @property
    def iso_languages(self) -> list[str]:
        """Canonical ISO 639 language name(s) for this station."""
        langs = []
        if self.language:
            for part in self.language.split(","):
                part = part.strip().title()
                if part:
                    langs.append(part)
        if not langs and self.languagecodes:
            for part in self.languagecodes.split(","):
                part = part.strip().title()
                if part:
                    langs.append(part)
        return langs if langs else ["Unknown"]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_api(cls, raw: dict) -> "Station":
        name = raw.get("name", "").strip() or "Unnamed Station"
        tags = raw.get("tags", "")
        return cls(
            uuid=raw.get("stationuuid", ""),
            name=name,
            url=raw.get("url_resolved") or raw.get("url", ""),
            favicon=raw.get("favicon", ""),
            tags=tags,
            country=_strip_leading_the(raw.get("country", "")),
            language=raw.get("language", ""),
            codec=raw.get("codec", ""),
            bitrate=int(raw.get("bitrate") or 0),
            votes=int(raw.get("votes") or 0),
            homepage=raw.get("homepage", ""),
            network=_guess_network(tags, name),
            languagecodes=raw.get("languagecodes", ""),
        )

    @classmethod
    def from_dict(cls, data: dict) -> "Station":
        return cls(**{k: data.get(k, "") for k in cls.__dataclass_fields__})


class StationAPIError(RuntimeError):
    pass


class StationAPI:
    """Thin HTTP client for the Radio Browser API; StationDB handles local caching."""

    def __init__(self, base_urls: Optional[list[str]] = None, proxies: Optional[dict] = None):
        if base_urls:
            self._base_urls = base_urls
        else:
            discovered = _discover_servers()
            seen: dict[str, None] = {}
            for url in discovered + DEFAULT_BASE_URLS:
                seen.setdefault(url, None)
            self._base_urls = list(seen.keys())
        self._session = requests.Session()
        from radiomaster.utils.network import get_user_agent, get_proxies
        self._session.headers["User-Agent"] = get_user_agent(USER_AGENT)
        self.proxies = proxies if proxies is not None else get_proxies()

    def set_proxies(self, proxies: Optional[dict]) -> None:
        self.proxies = proxies

    def _get(self, path: str, params: Optional[dict] = None, timeout: Optional[int] = None,
             retries: int = 1, retry_delay: float = 5.0,
             progress_cb: Optional[Callable[[int, Optional[int]], None]] = None) -> list:
        if timeout is None:
            from radiomaster.utils.network import get_timeout
            timeout = get_timeout(default=10)
        last_error: Exception | None = None
        for attempt in range(retries):
            for base in self._base_urls:
                try:
                    log_io(log, "GET %s params=%s", f"{base}{path}", params)
                    with self._session.get(
                        f"{base}{path}", params=params, timeout=timeout,
                        proxies=self.proxies, stream=progress_cb is not None,
                    ) as resp:
                        resp.raise_for_status()
                        log_io(log, "-> %s %s (%s bytes)", resp.status_code, resp.url,
                               resp.headers.get("Content-Length", "?"))
                        if progress_cb is None:
                            return resp.json()
                        total = resp.headers.get("Content-Length")
                        total = int(total) if total is not None else None
                        chunks = bytearray()
                        for chunk in resp.iter_content(chunk_size=65536):
                            chunks.extend(chunk)
                            progress_cb(len(chunks), total)
                        return json.loads(bytes(chunks))
                except (requests.RequestException, ValueError) as exc:
                    last_error = exc
                    continue
            if attempt < retries - 1:
                log.warning("Radio Browser request failed on all servers (attempt %d/%d): %s — retrying",
                            attempt + 1, retries, last_error)
                time.sleep(retry_delay)
        log.warning("Radio Browser unreachable on every mirror after %d attempt(s): %s", retries, last_error)
        raise StationAPIError(
            "Could not reach the Radio Browser station database — check your internet "
            "connection, or firewall/VPN settings if one is active."
        )

    def search(self, name: str, limit: int = 100) -> list[Station]:
        raw = self._get("/json/stations/search", {"name": name, "limit": limit})
        return [Station.from_api(r) for r in raw]

    def bulk_stations(self, limit: int = 100000,
                       progress_cb: Optional[Callable[[int, Optional[int]], None]] = None) -> list[Station]:
        raw = self._get(
            "/json/stations",
            {"limit": limit, "order": "name", "hidebroken": "true"},
            timeout=120, retries=3, retry_delay=8.0, progress_cb=progress_cb,
        )
        return [Station.from_api(r) for r in raw]

    def click(self, station_uuid: str) -> None:
        try:
            self._session.get(
                f"{self._base_urls[0]}/json/url/{station_uuid}", timeout=5, proxies=self.proxies
            )
        except requests.RequestException:
            pass
