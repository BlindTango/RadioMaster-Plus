"""Regression checks across Quill feature UI and persistence boundaries."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import wx

from radiomaster.database.connection import DatabaseManager
from radiomaster.database.repository import PodcastRepository, EpisodeRepository
from radiomaster.services.continue_listening import ContinueListeningService
from radiomaster.services.sources import SourceNode, StationRef
from radiomaster.services.station_api import Station
from radiomaster.services.stats_service import StatsService
from radiomaster.ui.audiobook_panel import AudiobookPanel
from radiomaster.ui.catalog_status_dialog import _next_run
from radiomaster.ui.main_window import MainWindow
from radiomaster.ui.media_player_panel import MediaPlayerPanel
from radiomaster.ui.podcast_panel import PodcastPanel
from radiomaster.ui.radio_panel import RadioPanel
from radiomaster.ui.widgets.station_tree import StationTree


@pytest.fixture
def db(tmp_path):
    manager = DatabaseManager(str(tmp_path))
    manager.initialize()
    yield manager
    manager.close()


@pytest.fixture
def frame():
    app = wx.GetApp() or wx.App(False)
    wx.Log.SetActiveTarget(wx.LogStderr())
    window = wx.Frame(None)
    yield window
    window.Destroy()
    app.ProcessPendingEvents()


def test_archive_search_folders_are_not_dropped():
    panel = SimpleNamespace(tree=Mock())
    source = SimpleNamespace(id="internet_archive", label="Internet Archive")
    RadioPanel._append_source_search_rows(
        panel,
        source,
        [
            SourceNode("Concert", "item:concert", has_children=True),
        ],
    )
    result = panel.tree.append_search_results.call_args.args[0][0]
    assert result.source_path == "item:concert"
    assert result.source_id == "internet_archive"
    assert result.url == ""


def test_archive_track_keeps_finite_playback_flag():
    panel = SimpleNamespace(tree=Mock())
    source = SimpleNamespace(id="internet_archive", label="Internet Archive")
    RadioPanel._append_source_search_rows(
        panel,
        source,
        [
            SourceNode(
                "Track",
                "file:track",
                station=StationRef(
                    "Track", "https://archive/audio.mp3", "internet_archive", is_live=False
                ),
            ),
        ],
    )
    assert panel.tree.append_search_results.call_args.args[0][0].is_live is False


def test_search_merge_preserves_station_identity(frame):
    tree = StationTree(frame, Mock())
    tree.set_search_results([Station("b", "Bravo", "b"), Station("z", "Zulu", "z")])
    tree.station_list.Select(1)
    tree.append_search_results([Station("a", "Alpha", "a")])
    assert tree.get_selected_station().uuid == "z"


def test_late_browse_does_not_replace_search_results(frame):
    tree = StationTree(frame, Mock())
    tree.show_sources([("Archive", "internet_archive")])
    tree.set_search_results([Station("b", "Bravo", "b")])
    tree.set_source_rows("internet_archive", ["Archive data"])
    assert tree.station_list.OnGetItemText(0, 0) == "Bravo"


def test_failed_source_can_be_retried(frame):
    tree = StationTree(frame, Mock())
    tree.show_sources([("Archive", "internet_archive")])
    tree.set_source_failed("internet_archive", "Offline")
    tree.on_source_selected = Mock()
    tree._select_group_index(0)
    tree.on_source_selected.assert_called_once_with("internet_archive")


def test_stale_search_result_is_discarded():
    panel = SimpleNamespace(_search_seq=2, _append_source_search_rows=Mock())
    RadioPanel._finish_source_search(panel, "old", 1, Mock(), [], "")
    panel._append_source_search_rows.assert_not_called()


def test_podcast_folder_opens_and_returns_to_subscriptions(frame, db):
    repo = PodcastRepository(db)
    folder = repo.create_folder("Tech")
    show = repo.add("https://feed", title="A show")
    repo.move_to_folder(show, folder)
    panel = PodcastPanel(frame, db, Mock())
    panel._set_status = Mock()
    index = panel._category_list.FindItem(-1, "Subscriptions")
    panel._category_list.Select(index)
    panel._on_category_select(wx.CommandEvent())
    assert panel._podcast_data == [{"_folder": repo.get_folders()[0]}]
    panel._podcast_list.Select(0)
    panel._on_podcast_activated(wx.CommandEvent())
    assert panel._podcast_data[1]["id"] == show
    panel._podcast_list.Select(0)
    panel._on_podcast_activated(wx.CommandEvent())
    assert "_folder" in panel._podcast_data[0]
    panel._position_timer.Stop()


def test_unfinished_episode_is_not_marked_played_on_start(frame, db):
    show = PodcastRepository(db).add("https://feed", title="Show")
    db.execute(
        "INSERT INTO episodes (podcast_id,title,audio_url,duration) VALUES (?,?,?,?)",
        (show, "Episode", "https://episode", 600),
    )
    episode = db.fetchone("SELECT * FROM episodes")
    engine = Mock(current_url="https://episode", state="playing", position=90, duration=600)
    panel = PodcastPanel(frame, db, engine)
    panel._episode_data = [episode]
    panel._play_episode_at(0, False)
    panel._save_position()
    assert EpisodeRepository(db).get(episode["id"])["is_played"] == 0
    assert ContinueListeningService(db).items()[0].source_id == episode["id"]
    panel.finish_current_episode()
    assert EpisodeRepository(db).get(episode["id"])["is_played"] == 1
    panel._position_timer.Stop()


def test_local_media_progress_populates_continue_listening(db, tmp_path):
    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"audio")
    playlist = Mock()
    playlist.GetItemText.side_effect = lambda idx, column=0: "Title" if column == 0 else "Artist"
    panel = SimpleNamespace(
        _current_index=0,
        _paths=[str(audio)],
        _playlist=playlist,
        _db=db,
        _engine=SimpleNamespace(current_url=str(audio), state="playing", position=90, duration=300),
    )
    MediaPlayerPanel._save_position(panel)
    assert ContinueListeningService(db).items()[0].file_path == str(audio)


def test_audiobook_does_not_save_another_sources_position(db):
    panel = SimpleNamespace(
        _db=db,
        _playing_book_id=1,
        _playing_url="book.mp3",
        _engine=SimpleNamespace(current_url="radio", state="playing", position=120),
    )
    AudiobookPanel._save_position(panel)
    assert db.fetchall("SELECT * FROM audiobooks") == []


def test_continue_order_uses_listening_activity(db):
    show = PodcastRepository(db).add("https://feed", title="Show")
    for title, created, listened in [
        ("Older", "2020-01-01", "2026-10-10"),
        ("Newer", "2025-01-01", "2026-10-09"),
    ]:
        db.execute(
            "INSERT INTO episodes (podcast_id,title,play_position,created_at,last_listened_at) "
            "VALUES (?,?,90,?,?)",
            (show, title, created, listened),
        )
    assert [i.title for i in ContinueListeningService(db).items()] == ["Older", "Newer"]


def test_active_stats_are_visible_and_not_double_counted(db, monkeypatch):
    import radiomaster.services.stats_service as module

    clock = [datetime(2026, 10, 9, 12)]
    monkeypatch.setattr(module, "_now", lambda: clock[0])
    stats = StatsService(db)
    stats.on_state_change("playing", "station", "url", "Station")
    clock[0] += timedelta(seconds=65)
    assert stats.totals().seconds == 65
    assert stats.top_items("station") == [("Station", 65)]
    stats.on_state_change("paused")
    assert stats.totals().seconds == 65


def test_stats_follow_audio_instead_of_selected_tab(db):
    window = SimpleNamespace(
        _engine=SimpleNamespace(current_url="radio", current_title="Station", _is_live=True)
    )
    assert MainWindow._stats_source_context(window) == ("station", "radio", "Station")


@pytest.mark.parametrize(
    "frequency, expected",
    [
        ("quarterly", datetime(2026, 7, 1, 3)),
        ("six_monthly", datetime(2026, 7, 1, 3)),
        ("yearly", datetime(2027, 1, 1, 3)),
    ],
)
def test_catalog_schedule_uses_actual_calendar_boundaries(frequency, expected):
    assert _next_run(frequency, None, datetime(2026, 5, 12)) == expected


def test_old_station_config_retains_live_default():
    assert Station.from_dict({"uuid": "old", "name": "Station", "url": "live"}).is_live is True
