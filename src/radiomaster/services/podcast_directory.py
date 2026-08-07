"""Podcast directory service for browsing iTunes/Apple Podcasts."""

import logging
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
                    results.append({
                        "id": item.get("collectionId", 0),
                        "title": item.get("collectionName", ""),
                        "author": item.get("artistName", ""),
                        "artwork_url": item.get("artworkUrl600", ""),
                        "feed_url": item.get("feedUrl", ""),
                        "description": item.get("description", ""),
                        "episode_count": item.get("trackCount", 0),
                        "genre": item.get("primaryGenreName", ""),
                        "country": item.get("country", ""),
                        "release_date": item.get("releaseDate", ""),
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
