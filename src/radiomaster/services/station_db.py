"""SQLite-backed local station catalog for fast indexed lookups."""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import threading
import uuid as uuid_module
from contextlib import contextmanager
from datetime import datetime, timedelta
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

CREATE TABLE IF NOT EXISTS hidden_stations (
    uuid TEXT PRIMARY KEY,
    reason TEXT DEFAULT '',
    hidden_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS station_health (
    uuid TEXT PRIMARY KEY,
    checked_at TEXT NOT NULL,
    stream_ok INTEGER DEFAULT 0,
    name_ok INTEGER DEFAULT 1,
    website_ok INTEGER DEFAULT 1,
    geo_blocked INTEGER DEFAULT 0,
    status TEXT DEFAULT '',
    detail TEXT DEFAULT '',
    codec TEXT DEFAULT '',
    sample_rate INTEGER DEFAULT 0,
    channels INTEGER DEFAULT 0,
    bit_rate INTEGER DEFAULT 0,
    db_codec TEXT DEFAULT '',
    db_bitrate INTEGER DEFAULT 0,
    format_mismatch INTEGER DEFAULT 0
);
"""

_FIELDS = ["uuid", "name", "url", "favicon", "tags", "country", "language",
           "codec", "bitrate", "votes", "homepage", "network", "languagecodes"]

_STATION_COLUMNS = ("uuid, name, url, favicon, tags, country, language, codec, "
                     "bitrate, votes, homepage, network, languagecodes")

# Appended to every catalog browse query so stations hidden via the
# Station Health Check (dead streams etc.) never appear in browse
# lists, group counts, or search. The hidden_stations table is a
# separate blacklist rather than a DELETE because the weekly catalog
# sync (upsert_stations) would re-insert anything still in the
# Radio-Browser feed -- the blacklist survives it untouched.
_NOT_HIDDEN = "uuid NOT IN (SELECT uuid FROM hidden_stations)"


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
                f"""SELECT genre, COUNT(*) c FROM station_genres g
                   JOIN stations s ON s.uuid = g.station_uuid
                   WHERE s.{_NOT_HIDDEN}
                   GROUP BY genre HAVING c >= ? ORDER BY genre COLLATE NOCASE ASC LIMIT ?""",
                (min_count, limit),
            ).fetchall()
        return list(rows)

    def country_groups(self, limit: int = 200000, min_count: int = 1) -> list[tuple[str, int]]:
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT country, COUNT(*) c FROM stations
                   WHERE country != '' AND {_NOT_HIDDEN}
                   GROUP BY country HAVING c >= ?
                   ORDER BY country COLLATE NOCASE ASC LIMIT ?""",
                (min_count, limit),
            ).fetchall()
        return list(rows)

    def language_groups(self, limit: int = 200000, min_count: int = 1) -> list[tuple[str, int]]:
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT l.language, COUNT(*) c FROM station_languages l
                   JOIN stations s ON s.uuid = l.station_uuid
                   WHERE s.{_NOT_HIDDEN}
                   GROUP BY l.language HAVING c >= ?
                   ORDER BY l.language COLLATE NOCASE ASC LIMIT ?""",
                (min_count, limit),
            ).fetchall()
        return list(rows)

    def network_groups(self, limit: int = 200000, min_count: int = 1) -> list[tuple[str, int]]:
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT network, COUNT(*) c FROM stations
                   WHERE network != '' AND {_NOT_HIDDEN}
                   GROUP BY network HAVING c >= ?
                   ORDER BY network COLLATE NOCASE ASC LIMIT ?""",
                (min_count, limit),
            ).fetchall()
        return list(rows)

    _ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    def alphabet_groups(self) -> list[tuple[str, int]]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT name FROM stations WHERE {_NOT_HIDDEN}"
            ).fetchall()
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
                    WHERE {_NOT_HIDDEN}
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
                    WHERE {clause} AND {_NOT_HIDDEN}
                    ORDER BY name COLLATE NOCASE ASC LIMIT ?""",
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
                   WHERE g.genre = ? AND s.{_NOT_HIDDEN}
                   ORDER BY s.name COLLATE NOCASE ASC LIMIT ?""",
                (genre, limit),
            ).fetchall()
        return self._rows_to_stations(rows)

    def stations_by_country(self, country: str, limit: int = 200000) -> list[Station]:
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT {_STATION_COLUMNS} FROM stations
                   WHERE country = ? AND {_NOT_HIDDEN}
                   ORDER BY name COLLATE NOCASE ASC LIMIT ?""",
                (country, limit),
            ).fetchall()
        return self._rows_to_stations(rows)

    def stations_by_language(self, language: str, limit: int = 200000) -> list[Station]:
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT {', '.join(f's.{c.strip()}' for c in _STATION_COLUMNS.split(','))}
                   FROM stations s JOIN station_languages l ON l.station_uuid = s.uuid
                   WHERE l.language = ? AND s.{_NOT_HIDDEN}
                   ORDER BY s.name COLLATE NOCASE ASC LIMIT ?""",
                (language, limit),
            ).fetchall()
        return self._rows_to_stations(rows)

    def stations_by_network(self, network: str, limit: int = 200000) -> list[Station]:
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT {_STATION_COLUMNS} FROM stations
                   WHERE network = ? AND {_NOT_HIDDEN}
                   ORDER BY name COLLATE NOCASE ASC LIMIT ?""",
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
                f"""SELECT {_STATION_COLUMNS} FROM stations
                   WHERE uuid IN ({placeholders}) AND {_NOT_HIDDEN}
                   ORDER BY name COLLATE NOCASE ASC""",
                uuids,
            ).fetchall()
        return self._rank_by_match_quality(self._rows_to_stations(rows), query)

    def _rank_by_match_quality(self, stations: list[Station], query: str) -> list[Station]:
        """search_local's SQL is a plain LIKE '%query%' -- it matches the
        query text ANYWHERE in a station's name, including buried in the
        middle of an unrelated word. Confirmed live: searching "KAMU"
        (the Texas A&M NPR affiliate) surfaces "Skamusic Munster" purely
        because those four letters happen to appear inside "Skamusic" --
        nothing to do with KAMU at all -- and alphabetical order doesn't
        distinguish a real match from that kind of coincidence. Someone
        typing a station's name expects that name, not a substring
        collision, so rank a real word-boundary match ahead of a
        mid-word one instead of leaving A-Z as the only sort key."""
        q = query.strip().lower()
        if not q:
            return stations
        word_boundary = re.compile(r"(?:^|[^a-z0-9])" + re.escape(q), re.IGNORECASE)

        def rank(station: Station) -> tuple[int, str]:
            name = station.name or ""
            lname = name.lower()
            if lname == q:
                tier = 0
            elif lname.startswith(q):
                tier = 1
            elif word_boundary.search(name):
                tier = 2
            else:
                tier = 3  # mid-word substring only, e.g. "Skamusic" for "KAMU"
            return (tier, lname)

        return sorted(stations, key=rank)

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

    # ------------------------------------------------------------------
    # Hidden stations (Station Health Check blacklist) -- see
    # _NOT_HIDDEN's comment for why this is a table and not a DELETE.
    # ------------------------------------------------------------------
    def hide_station(self, station_uuid: str, reason: str = "") -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO hidden_stations (uuid, reason) VALUES (?, ?)",
                (station_uuid, reason),
            )

    def unhide_station(self, station_uuid: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM hidden_stations WHERE uuid = ?", (station_uuid,))

    def unhide_all(self) -> int:
        """Clear the entire blacklist; returns the number of stations
        that were hidden (0 if it was already empty)."""
        with self._lock, self._connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM hidden_stations").fetchone()[0]
            conn.execute("DELETE FROM hidden_stations")
        return count

    def hidden_stations(self) -> list[tuple[str, str, str]]:
        """(uuid, name, reason) for every blacklisted station, newest
        first. Joins the catalog for the name; a hidden station that
        was dropped from the catalog entirely falls back to the uuid
        (favorites/custom keep their own rows, so this is rare)."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT h.uuid, COALESCE(s.name, f.name, c.name, h.uuid), h.reason
                   FROM hidden_stations h
                   LEFT JOIN stations s ON s.uuid = h.uuid
                   LEFT JOIN favorite_stations f ON f.uuid = h.uuid
                   LEFT JOIN custom_stations c ON c.uuid = h.uuid
                   ORDER BY h.hidden_at DESC, h.uuid"""
            ).fetchall()
        return list(rows)

    def hidden_count(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM hidden_stations").fetchone()[0]

    def hidden_uuids(self) -> set[str]:
        with self._connect() as conn:
            return {row[0] for row in conn.execute("SELECT uuid FROM hidden_stations")}

    # ------------------------------------------------------------------
    # Station health results -- written in batches by the health-check
    # scan's UI timer, read back when the dialog opens (so past results
    # are visible immediately) and for the resume filter.
    # ------------------------------------------------------------------
    _HEALTH_COLUMNS = ("uuid, checked_at, stream_ok, name_ok, website_ok, geo_blocked, "
                       "status, detail, codec, sample_rate, channels, bit_rate, "
                       "db_codec, db_bitrate, format_mismatch")

    def record_health_results(self, results: list[dict]) -> None:
        """Batched INSERT OR REPLACE of health-check rows. Each dict must
        carry the _HEALTH_COLUMNS keys (checked_at filled in here if the
        caller didn't set it)."""
        if not results:
            return
        now = datetime.now().isoformat()
        rows = []
        for r in results:
            rows.append((
                r["uuid"], r.get("checked_at") or now,
                int(bool(r.get("stream_ok"))), int(r.get("name_ok", 1) or 1),
                int(r.get("website_ok", 1) or 1), int(bool(r.get("geo_blocked"))),
                r.get("status", ""), r.get("detail", ""),
                r.get("codec", ""), int(r.get("sample_rate", 0) or 0),
                int(r.get("channels", 0) or 0), int(r.get("bit_rate", 0) or 0),
                r.get("db_codec", ""), int(r.get("db_bitrate", 0) or 0),
                int(bool(r.get("format_mismatch"))),
            ))
        with self._lock, self._connect() as conn:
            conn.executemany(
                f"""INSERT OR REPLACE INTO station_health ({self._HEALTH_COLUMNS})
                VALUES ({', '.join('?' * 15)})""",
                rows,
            )

    def health_results(self, problems_only: bool = True) -> list[dict]:
        """All persisted health rows (newest first), optionally only the
        problem ones -- a row is a problem when the stream is dead, the
        name mismatches, the website is down, it's geo-blocked, or the
        format differs from the database's claims."""
        where = ""
        if problems_only:
            where = ("WHERE stream_ok = 0 OR name_ok = 0 OR website_ok = 0 "
                     "OR geo_blocked = 1 OR format_mismatch = 1")
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT {self._HEALTH_COLUMNS} FROM station_health {where}
                    ORDER BY checked_at DESC, uuid"""
            ).fetchall()
        cols = [c.strip() for c in self._HEALTH_COLUMNS.split(",")]
        return [dict(zip(cols, row, strict=False)) for row in rows]

    def recently_checked_uuids(self, days: float) -> set[str]:
        """uuids with a health row newer than *days* days -- the resume
        filter, so a restarted scan doesn't re-pay the timeout cost for
        stations checked moments ago."""
        if days <= 0:
            return set()
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with self._connect() as conn:
            return {row[0] for row in conn.execute(
                "SELECT uuid FROM station_health WHERE checked_at > ?", (cutoff,))}
