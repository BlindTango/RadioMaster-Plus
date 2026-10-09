"""Registry of every station source RadioMaster+ knows about.

The registry is the single place the UI asks "which sources exist and
which does this user want?" -- the Choose Browse Sources dialog edits the
config key, the browse tree and search fanout read the answer here. A
source that ships disabled by default still appears in the dialog (the
user can turn it on); a source id unknown to the registry is ignored
rather than crashing on a stale config value.
"""

from __future__ import annotations

import logging
from typing import Optional

from radiomaster.services.sources.base import StationSource, describe_source

log = logging.getLogger("radiomaster")

#: Config key holding the list of enabled source ids (JSON list of
#: strings via ConfigManager; sources absent from the list are disabled).
CONFIG_KEY = "radio.enabled_sources"

#: Source ids enabled unless the user says otherwise. Radio Browser is
#: the historical whole catalog; the curated extras are on by default
#: because they are small, offline-capable, and immediately useful.
DEFAULT_ENABLED = ["radio_browser", "somafm", "acb_media", "internet_archive"]


class SourceRegistry:
    """Owns source instances and their enablement."""

    def __init__(self, config, cache_dir: str):
        self._config = config
        self._cache_dir = cache_dir
        self._sources: dict[str, StationSource] = {}
        self._build()

    def _build(self) -> None:
        """Instantiate every known source. Kept lazy-failure tolerant: a
        source whose constructor fails (e.g. a missing cache dir) is
        logged and skipped, not fatal -- one broken source must never
        take the whole radio tab down with it."""
        from radiomaster.services.sources.somafm import SomaFMSource
        from radiomaster.services.sources.acb_media import ACBMediaSource
        from radiomaster.services.sources.internet_archive import InternetArchiveSource

        for factory in (
            lambda: SomaFMSource(self._cache_dir),
            ACBMediaSource,
            InternetArchiveSource,
        ):
            try:
                source = factory()
                self._sources[source.id] = source
            except Exception:
                log.warning("Could not initialize station source", exc_info=True)

    def all_sources(self) -> list[StationSource]:
        """Every registered source, in stable registration order."""
        return list(self._sources.values())

    def enabled_ids(self) -> list[str]:
        """Source ids the user has enabled (config value, else defaults).

        Unknown ids in the config are dropped silently -- they are stale
        values from removed sources, not a user error worth a message.
        """
        raw = self._config.get(CONFIG_KEY, default=None)
        if raw is None:
            return [sid for sid in DEFAULT_ENABLED if sid in self._sources]
        if isinstance(raw, str):
            # ConfigManager may hand back a JSON-encoded list.
            import json
            try:
                raw = json.loads(raw)
            except ValueError:
                return [sid for sid in DEFAULT_ENABLED if sid in self._sources]
        if not isinstance(raw, list):
            return [sid for sid in DEFAULT_ENABLED if sid in self._sources]
        return [sid for sid in raw if sid in self._sources]

    def enabled_sources(self) -> list[StationSource]:
        return [self._sources[sid] for sid in self.enabled_ids()]

    def get(self, source_id: str) -> Optional[StationSource]:
        return self._sources.get(source_id)

    def set_enabled_ids(self, ids: list[str]) -> None:
        """Persist the user's Choose Browse Sources selection."""
        self._config.set(CONFIG_KEY, value=[sid for sid in ids if sid in self._sources])

    def describe_all(self) -> list[str]:
        """One sentence per source, for Catalog Status."""
        return [describe_source(s) for s in self.all_sources()]