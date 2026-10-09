"""Internet Archive station source: searchable public audio collections.

The Internet Archive's advancedsearch API answers keyword queries over
millions of public audio items. For RadioMaster+ this is the "long tail"
source Quill Radio gets from its Internet Archive branch: live concert
recordings (the etree/Live Music Archive collection), old time radio,
public-domain music -- items that are legal to stream and download, which
the row says out loud ("Public domain or Creative Commons").

Search-only by design: the Archive's browse tree is enormous and its
facets change shape; a keyword search is the honest, useful surface. The
row's note carries the licence truth before Enter is pressed.
"""

from __future__ import annotations

import logging
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

SEARCH_URL = "https://archive.org/advancedsearch.php"
#: Restrict to audio items that actually stream: mediatype audio, and
#: only collections known to publish streamable derivatives (etree is the
#: Live Music Archive; radio is the Old Time Radio collection). Without
#: the collection restriction the results drown in non-streamable uploads.
DEFAULT_QUERY = (
    'mediatype:audio AND (collection:etree OR collection:radio OR '
    'collection:audio_music OR collection:audio_foreign)'
)


class InternetArchiveSource(StationSource):
    id = "internet_archive"
    label = "Internet Archive"
    capabilities = SourceCapabilities(searchable=True, browsable=False, offline=False)

    def __init__(self, proxies: Optional[dict] = None, timeout: int = 20):
        self._proxies = proxies or {}
        self._timeout = timeout

    def search(self, query: str) -> list[SourceNode]:
        needle = query.strip()
        if not needle:
            return []
        from radiomaster.utils.network import get_proxies, get_user_agent
        params = {
            "q": f"({DEFAULT_QUERY}) AND ({needle})",
            "fl[]": ["identifier", "title", "creator"],
            "rows": 25,
            "page": 1,
            "output": "json",
        }
        try:
            resp = requests.get(
                SEARCH_URL, params=params, timeout=self._timeout,
                proxies=self._proxies or get_proxies(),
                headers={"User-Agent": get_user_agent("RadioMaster+")},
            )
            resp.raise_for_status()
            docs = resp.json().get("response", {}).get("docs", [])
        except (requests.RequestException, ValueError) as exc:
            raise SourceUnavailable(
                self.label, "Check your internet connection and try again."
            ) from exc
        nodes = []
        for doc in docs:
            identifier = doc.get("identifier", "")
            if not identifier:
                continue
            title = (doc.get("title") or identifier).strip()
            creator = (doc.get("creator") or "").strip()
            label = f"{title} — {creator}" if creator and creator != title else title
            nodes.append(SourceNode(
                label=label,
                path=f"item:{identifier}",
                station=StationRef(
                    name=title,
                    # The Archive serves a direct MP3 derivative at this
                    # well-known URL shape for streamable audio items.
                    url=f"https://archive.org/download/{identifier}/{identifier}_vbr.mp3",
                    source_id=self.id,
                    homepage=f"https://archive.org/details/{identifier}",
                    tags=creator,
                    note="Public domain or Creative Commons",
                ),
                note="Public domain or Creative Commons",
            ))
        return nodes

    def browse(self, path: str = "") -> list[SourceNode]:
        # Search-only by design -- see the module docstring.
        raise SourceUnavailable(self.label, "This source answers search only.")