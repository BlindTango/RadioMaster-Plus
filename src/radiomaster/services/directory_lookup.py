"""Look up a station website in the public Radio Browser catalog.

Nothing about the entered address leaves the computer: the catalog is already
stored locally, so this matches the website against stored station homepages
and then checks that each candidate stream really plays.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.parse import urlsplit

from radiomaster.services.stream_discovery import DiscoveredStream, _http_url
from radiomaster.services.stream_prober import format_stream_format, probe_stream_format


@dataclass(frozen=True)
class DirectoryResult:
    streams: tuple[DiscoveredStream, ...]
    candidates: int = 0
    catalog_empty: bool = False
    cancelled: bool = False
    error: str = ""


def _site(url: str) -> tuple[str, str]:
    """(host without www, path without trailing slash) for comparing websites."""
    parts = urlsplit(url if "//" in url else "//" + url)
    host = (parts.hostname or "").lower()
    for prefix in ("www.", "m."):
        if host.startswith(prefix):
            host = host[len(prefix):]
    return host, parts.path.rstrip("/").lower()


def matching_stations(stations, website: str):
    """Stations on the same website. A page below the site root only matches
    stations registered for that page, never the rest of the site: a channel
    page must not turn up unrelated stations from the same broadcaster."""
    host, path = _site(website)
    matched = []
    for station in stations:
        s_host, s_path = _site(station.homepage or "")
        if s_host != host:
            continue
        if path and s_path != path and not s_path.startswith(path + "/"):
            continue
        matched.append(station)
    return matched


def lookup_by_website(website: str, *, db=None, cancel: threading.Event | None = None,
                      limit: int = 12) -> DirectoryResult:
    """Playable catalog streams for *website*. Runs on a worker thread."""
    start = _http_url(website)
    if not start:
        raise ValueError("Enter a complete HTTP or HTTPS webpage URL.")
    cancel = cancel or threading.Event()
    if db is None:
        from radiomaster.services.station_db import StationDB
        db = StationDB()
    if db.station_count() == 0:
        return DirectoryResult((), catalog_empty=True)
    host, _ = _site(start)
    candidates = matching_stations(db.stations_by_website(host), start)[:limit]
    seen: set[str] = set()
    unique = []
    for station in candidates:
        if station.url and station.url not in seen:
            seen.add(station.url)
            unique.append(station)

    def verify(station):
        if cancel.is_set():
            return None
        return station, probe_stream_format(station.url)

    found: list[DiscoveredStream] = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for outcome in pool.map(verify, unique):
            if outcome and outcome[1]:
                station, fmt = outcome
                label = f"{station.name} ({format_stream_format(fmt)})"
                found.append(DiscoveredStream(station.url, label, "Radio Browser"))
    return DirectoryResult(tuple(found), len(unique), cancelled=cancel.is_set())
