"""Podcast directory service for browsing podcast directories.

search_all() fans a query out to every directory that's actually available
(iTunes always is; Podcast Index only once the user has entered a free API
key+secret in Settings > Podcasts) and merges the results, tagging each
with which directory it came from -- there's no single canonical podcast
database the way Radio Browser is for stations, so "discover podcasts"
means asking more than one source.
"""

import hashlib
import logging
import time
import requests
from typing import Any

logger = logging.getLogger("radiomaster")


class PodcastDirectory:
    """Browse and search podcast directories (iTunes/Apple Podcasts API)."""

    ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
    ITUNES_LOOKUP_URL = "https://itunes.apple.com/lookup"

    @staticmethod
    def _request_kwargs() -> dict[str, Any]:
        """Network settings (proxy, timeout, user agent) applied uniformly,
        so the Network settings panel actually has an effect here."""
        from radiomaster.utils.network import get_timeout, get_proxies, get_user_agent
        kwargs: dict[str, Any] = {
            "timeout": get_timeout(default=10),
            "headers": {"User-Agent": get_user_agent("RadioMaster+/1.0")},
        }
        proxies = get_proxies()
        if proxies:
            kwargs["proxies"] = proxies
        return kwargs

    @staticmethod
    def search(term: str, limit: int = 25, country: str = "US") -> list[dict[str, Any]]:
        """Search for podcasts on iTunes/Apple Podcasts."""
        try:
            resp = requests.get(
                PodcastDirectory.ITUNES_SEARCH_URL,
                params={
                    "term": term,
                    "media": "podcast",
                    "limit": limit,
                    "country": country,
                    "entity": "podcast",
                },
                **PodcastDirectory._request_kwargs(),
            )
            if resp.status_code == 200:
                results = []
                for item in resp.json().get("results", []):
                    feed_url = item.get("feedUrl", "")
                    if not feed_url:
                        continue
                    results.append({
                        "id": item.get("collectionId", 0),
                        "title": item.get("collectionName", ""),
                        "author": item.get("artistName", ""),
                        "artwork_url": item.get("artworkUrl600", ""),
                        "feed_url": feed_url,
                        "description": item.get("description", ""),
                        "episode_count": item.get("trackCount", 0),
                        "genre": item.get("primaryGenreName", ""),
                        "country": item.get("country", ""),
                        "release_date": item.get("releaseDate", ""),
                        "directory": "iTunes / Apple Podcasts",
                    })
                return results
        except Exception as e:
            logger.error(f"Podcast search failed: {e}")
        return []

    @staticmethod
    def lookup(podcast_id: int) -> dict[str, Any] | None:
        """Look up a specific podcast by iTunes ID."""
        try:
            resp = requests.get(
                PodcastDirectory.ITUNES_LOOKUP_URL,
                params={"id": podcast_id, "entity": "podcast", "limit": 1},
                **PodcastDirectory._request_kwargs(),
            )
            if resp.status_code == 200:
                results = resp.json().get("results", [])
                if results:
                    item = results[0]
                    return {
                        "id": item.get("collectionId", 0),
                        "title": item.get("collectionName", ""),
                        "author": item.get("artistName", ""),
                        "artwork_url": item.get("artworkUrl600", ""),
                        "feed_url": item.get("feedUrl", ""),
                        "description": item.get("description", ""),
                        "episode_count": item.get("trackCount", 0),
                        "genre": item.get("primaryGenreName", ""),
                    }
        except Exception as e:
            logger.error(f"Podcast lookup failed: {e}")
        return None

    @staticmethod
    def get_top_podcasts(limit: int = 50, country: str = "US") -> list[dict[str, Any]]:
        """Get top podcasts from iTunes."""
        try:
            resp = requests.get(
                PodcastDirectory.ITUNES_LOOKUP_URL,
                params={
                    "limit": limit,
                    "country": country,
                    "entity": "podcast",
                    "genreId": 26,  # Podcasts genre
                },
                **PodcastDirectory._request_kwargs(),
            )
            if resp.status_code == 200:
                results = []
                for item in resp.json().get("results", []):
                    if item.get("wrapperType") == "track":
                        results.append({
                            "id": item.get("collectionId", 0),
                            "title": item.get("collectionName", ""),
                            "author": item.get("artistName", ""),
                            "feed_url": item.get("feedUrl", ""),
                        })
                return results
        except Exception as e:
            logger.error(f"Failed to get top podcasts: {e}")
        return []


class PodcastIndexDirectory:
    """Podcast Index (podcastindex.org) -- a second, independent podcast
    directory. Needs a free API key+secret from the user (Settings >
    Podcasts); every request is HMAC-signed per Podcast Index's published
    auth scheme. Silently contributes no results (not an error) when not
    configured, so it's safe to always include in search_all() even for
    users who never set it up."""

    BASE_URL = "https://api.podcastindex.org/api/1.0"

    @staticmethod
    def _credentials() -> tuple[str, str]:
        from radiomaster.utils.config import ConfigManager
        config = ConfigManager.get_instance()
        return (
            config.get("podcasts.podcastindex_api_key", default=""),
            config.get("podcasts.podcastindex_api_secret", default=""),
        )

    @staticmethod
    def available() -> bool:
        key, secret = PodcastIndexDirectory._credentials()
        return bool(key and secret)

    @staticmethod
    def search(term: str, limit: int = 25) -> list[dict[str, Any]]:
        key, secret = PodcastIndexDirectory._credentials()
        if not key or not secret:
            return []
        from radiomaster.utils.network import get_timeout, get_proxies, get_user_agent
        epoch = str(int(time.time()))
        auth_hash = hashlib.sha1(f"{key}{secret}{epoch}".encode("utf-8")).hexdigest()
        headers = {
            "User-Agent": get_user_agent("RadioMaster+/1.0"),
            "X-Auth-Key": key,
            "X-Auth-Date": epoch,
            "Authorization": auth_hash,
        }
        try:
            resp = requests.get(
                f"{PodcastIndexDirectory.BASE_URL}/search/byterm",
                params={"q": term, "max": limit},
                headers=headers, timeout=get_timeout(default=10),
                proxies=get_proxies() or None,
            )
            if resp.status_code == 200:
                results = []
                for item in resp.json().get("feeds", []):
                    feed_url = item.get("url", "")
                    if not feed_url:
                        continue
                    categories = item.get("categories")
                    genre = ", ".join(categories.values()) if isinstance(categories, dict) else ""
                    results.append({
                        "id": 0,
                        "title": item.get("title", ""),
                        "author": item.get("author", ""),
                        "artwork_url": item.get("image") or item.get("artwork", ""),
                        "feed_url": feed_url,
                        "description": item.get("description", ""),
                        "episode_count": item.get("episodeCount", 0),
                        "genre": genre,
                        "country": "",
                        "release_date": "",
                        "directory": "Podcast Index",
                    })
                return results
        except Exception as e:
            logger.error(f"Podcast Index search failed: {e}")
        return []


def search_all(term: str, limit: int = 25) -> list[dict[str, Any]]:
    """Fans a search out to every available directory (iTunes always;
    Podcast Index once configured) and merges the results. Each directory
    already swallows its own network/parse errors and returns [] rather
    than raising, so a failure in one never blocks the other."""
    results = list(PodcastDirectory.search(term, limit=limit))
    results.extend(PodcastIndexDirectory.search(term, limit=limit))
    return results
