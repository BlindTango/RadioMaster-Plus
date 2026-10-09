"""Listening statistics: records real playback time and aggregates it.

A "session" is one continuous stretch of playback. Pause, stop, and
switching to a different source all end the current session, so
seconds_listened only ever counts time audio was actually audible --
buffering and paused time are never counted. The service hooks the
PlaybackEngine's on_state_change callback (the engine fires it from its
monitor thread, so the service is thread-safe and never touches wx).
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

log = logging.getLogger("radiomaster")


@dataclass
class SessionTotals:
    """Aggregated listening time for one period."""
    seconds: int
    sessions: int


def _now() -> datetime:
    return datetime.now()


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _parse(value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


class StatsService:
    """Records listening sessions from PlaybackEngine state changes.

    The engine's on_state_change is a single callback slot, so MainWindow
    chains this service in front of its own UI handler (see
    MainWindow._setup_engine_callbacks) rather than the service
    overwriting the UI's registration.
    """

    def __init__(self, db) -> None:
        # DatabaseManager (thread-local connections) or a plain
        # sqlite3.Connection -- both accept execute/fetchone/fetchall.
        self._db = db
        self._lock = threading.Lock()
        self._session_start: Optional[datetime] = None
        self._session_source_type = ""
        self._session_source_id = ""
        self._session_title = ""

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------
    def on_state_change(self, state: str, source_type: str = "",
                        source_id: str = "", title: str = "") -> None:
        """Engine state hook. The source_* arguments are supplied by
        MainWindow's chaining wrapper (the engine's own callback carries
        only the state string); they identify *what* is playing so
        top-stations/top-shows aggregations have something to group by."""
        with self._lock:
            if state == "playing":
                # A new play() (different source) ends the previous
                # session first so its time isn't lost.
                if self._session_start is not None and (
                        source_type != self._session_source_type
                        or source_id != self._session_source_id):
                    self._end_session_locked()
                if self._session_start is None:
                    self._session_start = _now()
                    self._session_source_type = source_type
                    self._session_source_id = source_id
                    self._session_title = title
                return
            # paused/stopped/buffering all suspend the session; only
            # "playing" resumes it. Buffering mid-stream ends the session
            # so the reconnect gap isn't counted as listening time.
            if self._session_start is not None:
                self._end_session_locked()

    def _end_session_locked(self) -> None:
        start = self._session_start
        self._session_start = None
        if start is None:
            return
        seconds = max(0, int((_now() - start).total_seconds()))
        if seconds <= 0:
            return
        try:
            self._db.execute(
                "INSERT INTO listening_sessions "
                "(source_type, source_id, title, started_at, ended_at, seconds_listened) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (self._session_source_type, self._session_source_id,
                 self._session_title, _iso(start), _iso(_now()), seconds),
            )
            if hasattr(self._db, "commit"):
                self._db.commit()
        except sqlite3.Error:
            # Statistics must never break playback -- a failed insert is
            # logged and dropped, not raised into the engine's monitor
            # thread (which would kill the monitor loop).
            log.exception("Failed to record listening session")

    def flush(self) -> None:
        """End and persist any open session (app exit)."""
        with self._lock:
            if self._session_start is not None:
                self._end_session_locked()

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------
    def totals(self, since: Optional[datetime] = None) -> SessionTotals:
        """Total listening time, optionally from *since* onward."""
        if since is None:
            row = self._db.execute(
                "SELECT COALESCE(SUM(seconds_listened), 0), COUNT(*) "
                "FROM listening_sessions"
            ).fetchone()
        else:
            row = self._db.execute(
                "SELECT COALESCE(SUM(seconds_listened), 0), COUNT(*) "
                "FROM listening_sessions WHERE started_at >= ?",
                (_iso(since),),
            ).fetchone()
        return SessionTotals(seconds=int(row[0]), sessions=int(row[1]))

    def start_of_today(self) -> datetime:
        return _now().replace(hour=0, minute=0, second=0, microsecond=0)

    def start_of_week(self) -> datetime:
        """Monday 00:00 of the current week (ISO week start)."""
        today = self.start_of_today()
        return today - timedelta(days=today.weekday())

    def top_items(self, source_type: str, limit: int = 5,
                  since: Optional[datetime] = None) -> list[tuple[str, int]]:
        """Top sources of one type (e.g. stations) by total seconds."""
        params: list = [source_type]
        where = "source_type = ?"
        if since is not None:
            where += " AND started_at >= ?"
            params.append(_iso(since))
        params.append(limit)
        rows = self._db.execute(
            f"SELECT COALESCE(NULLIF(title, ''), source_id) AS label, "
            f"SUM(seconds_listened) AS secs FROM listening_sessions "
            f"WHERE {where} GROUP BY label "
            f"ORDER BY secs DESC LIMIT ?",
            tuple(params),
        ).fetchall()
        return [(row[0], int(row[1])) for row in rows]