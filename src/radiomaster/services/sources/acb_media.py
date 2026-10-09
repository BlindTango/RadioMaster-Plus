"""ACB Media station source: the American Council of the Blind's network.

Ten live streams run by and for the blind community -- exactly the
audience RadioMaster+ is built for, and exactly the kind of source Quill
Radio ships in its own catalog. The stream URLs are stable Live365
endpoints published on each stream's page (acbmedia.org/media1 through
/media10); they are bundled here as a fixed list so the source answers
with no network at all, like Quill's NFB Radio branch.

No search: a ten-channel list is browsable in one glance, and a source
with no search of its own offers no search item rather than one that
pretends.
"""

from __future__ import annotations

from radiomaster.services.sources.base import (
    SourceCapabilities,
    SourceNode,
    SourceUnavailable,
    StationRef,
    StationSource,
)

#: (stream number, name, description, live365 endpoint) -- verified
#: against each stream's own page (the <source src=...> element).
_STREAMS = [
    (1, "ACB Media 1", "Flagship station of the ACB Media Network",
     "https://streaming.live365.com/a11911"),
    (2, "ACB Media 2", "Flagship station of the ACB Media Network",
     "https://streaming.live365.com/a27778"),
    (3, "ACB Media 3", "Old time radio station of the ACB Media Network",
     "https://streaming.live365.com/a17972"),
    (4, "ACB Media 4", "Flagship music station of the ACB Media Network",
     "https://streaming.live365.com/a89697"),
    (5, "ACB Media 5", "Flagship community station of the ACB Media Network",
     "https://streaming.live365.com/a46090"),
    (6, "ACB Media 6", "Live event station of the ACB Media Network",
     "https://streaming.live365.com/a36240"),
    (7, "ACB Media 7", "Live event station of the ACB Media Network",
     "https://streaming.live365.com/a95398"),
    (8, "ACB Media 8", "Live event station of the ACB Media Network",
     "https://streaming.live365.com/a18975"),
    (9, "ACB Media 9", "Live event station of the ACB Media Network",
     "https://streaming.live365.com/a44175"),
    (10, "ACB Media 10", "Convention coverage of the ACB Media Network",
     "https://streaming.live365.com/a85327"),
]


class ACBMediaSource(StationSource):
    id = "acb_media"
    label = "ACB Media"
    capabilities = SourceCapabilities(searchable=False, browsable=True, offline=True)

    def browse(self, path: str = "") -> list[SourceNode]:
        if path:
            # A flat list has no children -- asking for any is a caller
            # bug, but answering empty is safer than raising for a source
            # whose whole tree is one level.
            return []
        return [
            SourceNode(
                label=f"{name}: {description}",
                path=f"stream:{number}",
                station=StationRef(
                    name=name,
                    url=url,
                    source_id=self.id,
                    homepage=f"https://acbmedia.org/home/streams/media{number}/",
                    note="Blind-community radio from the American Council of the Blind",
                ),
                note="Blind-community radio",
            )
            for number, name, description, url in _STREAMS
        ]

    def search(self, query: str) -> list[SourceNode]:
        # Not searchable by design -- see the module docstring.
        raise SourceUnavailable(self.label, "This source has no search.")