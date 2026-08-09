"""SQLite-backed local station catalog for fast indexed lookups."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
import uuid as uuid_module
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator, Optional

from radiomaster.utils.paths import get_paths
from radiomaster.services.station_api import Station

SCHEMA = """
CREATE TABLE IF NOT EXISTS stations (
    uuid TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    favicon TEXT DEFAULT '',
    tags TEXT DEFAULT '',
    country TEXT DEFAULT '',
    language TEXT DEFAULT '',
    codec TEXT DEFAULT '',
    bitrate INTEGER DEFAULT 0,
    votes INTEGER DEFAULT 0,
    homepage TEXT DEFAULT '',
    network TEXT DEFAULT '',
    languagecodes TEXT DEFAULT '',
    content_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_stations_country ON stations(country);
CREATE INDEX IF NOT EXISTS idx_stations_language ON stations(language);

CREATE TABLE IF NOT EXISTS station_genres (
    station_uuid TEXT NOT NULL REFERENCES stations(uuid) ON DELETE CASCADE,
    genre TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_station_genres_genre ON station_genres(genre);
CREATE INDEX IF NOT EXISTS idx_station_genres_uuid ON station_genres(station_uuid);

CREATE TABLE IF NOT EXISTS station_languages (
    station_uuid TEXT NOT NULL REFERENCES stations(uuid) ON DELETE CASCADE,
    language TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_station_languages_language ON station_languages(language);
CREATE INDEX IF NOT EXISTS idx_station_languages_uuid ON station_languages(station_uuid);

CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS custom_stations (
    uuid TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS favorite_stations (
    uuid TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    favicon TEXT DEFAULT '',
    tags TEXT DEFAULT '',
    country TEXT DEFAULT '',
    language TEXT DEFAULT '',
    codec TEXT DEFAULT '',
    bitrate INTEGER DEFAULT 0,
    votes INTEGER DEFAULT 0,
    homepage TEXT DEFAULT '',
    network TEXT DEFAULT '',
    languagecodes TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE VIRTUAL TABLE IF NOT EXISTS stations_fts USING fts5(
    uuid UNINDEXED, name, tokenize='trigram'
);
"""

_FIELDS = ["uuid", "name", "url", "favicon", "tags", "country", "language",
           "codec", "bitrate", "votes", "homepage", "network", "languagecodes"]

_STATION_COLUMNS = ("uuid, name, url, favicon, tags, country, language, codec, "
                     "bitrate, votes, homepage, network, languagecodes")


def _content_hash(station: Station) -> str:
    payload = "|".join(str(getattr(station, f)) for f in _FIELDS if f != "uuid")
    return hashlib.sha1(payload.encode("utf-8", errors="ignore")).hexdigest()


class StationDB:
    def __init__(self, path: Optional[str] = None):
        paths = get_paths()
        self._path = path or os.path.join(paths["data"], "stations.db")
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(stations)").fetchall()}
        if "network" not in columns:
            conn.execute("ALTER TABLE stations ADD COLUMN network TEXT DEFAULT ''")
        if "languagecodes" not in columns:
            conn.execute("ALTER TABLE stations ADD COLUMN languagecodes TEXT DEFAULT ''")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_stations_network ON stations(network)")
        fts_count = conn.execute("SELECT COUNT(*) FROM stations_fts").fetchone()[0]
        total = conn.execute("SELECT COUNT(*) FROM stations").fetchone()[0]
        if fts_count == 0 and total > 0:
            conn.execute("INSERT INTO stations_fts(uuid, name) SELECT uuid, name FROM stations")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path, timeout=30)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def upsert_stations(self, stations: list[Station]) -> tuple[int, int]:
        changed = 0
        unchanged = 0
        with self._lock, self._connect() as conn:
            cur = conn.cursor()
            existing_hashes = dict(cur.execute("SELECT uuid, content_hash FROM stations").fetchall())
            for station in stations:
                if not station.uuid:
                    continue
                new_hash = _content_hash(station)
                if existing_hashes.get(station.uuid) == new_hash:
                    unchanged += 1
                    continue
                changed += 1
                cur.execute(
                    """INSERT INTO stations
                       (uuid, name, url, favicon, tags, country, language, codec,
                        bitrate, votes, homepage, network, languagecodes, content_hash)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(uuid) DO UPDATE SET
                           name=excluded.name, url=excluded.url, favicon=excluded.favicon,
                           tags=excluded.tags, country=excluded.country, language=excluded.language,
                           codec=excluded.codec, bitrate=excluded.bitrate, votes=excluded.votes,
                           homepage=excluded.homepage, network=excluded.network,
                           languagecodes=excluded.languagecodes,
                           content_hash=excluded.content_hash""",
                    (station.uuid, station.name, station.url, station.favicon, station.tags,
                     station.country, station.language, station.codec, station.bitrate,
                     station.votes, station.homepage, station.network, station.languagecodes, new_hash),
                )
                cur.execute("DELETE FROM station_genres WHERE station_uuid = ?", (station.uuid,))
                for genre in station.genres:
                    cur.execute(
                        "INSERT INTO station_genres (station_uuid, genre) VALUES (?, ?)",
                        (station.uuid, genre),
                    )
                cur.execute("DELETE FROM station_languages WHERE station_uuid = ?", (station.uuid,))
                for iso_language in station.iso_languages:
                    cur.execute(
                        "INSERT INTO station_languages (station_uuid, language) VALUES (?, ?)",
                        (station.uuid, iso_language),
                    )
            if changed:
                cur.execute("DELETE FROM stations_fts")
                cur.execute("INSERT INTO stations_fts(uuid, name) SELECT uuid, name FROM stations")
        self.set_metadata("last_updated", datetime.now().isoformat())
        return changed, unchanged

    def station_count(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM stations").fetchone()[0]

    def genre_groups(self, limit: int = 200000, min_count: int = 1) -> list[tuple[str, int]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT genre, COUNT(*) c FROM station_genres
                   GROUP BY genre HAVING c >= ? ORDER BY genre COLLATE NOCASE ASC LIMIT ?""",
                (min_count, limit),
            ).fetchall()
        return list(rows)

    def country_groups(self, limit: int = 200000, min_count: int = 1) -> list[tuple[str, int]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT country, COUNT(*) c FROM stations
                   WHERE country != '' GROUP BY country HAVING c >= ?
                   ORDER BY country COLLATE NOCASE ASC LIMIT ?""",
                (min_count, limit),
            ).fetchall()
        return list(rows)

    def language_groups(self, limit: int = 200000, min_count: int = 1) -> list[tuple[str, int]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT language, COUNT(*) c FROM station_languages
                   GROUP BY language HAVING c >= ?
                   ORDER BY language COLLATE NOCASE ASC LIMIT ?""",
                (min_count, limit),
            ).fetchall()
        return list(rows)

    def network_groups(self, limit: int = 200000, min_count: int = 1) -> list[tuple[str, int]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT network, COUNT(*) c FROM stations
                   WHERE network != '' GROUP BY network HAVING c >= ?
                   ORDER BY network COLLATE NOCASE ASC LIMIT ?""",
                (min_count, limit),
            ).fetchall()
        return list(rows)

    _ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    def alphabet_groups(self) -> list[tuple[str, int]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT name FROM stations").fetchall()
        buckets: dict[str, int] = {}
        for (name,) in rows:
            stripped = (name or "").strip()
            first = stripped[:1].upper() if stripped else "#"
            key = first if first in self._ALPHABET else "#"
            buckets[key] = buckets.get(key, 0) + 1
        return sorted(buckets.items(), key=lambda kv: (kv[0] != "#", kv[0]))

    def all_stations(self, limit: int = 200000) -> list[Station]:
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT {_STATION_COLUMNS} FROM stations
                    ORDER BY name COLLATE NOCASE ASC LIMIT ?""",
                (limit,),
            ).fetchall()
        return self._rows_to_stations(rows)

    def stations_by_letter(self, letter: str, limit: int = 200000) -> list[Station]:
        with self._connect() as conn:
            if letter == "#":
                clause = "upper(substr(name, 1, 1)) NOT BETWEEN 'A' AND 'Z'"
                params = (limit,)
            else:
                clause = "upper(substr(name, 1, 1)) = ?"
                params = (letter, limit)
            rows = conn.execute(
                f"""SELECT {_STATION_COLUMNS} FROM stations
                    WHERE {clause} ORDER BY name COLLATE NOCASE ASC LIMIT ?""",
                params,
            ).fetchall()
        return self._rows_to_stations(rows)

    def _rows_to_stations(self, rows) -> list[Station]:
        return [Station(uuid=r[0], name=r[1], url=r[2], favicon=r[3], tags=r[4],
                         country=r[5], language=r[6], codec=r[7], bitrate=r[8],
                         votes=r[9], homepage=r[10], network=r[11], languagecodes=r[12]) for r in rows]

    def add_custom(self, name: str, url: str) -> Station:
        """Add a user-entered custom station and return it as a Station."""
        station_uuid = f"custom-{uuid_module.uuid4()}"
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO custom_stations (uuid, name, url) VALUES (?, ?, ?)",
                (station_uuid, name, url),
            )
        return Station(uuid=station_uuid, name=name, url=url, network="Custom")

    def get_custom_stations(self) -> list[Station]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT uuid, name, url FROM custom_stations ORDER BY name COLLATE NOCASE ASC"
            ).fetchall()
        return [Station(uuid=r[0], name=r[1], url=r[2], network="Custom") for r in rows]

    def add_favorite(self, station: Station) -> None:
        """Bookmarks *station* -- stores its full metadata (not just a
        reference to the catalog) so it stays a complete, playable entry
        in Favorites even if the station is later dropped from a catalog
        refresh, same reasoning as custom_stations. INSERT OR REPLACE:
        re-favoriting an already-favorited station just refreshes its
        stored metadata rather than erroring on the uuid PK collision."""
        with self._lock, self._connect() as conn:
            conn.execute(
                f"""INSERT OR REPLACE INTO favorite_stations ({_STATION_COLUMNS})
                VALUES ({', '.join('?' for _ in _FIELDS)})""",
                tuple(getattr(station, f) for f in _FIELDS),
            )

    def remove_favorite(self, station_uuid: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM favorite_stations WHERE uuid = ?", (station_uuid,))

    def is_favorite(self, station_uuid: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM favorite_stations WHERE uuid = ?", (station_uuid,)
            ).fetchone()
        return row is not None

    def get_favorite_stations(self) -> list[Station]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {_STATION_COLUMNS} FROM favorite_stations ORDER BY name COLLATE NOCASE ASC"
            ).fetchall()
        return self._rows_to_stations(rows)

    def stations_by_genre(self, genre: str, limit: int = 200000) -> list[Station]:
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT {', '.join(f's.{c.strip()}' for c in _STATION_COLUMNS.split(','))}
                   FROM stations s JOIN station_genres g ON g.station_uuid = s.uuid
                   WHERE g.genre = ? ORDER BY s.name COLLATE NOCASE ASC LIMIT ?""",
                (genre, limit),
            ).fetchall()
        return self._rows_to_stations(rows)

    def stations_by_country(self, country: str, limit: int = 200000) -> list[Station]:
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT {_STATION_COLUMNS} FROM stations
                   WHERE country = ? ORDER BY name COLLATE NOCASE ASC LIMIT ?""",
                (country, limit),
            ).fetchall()
        return self._rows_to_stations(rows)

    def stations_by_language(self, language: str, limit: int = 200000) -> list[Station]:
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT {', '.join(f's.{c.strip()}' for c in _STATION_COLUMNS.split(','))}
                   FROM stations s JOIN station_languages l ON l.station_uuid = s.uuid
                   WHERE l.language = ? ORDER BY s.name COLLATE NOCASE ASC LIMIT ?""",
                (language, limit),
            ).fetchall()
        return self._rows_to_stations(rows)

    def stations_by_network(self, network: str, limit: int = 200000) -> list[Station]:
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT {_STATION_COLUMNS} FROM stations
                   WHERE network = ? ORDER BY name COLLATE NOCASE ASC LIMIT ?""",
                (network, limit),
            ).fetchall()
        return self._rows_to_stations(rows)

    def search_local(self, query: str, limit: int = 500) -> list[Station]:
        with self._connect() as conn:
            matches = conn.execute(
                """SELECT uuid FROM stations_fts WHERE name LIKE ?
                   ORDER BY name COLLATE NOCASE ASC LIMIT ?""",
                (f"%{query}%", limit),
            ).fetchall()
            uuids = [row[0] for row in matches]
            if not uuids:
                return []
            placeholders = ",".join("?" * len(uuids))
            rows = conn.execute(
                f"""SELECT {_STATION_COLUMNS} FROM stations WHERE uuid IN ({placeholders})
                   ORDER BY name COLLATE NOCASE ASC""",
                uuids,
            ).fetchall()
        return self._rows_to_stations(rows)

    def get_metadata(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def set_metadata(self, key: str, value: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO metadata (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def last_updated(self) -> Optional[datetime]:
        value = self.get_metadata("last_updated")
        return datetime.fromisoformat(value) if value else None
