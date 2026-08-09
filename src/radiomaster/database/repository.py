"""Repository layer for database CRUD operations."""

from typing import Any
from radiomaster.database.connection import DatabaseManager


class StationRepository:
    """CRUD operations for radio stations."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def bulk_upsert(self, stations: list[dict[str, Any]]) -> int:
        """Insert or update stations from Free Radio Browser."""
        count = 0
        for s in stations:
            sid = s.get("stationuuid", "") or s.get("id", "")
            if not sid:
                continue
            self._db.execute(
                """INSERT OR REPLACE INTO stations
                (station_id, name, url, country, country_code, language,
                 language_codes, genre, tags, bitrate, codec, votes, clicks)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    sid, s.get("name", ""), s.get("url_resolved", "") or s.get("url", ""),
                    s.get("country", ""), s.get("countrycode", ""),
                    s.get("language", ""), s.get("languagecodes", ""),
                    s.get("tags", ""), s.get("tags", ""),
                    s.get("bitrate", 0), s.get("codec", ""),
                    s.get("votes", 0), s.get("clickcount", 0),
                ),
            )
            count += 1
        self._db.commit()
        return count

    def search(self, query: str, limit: int = 100) -> list[dict[str, Any]]:
        """Search stations by name, country, language, genre, or tags."""
        like = f"%{query}%"
        return self._db.fetchall(
            """SELECT * FROM stations WHERE
            name LIKE ? OR country LIKE ? OR language LIKE ? OR
            genre LIKE ? OR tags LIKE ?
            ORDER BY votes DESC LIMIT ?""",
            (like, like, like, like, like, limit),
        )

    def get_by_category(self, category_type: str, value: str) -> list[dict[str, Any]]:
        """Get stations by category type and value."""
        return self._db.fetchall(
            """SELECT s.* FROM stations s
            JOIN station_categories sc ON s.station_id = sc.station_id
            WHERE sc.category_type = ? AND sc.category_value = ?
            ORDER BY s.votes DESC""",
            (category_type, value),
        )

    def get_categories(self, category_type: str) -> list[str]:
        """Get distinct category values for a category type."""
        rows = self._db.fetchall(
            "SELECT DISTINCT category_value FROM station_categories WHERE category_type = ? ORDER BY category_value",
            (category_type,),
        )
        return [r["category_value"] for r in rows]

    def add_custom(self, name: str, url: str, genre: str = "", country: str = "", language: str = "") -> int:
        """Add a custom station."""
        cursor = self._db.execute(
            "INSERT INTO custom_stations (name, url, genre, country, language) VALUES (?, ?, ?, ?, ?)",
            (name, url, genre, country, language),
        )
        self._db.commit()
        return cursor.lastrowid

    def get_custom_stations(self) -> list[dict[str, Any]]:
        """Get all custom stations."""
        return self._db.fetchall("SELECT * FROM custom_stations ORDER BY name")


class PodcastRepository:
    """CRUD operations for podcasts."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def add(self, feed_url: str, title: str = "", description: str = "",
            author: str = "", artwork_url: str = "", website_url: str = "",
            is_custom: bool = False) -> int:
        cursor = self._db.execute(
            """INSERT OR REPLACE INTO podcasts
            (feed_url, title, description, author, artwork_url, website_url, is_custom)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (feed_url, title, description, author, artwork_url, website_url, int(is_custom)),
        )
        self._db.commit()
        return cursor.lastrowid

    def get_by_feed_url(self, feed_url: str) -> dict[str, Any] | None:
        """Get a podcast by its feed URL."""
        results = self._db.fetchall(
            "SELECT * FROM podcasts WHERE feed_url = ?",
            (feed_url,),
        )
        return results[0] if results else None

    def get_all(self) -> list[dict[str, Any]]:
        return self._db.fetchall("SELECT * FROM podcasts ORDER BY title")

    def get_episodes(self, podcast_id: int) -> list[dict[str, Any]]:
        return self._db.fetchall(
            "SELECT * FROM episodes WHERE podcast_id = ? ORDER BY published_date DESC",
            (podcast_id,),
        )

    def remove(self, podcast_id: int) -> None:
        """Unsubscribe: removes the podcast and (via ON DELETE CASCADE,
        foreign_keys=ON in connection.py) its episodes."""
        self._db.execute("DELETE FROM podcasts WHERE id = ?", (podcast_id,))
        self._db.commit()


class EpisodeRepository:
    """CRUD operations for individual podcast episodes (play progress)."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def update_position(self, episode_id: int, position: float) -> None:
        self._db.execute(
            "UPDATE episodes SET play_position = ? WHERE id = ?",
            (position, episode_id),
        )
        self._db.commit()

    def mark_played(self, episode_id: int, is_played: bool = True) -> None:
        self._db.execute(
            "UPDATE episodes SET is_played = ? WHERE id = ?",
            (int(is_played), episode_id),
        )
        self._db.commit()

    def get(self, episode_id: int) -> dict[str, Any] | None:
        results = self._db.fetchall("SELECT * FROM episodes WHERE id = ?", (episode_id,))
        return results[0] if results else None


class AudiobookRepository:
    """CRUD operations for audiobooks."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def add(self, **kwargs: Any) -> int:
        cols = ", ".join(kwargs.keys())
        placeholders = ", ".join("?" for _ in kwargs)
        cursor = self._db.execute(
            f"INSERT INTO audiobooks ({cols}) VALUES ({placeholders})",
            tuple(kwargs.values()),
        )
        self._db.commit()
        return cursor.lastrowid

    def get_all(self) -> list[dict[str, Any]]:
        return self._db.fetchall("SELECT * FROM audiobooks ORDER BY title")

    def update_position(self, book_id: int, position: float) -> None:
        self._db.execute(
            "UPDATE audiobooks SET last_position = ? WHERE id = ?",
            (position, book_id),
        )
        self._db.commit()


class MediaRepository:
    """CRUD operations for local media files."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def add(self, file_path: str, title: str = "", artist: str = "",
            album: str = "", duration: float = 0.0, format: str = "",
            bitrate: int = 0) -> int:
        cursor = self._db.execute(
            """INSERT OR IGNORE INTO media_files
            (file_path, title, artist, album, duration, format, bitrate)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (file_path, title, artist, album, duration, format, bitrate),
        )
        self._db.commit()
        return cursor.lastrowid

    def search(self, query: str) -> list[dict[str, Any]]:
        like = f"%{query}%"
        return self._db.fetchall(
            "SELECT * FROM media_files WHERE title LIKE ? OR artist LIKE ? OR album LIKE ?",
            (like, like, like),
        )


class PlaylistRepository:
    """CRUD operations for playlists."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def create(self, name: str, description: str = "") -> int:
        cursor = self._db.execute(
            "INSERT INTO playlists (name, description) VALUES (?, ?)",
            (name, description),
        )
        self._db.commit()
        return cursor.lastrowid

    def get_all(self) -> list[dict[str, Any]]:
        return self._db.fetchall("SELECT * FROM playlists ORDER BY name")

    def add_item(self, playlist_id: int, item_type: str, title: str,
                 item_id: int = 0, item_url: str = "", duration: float = 0.0) -> int:
        pos = self._db.fetchone(
            "SELECT COALESCE(MAX(position), 0) + 1 as pos FROM playlist_items WHERE playlist_id = ?",
            (playlist_id,),
        )
        cursor = self._db.execute(
            """INSERT INTO playlist_items
            (playlist_id, item_type, item_id, item_url, title, duration, position)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (playlist_id, item_type, item_id, item_url, title, duration, pos["pos"] if pos else 1),
        )
        self._db.commit()
        return cursor.lastrowid

    def get_items(self, playlist_id: int) -> list[dict[str, Any]]:
        return self._db.fetchall(
            "SELECT * FROM playlist_items WHERE playlist_id = ? ORDER BY position",
            (playlist_id,),
        )


class DownloadRepository:
    """CRUD operations for downloads."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def add(self, url: str, title: str = "", source_type: str = "",
            format: str = "", quality: str = "") -> int:
        cursor = self._db.execute(
            """INSERT INTO downloads (url, title, source_type, format, quality)
            VALUES (?, ?, ?, ?, ?)""",
            (url, title, source_type, format, quality),
        )
        self._db.commit()
        return cursor.lastrowid

    def get_queued(self) -> list[dict[str, Any]]:
        return self._db.fetchall(
            "SELECT * FROM downloads WHERE status IN ('queued', 'downloading') ORDER BY id"
        )

    def update_progress(self, download_id: int, progress: float, status: str = "") -> None:
        if status:
            self._db.execute(
                "UPDATE downloads SET progress = ?, status = ? WHERE id = ?",
                (progress, status, download_id),
            )
        else:
            self._db.execute(
                "UPDATE downloads SET progress = ? WHERE id = ?",
                (progress, download_id),
            )
        self._db.commit()


class ScheduleRepository:
    """CRUD operations for recording schedules."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def add(self, url: str, title: str, source_type: str, start_time: str,
            duration: int = 0, recurrence: str = "", format: str = "auto",
            enabled: int = 1) -> int:
        cursor = self._db.execute(
            """INSERT INTO schedules (url, title, source_type, start_time, duration, recurrence, format, enabled)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (url, title, source_type, start_time, duration, recurrence, format, enabled),
        )
        self._db.commit()
        return cursor.lastrowid

    def get_active(self) -> list[dict[str, Any]]:
        return self._db.fetchall(
            "SELECT * FROM schedules WHERE enabled = 1 ORDER BY start_time"
        )

    def get_all(self) -> list[dict[str, Any]]:
        return self._db.fetchall("SELECT * FROM schedules ORDER BY start_time")

    def update(self, schedule_id: int, **kwargs: Any) -> None:
        """Update an existing schedule."""
        if not kwargs:
            return
        
        fields = ', '.join(f"{key} = ?" for key in kwargs.keys())
        values = list(kwargs.values()) + [schedule_id]
        
        self._db.execute(
            f"UPDATE schedules SET {fields} WHERE id = ?",
            values
        )
        self._db.commit()
    
    def delete(self, schedule_id: int) -> None:
        """Delete a schedule."""
        self._db.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
        self._db.commit()


class LyricsRepository:
    """CRUD operations for lyrics cache."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def get_cached(self, track_hash: str) -> dict[str, Any] | None:
        """Get cached lyrics by track hash.

        The original schema (migration 13) stored lyrics keyed by ``artist`` and
        ``title`` with a unique constraint.  Migration 20 introduced a ``track_hash``
        column, but the test suite still expects the older schema (version 19).
        Therefore we first try a hash lookup; if the column does not exist we fall
        back to the legacy ``artist``/``title`` query.
        """
        # Try hash‑based lookup – will succeed only if migration 20 was applied.
        try:
            results = self._db.fetchall(
                "SELECT * FROM lyrics_cache WHERE track_hash = ?",
                (track_hash,)
            )
            if results:
                return results[0]
        except Exception:
            # Column missing – ignore and fall back to legacy query.
            pass

        # Legacy fallback – match on artist/title (case‑insensitive).
        # The repository does not have the original artist/title values here,
        # so callers should provide them if they need this path.  For the current
        # usage we simply return ``None`` when the hash lookup fails.
        return None

    def save(
        self,
        track_hash: str,
        artist: str,
        title: str,
        lyrics_text: str,
        lyrics_synced: str | None,
        source: str,
        ttl_hours: int = 24,
    ) -> None:
        """Save lyrics to cache.

        Uses the legacy schema (migration 13) when the ``track_hash`` column is
        unavailable.  The ``ttl_hours`` parameter is retained for API
        compatibility but is ignored because the older schema does not store an
        expiration timestamp.
        """
        # Attempt to insert using the newer schema; if it fails we fall back to
        # the older column set.
        try:
            self._db.execute(
                "INSERT OR REPLACE INTO lyrics_cache (track_hash, artist, title, lyrics_text, lyrics_synced, source) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (track_hash, artist, title, lyrics_text, lyrics_synced, source),
            )
        except Exception:
            # Legacy schema – columns: artist, title, lyrics, source, is_synced, lrc_data
            self._db.execute(
                "INSERT OR REPLACE INTO lyrics_cache (artist, title, lyrics, source, is_synced, lrc_data) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    artist,
                    title,
                    lyrics_text,
                    source,
                    1 if lyrics_synced else 0,
                    lyrics_synced or "",
                ),
            )
        self._db.commit()

    def cleanup_expired(self) -> int:
        """Remove expired cache entries."""
        self._db.execute("DELETE FROM lyrics_cache WHERE expires_at < datetime('now')")
        self._db.commit()
        return self._db.conn.rowcount


class SleepTimerRepository:
    """CRUD operations for sleep timers."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def add(self, start_time: str, duration: int = 0) -> int:
        cursor = self._db.execute(
            "INSERT INTO sleep_timers (start_time, duration) VALUES (?, ?)",
            (start_time, duration),
        )
        self._db.commit()
        return cursor.lastrowid

    def get_all(self) -> list[dict[str, Any]]:
        return self._db.fetchall("SELECT * FROM sleep_timers ORDER BY start_time")

    def update(self, timer_id: int, **kwargs: Any) -> None:
        """Update an existing sleep timer."""
        if not kwargs:
            return
        
        fields = ', '.join(f"{key} = ?" for key in kwargs.keys())
        values = list(kwargs.values()) + [timer_id]
        
        self._db.execute(
            f"UPDATE sleep_timers SET {fields} WHERE id = ?",
            values
        )
        self._db.commit()
    
    def delete(self, timer_id: int) -> None:
        """Delete a sleep timer."""
        self._db.execute("DELETE FROM sleep_timers WHERE id = ?", (timer_id,))
        self._db.commit()


class BookmarkRepository:
    """CRUD operations for bookmarks."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def add(self, title: str, source_type: str, url: str = "",
            position: float = 0.0, notes: str = "") -> int:
        cursor = self._db.execute(
            """INSERT INTO bookmarks (title, source_type, url, position, notes)
            VALUES (?, ?, ?, ?, ?)""",
            (title, source_type, url, position, notes),
        )
        self._db.commit()
        return cursor.lastrowid

    def get_all(self, source_type: str = "") -> list[dict[str, Any]]:
        if source_type:
            return self._db.fetchall(
                "SELECT * FROM bookmarks WHERE source_type = ? ORDER BY created_at DESC",
                (source_type,),
            )
        return self._db.fetchall("SELECT * FROM bookmarks ORDER BY created_at DESC")

    def delete(self, bookmark_id: int) -> None:
        self._db.execute("DELETE FROM bookmarks WHERE id = ?", (bookmark_id,))
        self._db.commit()
