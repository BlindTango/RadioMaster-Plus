"""Regression coverage for importing podcast subscriptions and episodes."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from radiomaster.database.connection import DatabaseManager
from radiomaster.database.repository import PodcastRepository
from radiomaster.services.podcast_manager import PodcastManager


@pytest.fixture
def db(tmp_path):
    manager = DatabaseManager(str(tmp_path))
    manager.initialize()
    yield manager
    manager.close()


def test_import_loads_all_feeds_and_preserves_progress_on_retry(db, monkeypatch):
    feeds = PodcastManager.parse_opml('''<opml><body><outline text="Folder">
      <outline title="One" xmlUrl="https://one/feed"/>
      <outline text="Two" xmlUrl="https://two/feed"/>
      <outline text="Duplicate" xmlUrl="https://one/feed"/>
    </outline></body></opml>''')
    episodes = [
        {"guid": "shared", "title": "First", "audio_url": "https://audio/1"},
        {"title": "Second", "audio_url": "https://audio/2"},
        {"title": "Third", "audio_url": "https://audio/3"},
    ]
    parse = MagicMock(return_value={"episodes": episodes})
    monkeypatch.setattr(PodcastManager, "parse_feed", parse)
    result = PodcastManager.import_subscriptions(db, feeds)
    assert result["imported"] == result["refreshed"] == 2
    assert result["failed"] == []
    assert parse.call_count == 2
    repo = PodcastRepository(db)
    podcasts = repo.get_all()
    assert [p["title"] for p in podcasts] == ["One", "Two"]
    assert all(len(repo.get_episodes(p["id"])) == 3 for p in podcasts)
    ep = repo.get_episodes(podcasts[0]["id"])[0]
    db.execute("UPDATE episodes SET play_position = 123, is_played = 1 WHERE id = ?", (ep["id"],))
    db.commit()
    result = PodcastManager.import_subscriptions(db, feeds)
    assert result["imported"] == 0
    assert repo.get_all() == podcasts
    assert len(db.fetchall("SELECT * FROM episodes")) == 6
    saved = db.fetchone("SELECT * FROM episodes WHERE id = ?", (ep["id"],))
    assert saved["play_position"] == 123
    assert saved["is_played"] == 1


def test_existing_empty_subscription_is_repaired_and_failures_can_retry(db, monkeypatch):
    repo = PodcastRepository(db)
    podcast_id = repo.add("https://old/feed", title="Existing")
    feeds = [{"feed_url": "https://old/feed"}, {"feed_url": "https://new/feed"}]
    monkeypatch.setattr(PodcastManager, "parse_feed", lambda url: None if "old" in url else {
        "episodes": [{"guid": "episode", "title": "Episode"}]
    })
    result = PodcastManager.import_subscriptions(db, feeds)
    assert result["failed"] == ["https://old/feed"]
    assert result["refreshed"] == 1
    assert len(repo.get_all()) == 2
    monkeypatch.setattr(PodcastManager, "parse_feed", lambda url: {"episodes": [{"guid": "episode"}]})
    result = PodcastManager.import_subscriptions(db, feeds)
    assert result["failed"] == []
    assert len(repo.get_episodes(podcast_id)) == 1
    assert repo.get_by_feed_url("https://old/feed")["id"] == podcast_id


def panel_method(name):
    source = Path("src/radiomaster/ui/podcast_panel.py").read_text(encoding="utf-8")
    cls = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef))
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
    namespace = {}
    exec(compile(ast.Module(body=[method], type_ignores=[]), "podcast_panel.py", "exec"), namespace)
    return namespace[name]


@pytest.mark.parametrize("search,selected,subscribe,unsubscribe", [
    (False, 0, False, True), (True, 0, True, False),
    (False, -1, False, False), (True, -1, False, False),
])
def test_subscription_buttons_match_selection(search, selected, subscribe, unsubscribe):
    panel = SimpleNamespace(
        _podcast_list=MagicMock(), _podcast_data=[{"id": 1}],
        _viewing_search_results=search, _btn_subscribe=MagicMock(),
        _btn_unsubscribe=MagicMock(),
    )
    panel._podcast_list.GetFirstSelected.return_value = selected
    panel_method("_update_subscription_buttons")(panel)
    panel._btn_subscribe.Enable.assert_called_once_with(subscribe)
    panel._btn_unsubscribe.Enable.assert_called_once_with(unsubscribe)
