"""Multi-source station catalog framework.

RadioMaster+ started life speaking only to the Radio Browser database.
Quill Radio's structural advantage is its source abstraction: every place
a station can come from implements one contract, so Browse and Search can
fan out across all of them and the user chooses which branches exist.

This module defines that contract for RadioMaster+. A source is:

- identified (``id``) and labelled (``label``) for config and menus;
- honest about what it can do (``capabilities``) -- a source with no
  search of its own offers no search, one that works offline says so;
- lazy (``browse`` returns the children of one path at a time) so the UI
  never waits on a whole catalog it may never open;
- specific when it fails: :class:`SourceUnavailable` carries its own
  user-facing sentence, because "invalid" and silence are the failure
  modes this exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


class SourceUnavailable(RuntimeError):
    """A source could not be reached or refused the request.

    The message is user-facing: it is spoken as-is (status bar / dialog),
    so it must name the source and say what went wrong in words.
    """

    def __init__(self, source_label: str, reason: str):
        super().__init__(f"{source_label} could not be reached. {reason}")
        self.source_label = source_label
        self.reason = reason


@dataclass(frozen=True)
class SourceCapabilities:
    """What a source can do. Absent capabilities are simply not offered
    in the UI -- a source with ``searchable=False`` gets no "Search This
    Source" item rather than one that fails when pressed."""

    searchable: bool = False
    browsable: bool = False
    #: Answers from local storage (SQLite or a bundled list) without any
    #: network request. Surfaced in the UI as "works offline".
    offline: bool = False


@dataclass
class SourceNode:
    """One row in a source's browse tree, or one result of a search.

    ``path`` is opaque to everything except the source that produced it:
    the UI passes it back to ``browse()`` unchanged, so each source is
    free to structure its own tree (a flat list, genre folders, a single
    "all" node) without the framework dictating a shape.
    """

    label: str
    path: str
    #: Present when this node is itself playable (a station leaf).
    station: Optional["StationRef"] = None
    #: Present when this node has children worth fetching (a folder).
    has_children: bool = False
    #: Extra spoken context for the row, e.g. "opens on Mixcloud in your
    #: browser" -- the row carries its own truth before Enter is pressed.
    note: str = ""


@dataclass
class StationRef:
    """A playable station, normalized across sources.

    Deliberately not the Radio Browser ``Station`` dataclass: sources that
    have no uuid/votes/codec must not be forced to invent them. The radio
    panel converts a StationRef into whatever its playback path needs.
    """

    name: str
    url: str
    source_id: str
    is_live: bool = True
    homepage: str = ""
    tags: str = ""
    #: Human sentence describing licensing/permission for this item, e.g.
    #: "Public domain" or "opens on Mixcloud in your browser". Spoken in
    #: the row so the user knows what Enter will do before pressing it.
    note: str = ""


class StationSource:
    """Base class for every station source. Subclasses set the class
    attributes and implement the methods their capabilities advertise."""

    #: Stable identifier used in config keys (never rename one that has
    #: shipped -- it would silently reset users' Choose Browse Sources).
    id: str = ""
    #: Spoken label shown in the tree and menus.
    label: str = ""
    capabilities: SourceCapabilities = SourceCapabilities()

    def browse(self, path: str = "") -> list[SourceNode]:
        """Return the children of ``path`` ("" = the root).

        Raise :class:`SourceUnavailable` with a source-specific sentence
        when the source cannot answer. Must not block for long -- the UI
        calls this on a worker thread and shows a "Loading..." row until
        it returns.
        """
        raise SourceUnavailable(self.label, "This source has no browse.")

    def search(self, query: str) -> list[SourceNode]:
        """Return results for ``query``. Only called when
        ``capabilities.searchable`` is True."""
        raise SourceUnavailable(self.label, "This source has no search.")

    def refresh(self) -> None:
        """Re-fetch anything the source caches locally (no-op by
        default). Called by "Update Now" style UI affordances."""
        return None


def describe_source(source: StationSource) -> str:
    """One sentence for Catalog Status / Choose Browse Sources: what the
    source is and whether it works offline."""
    offline = "works offline" if source.capabilities.offline else "needs the internet"
    return f"{source.label} ({offline})"
