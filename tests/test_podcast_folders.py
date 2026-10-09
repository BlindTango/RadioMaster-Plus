"""Tests for podcast folders, unheard badges, and per-show speed."""

import pytest

from radiomaster.database.connection import DatabaseManager
from radiomaster.database.repository import EpisodeRepository, PodcastRepository


@pytest.fixture
def db(tmp_path):
    manager = DatabaseManager(str(tmp_path))
    manager.initialize()
    yield manager
    manager.close()


@pytest.fixture
def podcasts(db):
    return PodcastRepository(db)


@pytest.fixture
def episodes(db):
    return EpisodeRepository(db)


def _subscribe(podcasts, title="A Show", feed="https://example/feed"):
    return podcasts.add(feed, title)


def _add_episode(db, podcast_id, played=0):
    db.execute(
        "INSERT INTO episodes (podcast_id, title, is_played) VALUES (?, ?, ?)",
        (podcast_id, "Ep", played))
    return db.fetchone("SELECT MAX(id) AS id FROM episodes")["id"]


# ---------------------------------------------------------------- folders


def test_create_and_list_folders(podcasts):
    podcasts.create_folder("Tech")
    podcasts.create_folder("News")
    names = [f["name"] for f in podcasts.get_folders()]
    assert names == ["News", "Tech"]  # alphabetical


def test_duplicate_folder_name_is_refused(podcasts):
    podcasts.create_folder("Tech")
    with pytest.raises(Exception):
        podcasts.create_folder("Tech")


def test_move_to_folder_and_back(podcasts):
    show_id = _subscribe(podcasts)
    folder_id = podcasts.create_folder("Tech")
    podcasts.move_to_folder(show_id, folder_id)
    row = podcasts.get_all()[0]
    assert row["folder_id"] == folder_id
    podcasts.move_to_folder(show_id, None)
    assert podcasts.get_all()[0]["folder_id"] is None


def test_delete_folder_moves_children_to_root(podcasts):
    show_id = _subscribe(podcasts)
    folder_id = podcasts.create_folder("Tech")
    podcasts.move_to_folder(show_id, folder_id)
    moved = podcasts.delete_folder(folder_id)
    assert moved == 1
    assert podcasts.get_folders() == []
    assert podcasts.get_all()[0]["folder_id"] is None


def test_rename_folder(podcasts):
    folder_id = podcasts.create_folder("Tech")
    podcasts.rename_folder(folder_id, "Technology")
    assert podcasts.get_folders()[0]["name"] == "Technology"


# ---------------------------------------------------------------- badges


def test_unheard_count(podcasts, episodes, db):
    show_id = _subscribe(podcasts)
    _add_episode(db, show_id, played=0)
    _add_episode(db, show_id, played=0)
    _add_episode(db, show_id, played=1)
    assert episodes.unheard_count(show_id) == 2


def test_unheard_count_zero_when_all_played(podcasts, episodes, db):
    show_id = _subscribe(podcasts)
    _add_episode(db, show_id, played=1)
    assert episodes.unheard_count(show_id) == 0


def test_mark_all_played_returns_count(podcasts, episodes, db):
    show_id = _subscribe(podcasts)
    _add_episode(db, show_id, played=0)
    _add_episode(db, show_id, played=0)
    _add_episode(db, show_id, played=1)
    count = episodes.mark_all_played(show_id)
    assert count == 2
    assert episodes.unheard_count(show_id) == 0


def test_mark_all_played_on_empty_show(podcasts, episodes, db):
    show_id = _subscribe(podcasts)
    assert episodes.mark_all_played(show_id) == 0


# ---------------------------------------------------------------- per-show speed


def test_playback_rate_round_trip(podcasts):
    show_id = _subscribe(podcasts)
    assert podcasts.get_playback_rate(show_id) == 1.0  # default
    podcasts.set_playback_rate(show_id, 1.5)
    assert podcasts.get_playback_rate(show_id) == 1.5


def test_playback_rate_is_clamped(podcasts):
    show_id = _subscribe(podcasts)
    podcasts.set_playback_rate(show_id, 9.9)
    assert podcasts.get_playback_rate(show_id) == 3.0
    podcasts.set_playback_rate(show_id, 0.1)
    assert podcasts.get_playback_rate(show_id) == 0.5