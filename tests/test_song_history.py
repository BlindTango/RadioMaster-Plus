"""Tests for the Song History service (services/song_history.py)."""

import sqlite3
from datetime import datetime, timedelta

import pytest

from radiomaster.database.connection import DatabaseManager
from radiomaster.services.song_history import SongHistoryService


@pytest.fixture
def db(tmp_path):
    manager = DatabaseManager(str(tmp_path))
    manager.initialize()
    yield manager
    manager.close()


@pytest.fixture
def service(db):
    return SongHistoryService(db)


def test_record_and_recent_newest_first(service):
    service.record("uuid1", "Station One", "Artist A", "Song 1",
                   played_at=datetime(2026, 10, 9, 10, 0, 0))
    service.record("uuid1", "Station One", "Artist B", "Song 2",
                   played_at=datetime(2026, 10, 9, 11, 0, 0))
    rows = service.recent(station_uuid="uuid1")
    assert len(rows) == 2
    # Newest first.
    assert rows[0]["title"] == "Song 2"
    assert rows[1]["title"] == "Song 1"


def test_recent_filters_by_station(service):
    service.record("uuid1", "Station One", "Artist A", "Song 1")
    service.record("uuid2", "Station Two", "Artist B", "Song 2")
    only_one = service.recent(station_uuid="uuid1")
    assert len(only_one) == 1
    assert only_one[0]["station_name"] == "Station One"
    everything = service.recent()
    assert len(everything) == 2


def test_ring_buffer_prunes_old_rows(service):
    for i in range(600):
        service.record("uuid1", "Station One", "Artist", f"Song {i}")
    rows = service.recent(station_uuid="uuid1", limit=1000)
    assert len(rows) == 500
    # The newest 500 survive; the oldest 100 are gone.
    assert rows[0]["title"] == "Song 599"
    assert rows[-1]["title"] == "Song 100"


def test_prune_is_per_station(service):
    for i in range(600):
        service.record("uuid1", "Station One", "Artist", f"Song {i}")
    service.record("uuid2", "Station Two", "Artist", "Other Song")
    # The other station's rows are untouched by uuid1's pruning.
    assert len(service.recent(station_uuid="uuid2")) == 1


def test_spoken_time_is_words(service):
    service.record("uuid1", "Station One", "Artist", "Song",
                   played_at=datetime(2026, 10, 9, 15, 42, 0))
    row = service.recent()[0]
    assert row["spoken_time"] == "at 3:42 PM"


def test_record_failure_is_swallowed(db, service):
    """History must never break the ICY watcher: a broken DB write is
    logged and dropped, not raised into the watcher thread."""
    original = db.execute
    db.execute = lambda *a, **k: (_ for _ in ()).throw(sqlite3.OperationalError("boom"))
    service.record("uuid1", "Station One", "Artist", "Song")  # must not raise
    db.execute = original
    # The DB still answers queries afterward.
    assert service.recent() == []


def test_limit_is_respected(service):
    for i in range(50):
        service.record("uuid1", "Station One", "Artist", f"Song {i}")
    assert len(service.recent(limit=10)) == 10