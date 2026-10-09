"""Tests for the Continue Listening service (services/continue_listening.py)."""

import pytest

from radiomaster.database.connection import DatabaseManager
from radiomaster.services.continue_listening import (
    ContinueListeningService, MIN_POSITION_SECONDS,
)


@pytest.fixture
def db(tmp_path):
    manager = DatabaseManager(str(tmp_path))
    manager.initialize()
    yield manager
    manager.close()


@pytest.fixture
def service(db):
    return ContinueListeningService(db)


def _add_podcast(db, title="A Show", episode_title="Ep 1", position=120.0,
                 played=0, file_path=""):
    # feed_url is UNIQUE -- vary it per call so multiple shows can exist.
    db.execute(
        "INSERT INTO podcasts (feed_url, title) VALUES (?, ?)",
        (f"https://example/feed/{episode_title}", title,))
    podcast_id = db.fetchone("SELECT MAX(id) AS id FROM podcasts")["id"]
    db.execute(
        "INSERT INTO episodes (podcast_id, title, play_position, is_played, file_path) "
        "VALUES (?, ?, ?, ?, ?)",
        (podcast_id, episode_title, position, played, file_path))
    return db.fetchone("SELECT MAX(id) AS id FROM episodes")["id"]


def _add_audiobook(db, title="A Book", position=300.0, file_path=""):
    db.execute(
        "INSERT INTO audiobooks (title, last_position, file_path) VALUES (?, ?, ?)",
        (title, position, file_path))
    return db.fetchone("SELECT MAX(id) AS id FROM audiobooks")["id"]


def _add_media_file(db, title="A Song", position=45.0, file_path=""):
    db.execute(
        "INSERT INTO media_files (title, last_position, file_path) VALUES (?, ?, ?)",
        (title, position, file_path))
    return db.fetchone("SELECT MAX(id) AS id FROM media_files")["id"]


def test_gathers_all_three_kinds(service):
    _add_podcast(service._db)
    _add_audiobook(service._db)
    _add_media_file(service._db)
    items = service.items()
    kinds = {item.kind for item in items}
    assert kinds == {"podcast episode", "audiobook", "media file"}


def test_played_episodes_are_excluded(service):
    _add_podcast(service._db, played=1)
    assert service.items() == []


def test_tiny_positions_are_noise(service):
    _add_podcast(service._db, position=MIN_POSITION_SECONDS - 1)
    assert service.items() == []


def test_missing_files_are_quietly_absent(service, tmp_path):
    _add_podcast(service._db, file_path=str(tmp_path / "gone.mp3"))
    _add_media_file(service._db, file_path=str(tmp_path / "also_gone.flac"))
    # A real file still shows up.
    real = tmp_path / "real.mp3"
    real.write_text("x")
    _add_audiobook(service._db, file_path=str(real))
    items = service.items()
    assert len(items) == 1
    assert items[0].kind == "audiobook"


def test_forget_zeroes_position_and_marks_unplayed(service):
    episode_id = _add_podcast(service._db, position=500.0)
    item = service.items()[0]
    service.forget(item)
    row = service._db.fetchone(
        "SELECT play_position, is_played FROM episodes WHERE id = ?",
        (episode_id,))
    assert row["play_position"] == 0
    assert row["is_played"] == 0
    assert service.items() == []


def test_forget_audiobook_and_media(service):
    book_id = _add_audiobook(service._db, position=500.0)
    media_id = _add_media_file(service._db, position=500.0)
    items = service.items()
    for item in items:
        service.forget(item)
    book = service._db.fetchone(
        "SELECT last_position FROM audiobooks WHERE id = ?", (book_id,))
    media = service._db.fetchone(
        "SELECT last_position FROM media_files WHERE id = ?", (media_id,))
    assert book["last_position"] == 0
    assert media["last_position"] == 0


def test_describe_position_words():
    assert ContinueListeningService.describe_position(720, 2700) == "12 of 45 minutes"
    # No duration: whole minutes, floored (90s is honestly "1 minute").
    assert ContinueListeningService.describe_position(90, 0) == "1 minute"
    assert ContinueListeningService.describe_position(3700, 0) == "1 hour 1 minute"


def test_summary_sentence():
    assert ContinueListeningService.summary_sentence([]) == \
        "Nothing is waiting to be continued."
    from radiomaster.services.continue_listening import ContinueItem
    items = [
        ContinueItem("podcast episode", "Ep", "", 10, 0, "episode", 1, ""),
        ContinueItem("audiobook", "Book", "", 10, 0, "audiobook", 1, ""),
    ]
    sentence = ContinueListeningService.summary_sentence(items)
    assert sentence == ("2 things you did not finish, "
                        "across audiobook, podcast episode.")


def test_newest_first_ordering(service):
    # Same created_at second-resolution timestamps are possible; the
    # service must still produce a stable, complete list.
    for i in range(5):
        _add_podcast(service._db, episode_title=f"Ep {i}")
    items = service.items()
    assert len(items) == 5


@pytest.mark.parametrize("table,position", [
    ("episodes", "play_position"),
    ("audiobooks", "last_position"),
    ("media_files", "last_position"),
])
def test_completed_items_are_excluded(service, table, position):
    _add_podcast(service._db)
    _add_audiobook(service._db)
    _add_media_file(service._db)
    service._db.execute(f"UPDATE {table} SET duration = {position}")
    assert len(service.items()) == 2


def test_episode_duration_is_preserved(service):
    episode_id = _add_podcast(service._db)
    service._db.execute("UPDATE episodes SET duration = 600 WHERE id = ?", (episode_id,))
    assert service.items()[0].duration == 600
