"""Lyrics lookup service supporting multiple lyrics APIs."""

import logging
import re
import hashlib
from typing import Any

from radiomaster.database.repository import LyricsRepository

logger = logging.getLogger("radiomaster")

# Module‑level reference to the injected repository (set during app start‑up)
_lyrics_repo: LyricsRepository | None = None


def set_lyrics_repository(repo: LyricsRepository) -> None:
    """Inject the LyricsRepository used for caching.

    The application creates a single ``DatabaseManager`` and passes it to the
    repository layer.  This helper stores the repository in a module‑level
    variable so the static ``LyricsService`` methods can access the cache without
    needing an instance.
    """
    global _lyrics_repo
    _lyrics_repo = repo


class LyricsService:
    """Fetches lyrics from multiple sources with optional SQLite caching.

    Lookup order:
    1. Local ``lyrics_cache`` (if repository injected)
    2. LRCLib
    3. Lyrics.ovh
    4. Genius (placeholder)
    5. Musixmatch (placeholder)
    """

    @staticmethod
    def _track_hash(artist: str, title: str) -> str:
        """Create a deterministic SHA‑256 hash used as the cache key."""
        key = f"{artist.lower().strip()}-{title.lower().strip()}"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    @staticmethod
    def _request_kwargs(timeout: float, extra_headers: dict[str, str] | None = None) -> dict[str, Any]:
        """Network settings (proxy, timeout, user agent) applied uniformly."""
        from radiomaster.utils.network import get_timeout, get_proxies, get_user_agent
        headers = {"User-Agent": get_user_agent("RadioMaster+/1.0")}
        if extra_headers:
            headers.update(extra_headers)
        kwargs: dict[str, Any] = {"timeout": get_timeout(default=timeout), "headers": headers}
        proxies = get_proxies()
        if proxies:
            kwargs["proxies"] = proxies
        return kwargs

    @staticmethod
    def fetch_lyrics(artist: str, title: str) -> dict[str, Any] | None:
        """Fetch lyrics for a track, using cache when possible."""
        track_hash = LyricsService._track_hash(artist, title)

        # 1️⃣ Cache lookup
        if _lyrics_repo is not None:
            cached = _lyrics_repo.get_cached(track_hash)
            if cached:
                logger.debug("Lyrics cache hit for %s - %s", artist, title)
                return {
                    "lyrics": cached["lyrics_text"],
                    "source": cached["source"],
                    "is_synced": bool(cached["lyrics_synced"]),
                    "lrc": cached["lyrics_synced"] or "",
                }

        # 2️⃣ External providers – stop at first success
        for provider in (
            LyricsService._fetch_lrclib,
            LyricsService._fetch_lyrics_ovh,
            LyricsService._fetch_genius,
            LyricsService._fetch_musixmatch,
        ):
            result = provider(artist, title)
            if result:
                # Store in cache (default TTL 24 h)
                if _lyrics_repo is not None:
                    _lyrics_repo.save(
                        track_hash=track_hash,
                        artist=artist,
                        title=title,
                        lyrics_text=result["lyrics"],
                        lyrics_synced=result.get("lrc", ""),
                        source=result.get("source", ""),
                        ttl_hours=24,
                    )
                return result

        return None

    @staticmethod
    def _fetch_lrclib(artist: str, title: str) -> dict[str, Any] | None:
        """Fetch lyrics from LRCLib (open source, supports LRC)."""
        try:
            import requests
            resp = requests.get(
                "https://lrclib.net/api/get",
                params={"artist_name": artist, "track_name": title},
                **LyricsService._request_kwargs(5),
            )
            if resp.status_code == 200:
                data = resp.json()
                lyrics = data.get("plainLyrics", "") or data.get("syncedLyrics", "")
                if lyrics:
                    return {
                        "lyrics": lyrics,
                        "source": "LRCLib",
                        "is_synced": bool(data.get("syncedLyrics")),
                        "lrc": data.get("syncedLyrics", ""),
                    }
        except Exception as e:
            logger.debug(f"LRCLib lookup failed: {e}")
        return None

    @staticmethod
    def _fetch_lyrics_ovh(artist: str, title: str) -> dict[str, Any] | None:
        """Fetch lyrics from Lyrics.ovh."""
        try:
            import requests
            resp = requests.get(
                f"https://api.lyrics.ovh/v1/{artist}/{title}",
                **LyricsService._request_kwargs(5),
            )
            if resp.status_code == 200:
                data = resp.json()
                lyrics = data.get("lyrics", "")
                if lyrics and lyrics != "Not found":
                    return {
                        "lyrics": lyrics,
                        "source": "Lyrics.ovh",
                        "is_synced": False,
                        "lrc": "",
                    }
        except Exception as e:
            logger.debug(f"Lyrics.ovh lookup failed: {e}")
        return None

    @staticmethod
    def parse_lrc(lrc_text: str) -> list[dict[str, Any]]:
        """Parse LRC (synced lyrics) format into timed lines."""
        lines = []
        pattern = re.compile(r"\[(\d{2}):(\d{2})\.(\d{2,3})\](.*)")
        for line in lrc_text.strip().split("\n"):
            match = pattern.match(line)
            if match:
                minutes = int(match.group(1))
                seconds = int(match.group(2))
                frac = match.group(3)
                # ``frac`` may be two digits (centiseconds) or three digits
                # (milliseconds).  Convert accordingly.
                if len(frac) == 2:
                    fraction = int(frac) / 100.0
                else:
                    fraction = int(frac) / 1000.0
                time_sec = minutes * 60 + seconds + fraction
                text = match.group(4).strip()
                lines.append({"time": time_sec, "text": text})
        return sorted(lines, key=lambda x: x["time"])

    # ------------------------------------------------------------------
    # External providers (Genius, Musixmatch)
    # ------------------------------------------------------------------
    @staticmethod
    def _fetch_genius(artist: str, title: str) -> dict[str, Any] | None:
        """Fetch lyrics from Genius API.

        Requires a Genius API client access token configured in settings
        under ``lyrics.genius_token``.
        """
        from radiomaster.utils.config import ConfigManager
        config = ConfigManager.get_instance()
        token = config.get("lyrics.genius_token", default="")
        if not token:
            logger.debug("Genius API token not configured — skipping")
            return None
        try:
            import requests
            resp = requests.get(
                "https://api.genius.com/search",
                params={"q": f"{artist} {title}"},
                **LyricsService._request_kwargs(10, {"Authorization": f"Bearer {token}"}),
            )
            if resp.status_code == 200:
                hits = resp.json().get("response", {}).get("hits", [])
                if hits:
                    song_path = hits[0].get("result", {}).get("path", "")
                    if song_path:
                        page = requests.get(f"https://genius.com{song_path}", **LyricsService._request_kwargs(10))
                        if page.status_code == 200:
                            import re
                            match = re.search(
                                r'<div class="lyrics".*?>(.*?)</div>', page.text, re.DOTALL
                            )
                            if match:
                                from html import unescape
                                lyrics = unescape(match.group(1))
                                lyrics = re.sub(r"<[^>]+>", "", lyrics)
                                return {"lyrics": lyrics.strip(), "source": "genius"}
        except Exception as e:
            logger.error(f"Genius lookup failed: {e}")
        return None

    @staticmethod
    def _fetch_musixmatch(artist: str, title: str) -> dict[str, Any] | None:
        """Fetch lyrics from Musixmatch.

        Requires a Musixmatch API key configured in settings
        under ``lyrics.musixmatch_key``.
        """
        from radiomaster.utils.config import ConfigManager
        config = ConfigManager.get_instance()
        api_key = config.get("lyrics.musixmatch_key", default="")
        if not api_key:
            logger.debug("Musixmatch API key not configured — skipping")
            return None
        try:
            import requests
            resp = requests.get(
                "https://api.musixmatch.com/ws/1.1/matcher.lyrics.get",
                params={"q_artist": artist, "q_track": title, "apikey": api_key},
                **LyricsService._request_kwargs(10),
            )
            if resp.status_code == 200:
                body = resp.json().get("message", {}).get("body", {})
                lyrics = body.get("lyrics", {}).get("lyrics_body", "")
                if lyrics:
                    return {"lyrics": lyrics.strip(), "source": "musixmatch"}
        except Exception as e:
            logger.error(f"Musixmatch lookup failed: {e}")
        return None
