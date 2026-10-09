"""Browse Archive audio collections and play files listed by its metadata API."""

from __future__ import annotations
from urllib.parse import quote
import requests
from radiomaster.services.sources.base import (
    SourceCapabilities,
    SourceNode,
    SourceUnavailable,
    StationRef,
    StationSource,
)

SEARCH_URL = "https://archive.org/advancedsearch.php"
DEFAULT_QUERY = "mediatype:audio AND (collection:etree OR collection:radio OR collection:audio_music OR collection:audio_foreign)"
COLLECTIONS = {
    "etree": "Live Music Archive",
    "radio": "Old Time Radio",
    "audio_music": "Music",
    "audio_foreign": "International Audio",
}


def _text(value):
    return (
        ", ".join(str(part) for part in value)
        if isinstance(value, list)
        else str(value or "").strip()
    )


class InternetArchiveSource(StationSource):
    id = "internet_archive"
    label = "Internet Archive"
    capabilities = SourceCapabilities(searchable=True, browsable=True, offline=False)
    PAGE_SIZE = 25

    def __init__(self, proxies=None, timeout=20):
        self._proxies = proxies or {}
        self._timeout = timeout

    def _get(self, url, params=None):
        from radiomaster.utils.network import get_proxies, get_user_agent

        try:
            response = requests.get(
                url,
                params=params,
                timeout=self._timeout,
                proxies=self._proxies or get_proxies(),
                headers={"User-Agent": get_user_agent("RadioMaster+")},
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict) or data.get("error"):
                raise ValueError("Archive returned no usable metadata")
            return data
        except (requests.RequestException, ValueError) as exc:
            raise SourceUnavailable(self.label, "Check your connection and try again.") from exc

    def _items(self, query, page=1, collection=""):
        response = self._get(
            SEARCH_URL,
            {
                "q": query,
                "fl[]": ["identifier", "title", "creator"],
                "rows": self.PAGE_SIZE,
                "page": page,
                "output": "json",
            },
        ).get("response", {})
        nodes = []
        for doc in response.get("docs", []):
            identifier = _text(doc.get("identifier"))
            if not identifier:
                continue
            title = _text(doc.get("title")) or identifier
            creator = _text(doc.get("creator"))
            nodes.append(
                SourceNode(
                    label=f"{title} — {creator}" if creator and creator != title else title,
                    path=f"item:{identifier}",
                    has_children=True,
                    note="Open to choose an audio track",
                )
            )
        if collection:
            nodes.insert(0, SourceNode("Back to collections", "", has_children=True))
            if page > 1:
                nodes.append(
                    SourceNode(
                        "Previous page", f"collection:{collection}:{page - 1}", has_children=True
                    )
                )
            if page * self.PAGE_SIZE < int(response.get("numFound", 0)):
                nodes.append(
                    SourceNode(
                        "Next page", f"collection:{collection}:{page + 1}", has_children=True
                    )
                )
        return nodes

    def search(self, query):
        if not query.strip():
            return []
        return self._items(f"({DEFAULT_QUERY}) AND ({query.strip()})")

    def browse(self, path=""):
        if not path:
            return [
                SourceNode(label, f"collection:{key}:1", has_children=True)
                for key, label in COLLECTIONS.items()
            ]
        if path.startswith("collection:"):
            _, collection, page = path.split(":", 2)
            if collection not in COLLECTIONS or not page.isdigit() or int(page) < 1:
                raise SourceUnavailable(self.label, "That collection does not exist.")
            return self._items(
                f"mediatype:audio AND collection:{collection}", int(page), collection
            )
        if not path.startswith("item:"):
            raise SourceUnavailable(self.label, "That folder does not exist.")
        identifier = path[5:]
        metadata = self._get(f"https://archive.org/metadata/{quote(identifier, safe='')}")
        if metadata.get("is_dark") or metadata.get("nodownload"):
            raise SourceUnavailable(self.label, "This item is not available for streaming.")
        info = metadata.get("metadata", {})
        title = _text(info.get("title")) or identifier
        creator = _text(info.get("creator"))
        license_note = _text(info.get("licenseurl"))
        note = f"License: {license_note}" if license_note else "Check the item page for usage terms"
        files = sorted(
            metadata.get("files", []),
            key=lambda f: (not _text(f.get("name")).lower().endswith(".mp3"), _text(f.get("name"))),
        )
        nodes = [SourceNode("Back to collections", "", has_children=True)]
        seen = set()
        for file in files:
            name = _text(file.get("name"))
            if str(file.get("private", "")).lower() in ("true", "1") or not name.lower().endswith(
                (".mp3", ".ogg", ".flac", ".m4a", ".wav", ".opus", ".aac", ".wma", ".aiff")
            ):
                continue
            original = _text(file.get("original")) or name
            key = original.rsplit(".", 1)[0]
            if key in seen:
                continue
            seen.add(key)
            track = _text(file.get("title")) or name
            ref = StationRef(
                name=f"{title} — {track}",
                url=f"https://archive.org/download/{quote(identifier, safe='')}/{quote(name, safe='/')}",
                source_id=self.id,
                homepage=f"https://archive.org/details/{quote(identifier, safe='')}",
                tags=creator,
                note=note,
                is_live=False,
            )
            nodes.append(SourceNode(track, f"file:{name}", station=ref, note=note))
        if len(nodes) == 1:
            raise SourceUnavailable(self.label, "This item has no playable audio files.")
        return nodes
