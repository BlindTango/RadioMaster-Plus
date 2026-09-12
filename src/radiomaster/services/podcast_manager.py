"""Podcast manager for RSS feed parsing and podcast directory integration."""

import feedparser
import logging
import re
from typing import Any
from datetime import datetime

logger = logging.getLogger("radiomaster")


class PodcastManager:
    """Manages podcast feed parsing and subscription management."""

    @staticmethod
    def parse_feed(url: str) -> dict[str, Any] | None:
        """Parse an RSS/Atom podcast feed."""
        try:
            import requests
            from radiomaster.utils.network import request_kwargs
            response = requests.get(url, **request_kwargs("RadioMaster+/1.0"))
            response.raise_for_status()
            feed = feedparser.parse(response.content)
            if feed.bozo and not feed.entries:
                logger.warning(f"Failed to parse feed: {url}")
                return None

            podcast = {
                "title": feed.feed.get("title", ""),
                "description": feed.feed.get("description", ""),
                "author": feed.feed.get("author", ""),
                "artwork_url": "",
                "website_url": feed.feed.get("link", ""),
                "episodes": [],
            }

            # Get artwork (prefer iTunes image)
            if hasattr(feed.feed, "image") and feed.feed.image:
                podcast["artwork_url"] = feed.feed.image.get("href", "")
            if hasattr(feed.feed, "itunes_image"):
                podcast["artwork_url"] = feed.feed.itunes_image.get("href", "")

            # Parse episodes
            for entry in feed.entries:
                episode = {
                    "guid": entry.get("id", ""),
                    "title": entry.get("title", ""),
                    "description": PodcastManager._clean_html(
                        entry.get("description", "")
                    ),
                    "content_encoded": entry.get("content", [{}])[0].get("value", "")
                    if entry.get("content") else "",
                    "published_date": "",
                    "duration": 0,
                    "audio_url": "",
                }

                # Publication date
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    episode["published_date"] = datetime(*entry.published_parsed[:6]).isoformat()

                # Duration
                if hasattr(entry, "itunes_duration"):
                    duration_str = entry.itunes_duration
                    episode["duration"] = PodcastManager._parse_duration(duration_str)

                # Audio URL
                for link in entry.get("links", []):
                    if link.get("type", "").startswith("audio/"):
                        episode["audio_url"] = link.get("href", "")
                        break
                if not episode["audio_url"] and entry.get("enclosures"):
                    episode["audio_url"] = entry.enclosures[0].get("href", "")

                podcast["episodes"].append(episode)

            return podcast

        except Exception as e:
            logger.error(f"Error parsing feed {url}: {e}")
            return None

    @staticmethod
    def _clean_html(html: str) -> str:
        """Remove HTML tags from text."""
        clean = re.sub(r"<[^>]+>", "", html)
        return clean.strip()

    @staticmethod
    def _parse_duration(duration_str: str) -> int:
        """Parse duration string (HH:MM:SS, MM:SS, or seconds) to seconds."""
        if not duration_str:
            return 0
        try:
            return int(duration_str)
        except ValueError:
            pass
        parts = duration_str.split(":")
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        return 0

    @staticmethod
    def import_subscriptions(
        db, feeds: list[dict[str, str]], *, create_missing: bool = True,
    ) -> dict[str, Any]:
        """Save subscriptions and fetch episodes, preserving existing playback state."""
        import hashlib
        from radiomaster.database.repository import PodcastRepository

        repo = PodcastRepository(db)
        result = {"imported": 0, "refreshed": 0, "failed": [], "podcast_ids": []}
        seen = set()
        for feed in feeds:
            url = feed["feed_url"].strip()
            if not url or url in seen:
                continue
            seen.add(url)
            try:
                existing = repo.get_by_feed_url(url)
                if not create_missing and not existing:
                    continue
                podcast_id = existing["id"] if existing else repo.add(
                    url, title=feed.get("title") or url,
                    website_url=feed.get("website_url", ""), is_custom=True,
                )
                result["podcast_ids"].append(podcast_id)
                if not existing:
                    result["imported"] += 1
                data = PodcastManager.parse_feed(url)
                if data is None:
                    raise ValueError("Feed could not be loaded")
                for ep in data.get("episodes", []):
                    identity = ep.get("guid") or ep.get("audio_url") or (
                        ep.get("title", "") + "|" + ep.get("published_date", "")
                    )
                    # Publishers can omit GUIDs or reuse them across feeds.
                    guid = "opml:" + hashlib.sha256(
                        (url + "\n" + identity).encode("utf-8")
                    ).hexdigest()
                    found = db.fetchone(
                        """SELECT id FROM episodes WHERE podcast_id = ? AND
                        (guid = ? OR (guid <> '' AND guid = ?) OR
                         (audio_url <> '' AND audio_url = ?))""",
                        (podcast_id, guid, ep.get("guid", ""), ep.get("audio_url", "")),
                    )
                    if found:
                        continue
                    db.execute(
                        """INSERT INTO episodes
                        (podcast_id, guid, title, description, content_encoded,
                         duration, published_date, audio_url)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (podcast_id, guid, ep.get("title", ""),
                         ep.get("description", ""), ep.get("content_encoded", ""),
                         ep.get("duration", 0), ep.get("published_date", ""),
                         ep.get("audio_url", "")),
                    )
                db.commit()
                result["refreshed"] += 1
            except Exception:
                db.conn.rollback()
                logger.exception("Unable to import episodes for %s", url)
                result["failed"].append(feed.get("title") or url)
        return result

    @staticmethod
    def export_opml(subscriptions: list[dict[str, Any]]) -> str:
        """Export podcast subscriptions to OPML format."""
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<opml version="2.0">',
            "  <head>",
            "    <title>RadioMaster+ Podcast Subscriptions</title>",
            "  </head>",
            "  <body>",
        ]
        for sub in subscriptions:
            lines.append(
                f'    <outline text="{sub.get("title", "")}" '
                f'type="rss" xmlUrl="{sub.get("feed_url", "")}" '
                f'htmlUrl="{sub.get("website_url", "")}"/>'
            )
        lines.append("  </body>")
        lines.append("</opml>")
        return "\n".join(lines)

    @staticmethod
    def parse_opml(opml_content: str) -> list[dict[str, str]]:
        """Parse OPML content to extract feed URLs."""
        import xml.etree.ElementTree as ET
        feeds = []
        try:
            root = ET.fromstring(opml_content)
            for outline in root.iter("outline"):
                xml_url = outline.get("xmlUrl", "")
                if xml_url:
                    feeds.append({
                        "title": outline.get("text") or outline.get("title", ""),
                        "feed_url": xml_url,
                        "website_url": outline.get("htmlUrl", ""),
                    })
        except ET.ParseError as e:
            logger.error(f"Failed to parse OPML: {e}")
        return feeds
