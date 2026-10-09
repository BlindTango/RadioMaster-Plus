"""SomaFM station source: a curated, listener-supported independent network.

SomaFM publishes its whole channel list as one JSON document
(https://api.somafm.com/channels.json) with direct .pls playlist URLs per
channel. That makes it the ideal first "extra" source for the multi-source
catalog: the list is small (a few dozen channels), the URLs are stable, and
the whole thing can be cached to disk so the source keeps working offline
-- the same contract Quill Radio gives its fixed-list sources.

The .pls files themselves are fetched by the playback engine at play time
(bass_host already understands audio/x-scpls), so this source only ever
hands out playlist URLs, never re-hosts streams.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional

import requests

from radiomaster.services.sources.base import (
    SourceCapabilities,
    SourceNode,
    SourceUnavailable,
    StationRef,
    StationSource,
)

log = logging.getLogger("radiomaster")

CHANNELS_URL = "https://api.somafm.com/channels.json"
#: How long a cached channel list stays fresh before a refresh is wanted.
CACHE_TTL_SECONDS = 7 * 24 * 3600  # one week


class SomaFMSource(StationSource):
    id = "somafm"
    label = "SomaFM"
    capabilities = SourceCapabilities(searchable=True, browsable=True, offline=True)

    def __init__(self, cache_dir: str, proxies: Optional[dict] = None,
                 timeout: int = 15):
        self._cache_path = os.path.join(cache_dir, "somafm_channels.json")
        self._proxies = proxies or {}
        self._timeout = timeout
        self._channels: list[dict] = []
        self._loaded = False

    # -- cache -----------------------------------------------------------

    def _load_cache(self) -> None:
        """Populate the channel list from disk cache, then network.

        The cache is the source of truth for offline browsing: if it is
        present, the source answers even with no network (stale beats
        silent). Only a missing/expired cache triggers a network fetch,
        and a failed fetch with no cache at all raises -- the honest
        "could not be reached" sentence, never an invented empty list.
        """
        if self._loaded:
            return
        self._loaded = True
        self._channels = self._read_cache()
        if self._channels and not self._cache_expired():
            return
        try:
            fetched = self._fetch_channels()
        except SourceUnavailable:
            # A stale cache still answers; only a total absence fails.
            if not self._channels:
                raise
            return
        self._channels = fetched
        self._write_cache(fetched)

    def _read_cache(self) -> list[dict]:
        try:
            with open(self._cache_path, "r", encoding="utf-8") as f:
                blob = json.load(f)
            return blob.get("channels", [])
        except (OSError, ValueError):
            return []

    def _cache_expired(self) -> bool:
        try:
            mtime = os.path.getmtime(self._cache_path)
        except OSError:
            return True
        return (time.time() - mtime) > CACHE_TTL_SECONDS

    def _write_cache(self, channels: list[dict]) -> None:
        try:
            os.makedirs(os.path.dirname(self._cache_path), exist_ok=True)
            with open(self._cache_path, "w", encoding="utf-8") as f:
                json.dump({"channels": channels, "cached_at": time.time()}, f)
        except OSError:
            log.warning("Could not write SomaFM channel cache", exc_info=True)

    def _fetch_channels(self) -> list[dict]:
        from radiomaster.utils.network import get_proxies, get_user_agent
        try:
            resp = requests.get(
                CHANNELS_URL, timeout=self._timeout,
                proxies=self._proxies or get_proxies(),
                headers={"User-Agent": get_user_agent("RadioMaster+")},
            )
            resp.raise_for_status()
            return resp.json().get("channels", [])
        except (requests.RequestException, ValueError) as exc:
            raise SourceUnavailable(
                self.label, "Check your internet connection and try again."
            ) from exc

    # -- StationSource ----------------------------------------------------

    def refresh(self) -> None:
        """Force a network re-fetch (used by Update Now)."""
        self._loaded = False
        self._channels = []
        try:
            os.remove(self._cache_path)
        except OSError:
            pass
        self._load_cache()

    def browse(self, path: str = "") -> list[SourceNode]:
        self._load_cache()
        if not path:
            # Root: one folder per genre, plus an "All Channels" leaf set.
            genres: dict[str, list[dict]] = {}
            for ch in self._channels:
                genre = (ch.get("genre") or "other").strip().title() or "Other"
                genres.setdefault(genre, []).append(ch)
            nodes = [
                SourceNode(label=genre, path=f"genre:{genre}", has_children=True)
                for genre in sorted(genres, key=str.lower)
            ]
            return nodes
        if path.startswith("genre:"):
            genre = path[len("genre:"):].lower()
            return [
                self._node_for_channel(ch)
                for ch in self._channels
                if (ch.get("genre") or "other").strip().lower() == genre
            ]
        raise SourceUnavailable(self.label, "That folder does not exist.")

    def search(self, query: str) -> list[SourceNode]:
        self._load_cache()
        needle = query.strip().lower()
        if not needle:
            return []
        results = []
        for ch in self._channels:
            haystack = " ".join([
                ch.get("title", ""), ch.get("genre", ""), ch.get("description", ""),
                ch.get("dj", ""),
            ]).lower()
            if needle in haystack:
                results.append(self._node_for_channel(ch))
        return results

    # -- helpers -----------------------------------------------------------

    def _node_for_channel(self, channel: dict) -> SourceNode:
        """One channel -> one playable node. Prefers the highest-quality
        MP3 playlist (broadest codec support in the engine); falls back
        to the first playlist offered."""
        playlists = channel.get("playlists") or []
        url = ""
        for pl in playlists:
            if pl.get("format") == "mp3":
                url = pl.get("url", "")
                break
        if not url and playlists:
            url = playlists[0].get("url", "")
        title = channel.get("title", "").strip() or channel.get("id", "Channel")
        return SourceNode(
            label=title,
            path=f"channel:{channel.get('id', '')}",
            station=StationRef(
                name=f"SomaFM {title}",
                url=url,
                source_id=self.id,
                homepage=f"https://somafm.com/{channel.get('id', '')}/",
                tags=channel.get("genre", ""),
                note="Listener-supported independent radio",
            ),
            note="Listener-supported independent radio",
        )