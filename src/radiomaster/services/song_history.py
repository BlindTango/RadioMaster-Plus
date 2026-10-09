"""Song History: what played, per station, capped and queryable.

Borrowed from Quill Radio's song history: the ICY StreamTitle the radio
panel already parses is a log of what the listener actually heard, and
"what was that song an hour ago?" is the single most natural question a
radio listener asks. This service records each song change and answers
newest-first queries, per station or across all stations.

The ring-buffer cap keeps the table bounded: a station that publishes a
title every 20 seconds would otherwise add 4,320 rows a day. Old rows
are pruned on insert, so the table never grows without bound.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime
from typing import Optional

log = logging.getLogger("radiomaster")

#: Rows kept per station; older rows are pruned on insert.
MAX_ROWS_PER_STATION = 500


class SongHistoryService:
    """Records and queries song history. Thread-safe: the radio panel
    inserts from a background thread (never the wx thread)."""

    def __init__(self, db, max_rows: int = MAX_ROWS_PER_STATION):
        # DatabaseManager (thread-local connections) or a plain
        # sqlite3.Connection -- both accept execute/fetchall.
        self._db = db
        self._max_rows = max_rows
        self._lock = threading.Lock()

    def record(self, station_uuid: str, station_name: str,
               artist: str, title: str,
               played_at: Optional[datetime] = None) -> None:
        """Insert one song change and prune the per-station cap.

        Failures are logged and dropped, never raised: history is a
        convenience, and a failed insert must not take down the ICY
        watcher thread that feeds it."""
        played_at = played_at or datetime.now()
        with self._lock:
            try:
                self._db.execute(
                    "INSERT INTO song_history "
                    "(station_uuid, station_name, artist, title, played_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (station_uuid, station_name, artist, title,
                     played_at.isoformat(timespec="seconds")),
                )
                if hasattr(self._db, "commit"):
                    self._db.commit()
                self._prune(station_uuid)
            except sqlite3.Error:
                log.exception("Failed to record song history")

    def _prune(self, station_uuid: str) -> None:
        """Keep only the newest ``max_rows`` rows for *station_uuid*."""
        self._db.execute(
            "DELETE FROM song_history WHERE station_uuid = ? AND id NOT IN ("
            "  SELECT id FROM song_history WHERE station_uuid = ? "
            "  ORDER BY id DESC LIMIT ?)",
            (station_uuid, station_uuid, self._max_rows),
        )
        if hasattr(self._db, "commit"):
            self._db.commit()

    def recent(self, station_uuid: Optional[str] = None,
               limit: int = 100) -> list[dict]:
        """Newest-first history, optionally for one station. Rows carry
        artist, title, station name, and the spoken time ("at 3:42 PM")
        so the dialog can render sentences without re-formatting."""
        if station_uuid:
            rows = self._db.execute(
                "SELECT id, station_uuid, station_name, artist, title, played_at "
                "FROM song_history WHERE station_uuid = ? "
                "ORDER BY id DESC LIMIT ?",
                (station_uuid, limit),
            ).fetchall()
        else:
            rows = self._db.execute(
                "SELECT id, station_uuid, station_name, artist, title, played_at "
                "FROM song_history ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row) if not isinstance(row, sqlite3.Row) else {
                "id": row["id"], "station_uuid": row["station_uuid"],
                "station_name": row["station_name"], "artist": row["artist"],
                "title": row["title"], "played_at": row["played_at"],
            }
            item["spoken_time"] = self._spoken_time(item["played_at"])
            result.append(item)
        return result

    @staticmethod
    def _spoken_time(played_at: str) -> str:
        """'at 3:42 PM' -- words, never a bare 15:42."""
        try:
            dt = datetime.fromisoformat(played_at)
            return f"at {dt.strftime('%I:%M %p').lstrip('0')}"
        except (TypeError, ValueError):
            return ""