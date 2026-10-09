"""Tests for listening statistics: migration, session recording, aggregation."""

from datetime import datetime, timedelta

import pytest

from radiomaster.database.connection import DatabaseManager
from radiomaster.services.stats_service import StatsService


@pytest.fixture
def db() -> DatabaseManager:
    import tempfile
    tmp_dir = tempfile.mkdtemp()
    manager = DatabaseManager(tmp_dir)
    manager.initialize()
    yield manager
    manager.close()


@pytest.fixture
def stats(db: DatabaseManager) -> StatsService:
    return StatsService(db)


class TestListeningSessionsMigration:
    def test_listening_sessions_table_exists(self, db: DatabaseManager) -> None:
        row = db.fetchone(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='listening_sessions'"
        )
        assert row is not None

    def test_listening_sessions_columns(self, db: DatabaseManager) -> None:
        columns = {
            r["name"] for r in db.fetchall("PRAGMA table_info(listening_sessions)")
        }
        assert columns == {
            "id", "source_type", "source_id", "title",
            "started_at", "ended_at", "seconds_listened",
        }


class TestSessionRecording:
    def test_playing_starts_a_session(self, stats: StatsService, db: DatabaseManager,
                                      monkeypatch) -> None:
        times = iter([datetime(2026, 10, 9, 10, 0, 0), datetime(2026, 10, 9, 10, 5, 0),
                      datetime(2026, 10, 9, 10, 5, 0)])
        monkeypatch.setattr("radiomaster.services.stats_service._now", lambda: next(times))
        stats.on_state_change("playing", source_type="station",
                              source_id="http://a", title="A Radio")
        stats.on_state_change("stopped")
        rows = db.fetchall("SELECT * FROM listening_sessions")
        assert len(rows) == 1
        assert rows[0]["source_type"] == "station"
        assert rows[0]["title"] == "A Radio"
        assert rows[0]["seconds_listened"] == 300

    def test_pause_ends_session_not_playing_time(self, stats: StatsService, db: DatabaseManager,
                                                 monkeypatch) -> None:
        # Pause must end the session so paused time is never counted.
        clock = {"t": datetime(2026, 10, 9, 10, 0, 0)}

        def tick():
            clock["t"] += timedelta(minutes=1)
            return clock["t"]

        monkeypatch.setattr("radiomaster.services.stats_service._now", tick)
        stats.on_state_change("playing", source_type="station", source_id="u1")
        stats.on_state_change("paused")
        stats.on_state_change("playing", source_type="station", source_id="u1")
        stats.on_state_change("stopped")
        rows = db.fetchall("SELECT * FROM listening_sessions")
        assert len(rows) == 2
        # Each session counted exactly its 1 minute of playing time.
        assert all(r["seconds_listened"] == 60 for r in rows)

    def test_buffering_ends_session(self, stats: StatsService, db: DatabaseManager,
                                    monkeypatch) -> None:
        # A buffering gap mid-stream is not listening time.
        clock = {"t": datetime(2026, 10, 9, 10, 0, 0)}

        def tick():
            clock["t"] += timedelta(seconds=30)
            return clock["t"]

        monkeypatch.setattr("radiomaster.services.stats_service._now", tick)
        stats.on_state_change("playing", source_type="station", source_id="u1")
        stats.on_state_change("buffering")
        stats.on_state_change("playing", source_type="station", source_id="u1")
        stats.flush()
        rows = db.fetchall("SELECT * FROM listening_sessions")
        assert len(rows) == 2

    def test_switching_source_ends_previous_session(
            self, stats: StatsService, db: DatabaseManager, monkeypatch) -> None:
        clock = {"t": datetime(2026, 10, 9, 10, 0, 0)}

        def tick():
            clock["t"] += timedelta(minutes=2)
            return clock["t"]

        monkeypatch.setattr("radiomaster.services.stats_service._now", tick)
        stats.on_state_change("playing", source_type="station", source_id="a")
        stats.on_state_change("playing", source_type="station", source_id="b")
        stats.flush()
        rows = db.fetchall("SELECT * FROM listening_sessions ORDER BY id")
        assert len(rows) == 2
        assert rows[0]["source_id"] == "a"
        assert rows[1]["source_id"] == "b"

    def test_flush_persists_open_session(self, stats: StatsService, db: DatabaseManager,
                                         monkeypatch) -> None:
        times = iter([datetime(2026, 10, 9, 10, 0, 0), datetime(2026, 10, 9, 10, 1, 0),
                      datetime(2026, 10, 9, 10, 1, 0)])
        monkeypatch.setattr("radiomaster.services.stats_service._now", lambda: next(times))
        stats.on_state_change("playing", source_type="station", source_id="u1")
        stats.flush()
        rows = db.fetchall("SELECT * FROM listening_sessions")
        assert len(rows) == 1
        assert rows[0]["seconds_listened"] == 60

    def test_subsecond_session_is_not_recorded(self, stats: StatsService,
                                               db: DatabaseManager) -> None:
        """A play/stop blip shorter than a second is not listening --
        no row, so session counts only reflect real listening."""
        stats.on_state_change("playing", source_type="station", source_id="u1")
        stats.on_state_change("stopped")
        assert db.fetchall("SELECT * FROM listening_sessions") == []

    def test_stop_without_play_is_noop(self, stats: StatsService,
                                       db: DatabaseManager) -> None:
        stats.on_state_change("stopped")
        assert db.fetchall("SELECT * FROM listening_sessions") == []


class TestAggregation:
    def test_totals_all_time(self, stats: StatsService, db: DatabaseManager) -> None:
        db.execute(
            "INSERT INTO listening_sessions (source_type, source_id, title, "
            "started_at, ended_at, seconds_listened) VALUES (?, ?, ?, ?, ?, ?)",
            ("station", "u1", "A Radio", "2026-01-01T10:00:00", "2026-01-01T11:00:00", 3600),
        )
        db.commit()
        totals = stats.totals()
        assert totals.seconds == 3600
        assert totals.sessions == 1

    def test_totals_since_filters_old_rows(self, stats: StatsService,
                                           db: DatabaseManager) -> None:
        db.execute(
            "INSERT INTO listening_sessions (source_type, source_id, title, "
            "started_at, ended_at, seconds_listened) VALUES (?, ?, ?, ?, ?, ?)",
            ("station", "u1", "Old", "2020-01-01T10:00:00", "2020-01-01T11:00:00", 3600),
        )
        db.execute(
            "INSERT INTO listening_sessions (source_type, source_id, title, "
            "started_at, ended_at, seconds_listened) VALUES (?, ?, ?, ?, ?, ?)",
            ("station", "u2", "New", datetime.now().isoformat(timespec="seconds"),
             datetime.now().isoformat(timespec="seconds"), 600),
        )
        db.commit()
        totals = stats.totals(since=datetime.now() - timedelta(days=1))
        assert totals.seconds == 600
        assert totals.sessions == 1

    def test_top_items_groups_by_title(self, stats: StatsService, db: DatabaseManager) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        for source_id, title, secs in (("u1", "A Radio", 100), ("u1", "A Radio", 50),
                                       ("u2", "B Radio", 200)):
            db.execute(
                "INSERT INTO listening_sessions (source_type, source_id, title, "
                "started_at, ended_at, seconds_listened) VALUES (?, ?, ?, ?, ?, ?)",
                ("station", source_id, title, now, now, secs),
            )
        db.commit()
        top = stats.top_items("station", limit=5)
        assert top[0] == ("B Radio", 200)
        assert top[1] == ("A Radio", 150)

    def test_top_items_empty(self, stats: StatsService) -> None:
        assert stats.top_items("station") == []

    def test_start_of_week_is_monday(self, stats: StatsService) -> None:
        start = stats.start_of_week()
        assert start.weekday() == 0
        assert start.hour == 0 and start.minute == 0 and start.second == 0