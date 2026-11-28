"""Where a recording schedule can get its address from, so it never has to be typed.

A schedule needs a stream or audio address, a title and a source type. These helpers
turn what the listener already has (the item playing now, a station, a podcast
episode) into exactly that.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

SOURCE_STATION = "Radio Station"
SOURCE_PODCAST = "Podcast"
SOURCE_AUDIOBOOK = "Audiobook"


@dataclass(frozen=True)
class SourcePick:
    url: str
    title: str
    source_type: str


def _online(url: str) -> bool:
    return (url or "").lower().startswith(("http://", "https://"))


def pick_from_station(station) -> SourcePick | None:
    """A station as a schedule source, or None when it has no online address."""
    url = (getattr(station, "url", "") or "").strip()
    if not _online(url):
        return None
    return SourcePick(url, (getattr(station, "name", "") or url).strip(), SOURCE_STATION)


def pick_from_episode(show: dict[str, Any], episode: dict[str, Any]) -> SourcePick | None:
    """A podcast episode's audio as a schedule source."""
    url = (episode.get("audio_url") or "").strip()
    if not _online(url):
        return None
    show_title = (show.get("title") or "").strip()
    episode_title = (episode.get("title") or "").strip() or "Episode"
    return SourcePick(url, f"{show_title}: {episode_title}" if show_title else episode_title,
                      SOURCE_PODCAST)


def pick_from_now_playing(url: str, title: str, kind: str, *, is_video: bool = False,
                          show_title: str = "") -> tuple[SourcePick | None, str]:
    """What is playing now as a schedule source: (pick, "") or (None, why not).

    *kind* is the source the main window reports: "station", "podcast", "audiobook"
    or "media" (a file or anything else)."""
    if not url:
        return None, "Nothing is loaded in the player. Play a station or episode first."
    if is_video:
        return None, ("A video cannot be recorded by the scheduler. Choose a station or "
                      "podcast episode instead.")
    if not _online(url):
        return None, ("The item playing now is a file on this computer. Only a stream or an "
                      "online episode can be scheduled.")
    source_type = {"station": SOURCE_STATION, "podcast": SOURCE_PODCAST,
                   "audiobook": SOURCE_AUDIOBOOK}.get(kind, SOURCE_STATION)
    name = (title or "").strip() or url
    if kind == "podcast" and show_title and show_title not in name:
        name = f"{show_title}: {name}"
    return SourcePick(url, name, source_type), ""


class ScheduleSources:
    """The lists the schedule dialog's pickers draw from."""

    def __init__(self, station_db, db, now_playing: Callable[[], tuple[SourcePick | None, str]]):
        self._station_db = station_db
        self._db = db
        self._now_playing = now_playing

    def now_playing(self) -> tuple[SourcePick | None, str]:
        try:
            return self._now_playing()
        except Exception:
            return None, "Could not tell what is playing."

    def stations(self, query: str = "", limit: int = 200) -> list:
        """Stations matching *query*: favorites and custom stations first, then the
        catalog. With no query, just favorites and custom stations."""
        query = (query or "").strip()
        found: list = []
        seen: set[str] = set()

        def add(stations) -> None:
            for station in stations:
                url = getattr(station, "url", "")
                if _online(url) and url not in seen:
                    seen.add(url)
                    found.append(station)

        def matches(station) -> bool:
            wanted = query.casefold()
            return not wanted or wanted in (getattr(station, "name", "") or "").casefold()

        add(s for s in self._station_db.get_favorite_stations() if matches(s))
        add(s for s in self._station_db.get_custom_stations() if matches(s))
        if query:
            add(self._station_db.search_local(query, limit))
        return found[:limit]

    def podcast_shows(self) -> list[dict[str, Any]]:
        from radiomaster.database.repository import PodcastRepository
        return [show for show in PodcastRepository(self._db).get_all() if show.get("id")]

    def episodes(self, show_id: int) -> list[dict[str, Any]]:
        from radiomaster.database.repository import PodcastRepository
        return [ep for ep in PodcastRepository(self._db).get_episodes(show_id)
                if _online(ep.get("audio_url") or "")]
