"""Database connection manager for RadioMaster+."""

import os
import sqlite3
import threading
from typing import Any

from radiomaster.database.migrations import run_migrations


class DatabaseManager:
    """Manages the SQLite database connection and provides thread-safe access."""

    def __init__(self, data_dir: str) -> None:
        self._data_dir = data_dir
        self._db_path = os.path.join(data_dir, "radiomaster.db")
        self._local = threading.local()

    def initialize(self) -> None:
        """Create the database directory and run migrations."""
        os.makedirs(self._data_dir, exist_ok=True)
        run_migrations(self._get_connection())

    def _get_connection(self) -> sqlite3.Connection:
        """Get a thread-local database connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self._db_path)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA foreign_keys=ON")
        return self._local.conn

    @property
    def conn(self) -> sqlite3.Connection:
        """Get the thread-local connection."""
        return self._get_connection()

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        """Execute a query and return the cursor."""
        return self.conn.execute(sql, params)

    def executemany(self, sql: str, params: list[tuple[Any, ...]]) -> sqlite3.Cursor:
        """Execute a query with multiple parameter sets."""
        return self.conn.executemany(sql, params)

    def fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        """Fetch a single row as a dict."""
        row = self.conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        """Fetch all rows as dicts."""
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def commit(self) -> None:
        """Commit the current transaction."""
        self.conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
