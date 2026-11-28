"""Filling in a recording schedule's address from what is playing, a station or an episode."""

import gc
from types import SimpleNamespace

import pytest
import wx

from radiomaster.database.connection import DatabaseManager
from radiomaster.services.schedule_sources import (
    SOURCE_AUDIOBOOK, SOURCE_PODCAST, SOURCE_STATION, ScheduleSources, SourcePick,
    pick_from_episode, pick_from_now_playing, pick_from_station)
from radiomaster.services.station_api import Station
from radiomaster.services.station_db import StationDB


# --- turning things into a pick -----------------------------------------------------------

def test_a_station_becomes_a_radio_pick():
    pick = pick_from_station(Station("u", "BBC Radio 2", "https://bbc.test/live.m3u8"))
    assert pick == SourcePick("https://bbc.test/live.m3u8", "BBC Radio 2", SOURCE_STATION)


def test_a_station_without_an_online_address_gives_no_pick():
    assert pick_from_station(Station("u", "Local", "C:/music/a.mp3")) is None
    assert pick_from_station(Station("u", "Empty", "")) is None


def test_an_episode_becomes_a_podcast_pick_named_after_its_show():
    pick = pick_from_episode({"title": "Double Tap"}, {"title": "Ep 42", "audio_url": "https://pod.test/42.mp3"})
    assert pick == SourcePick("https://pod.test/42.mp3", "Double Tap: Ep 42", SOURCE_PODCAST)
    assert pick_from_episode({"title": "S"}, {"title": "x", "audio_url": ""}) is None


@pytest.mark.parametrize("kind,expected", [("station", SOURCE_STATION), ("podcast", SOURCE_PODCAST),
                                           ("audiobook", SOURCE_AUDIOBOOK), ("media", SOURCE_STATION)])
def test_now_playing_maps_what_is_playing_to_a_source_type(kind, expected):
    pick, why = pick_from_now_playing("https://x.test/a", "Title", kind)
    assert pick.source_type == expected and pick.url == "https://x.test/a" and why == ""


def test_now_playing_names_a_podcast_episode_after_its_show_once():
    pick, _ = pick_from_now_playing("https://x.test/a.mp3", "Ep 1", "podcast", show_title="The Show")
    assert pick.title == "The Show: Ep 1"
    pick, _ = pick_from_now_playing("https://x.test/a.mp3", "The Show - Ep 1", "podcast", show_title="The Show")
    assert pick.title == "The Show - Ep 1"                      # already named, not doubled


@pytest.mark.parametrize("url,video,needle", [
    ("", False, "Nothing is loaded"),
    ("https://x.test/v", True, "video cannot be recorded"),
    ("C:/music/song.mp3", False, "file on this computer"),
])
def test_now_playing_explains_why_it_cannot_be_scheduled(url, video, needle):
    pick, why = pick_from_now_playing(url, "T", "media", is_video=video)
    assert pick is None and needle in why


# --- the lists the pickers use --------------------------------------------------------------

@pytest.fixture
def stations(tmp_path):
    db = StationDB(str(tmp_path / "s.db"))
    db.upsert_stations([Station("1", "BBC Radio 2", "https://bbc.test/2", country="UK", bitrate=128),
                        Station("2", "BBC Radio 4", "https://bbc.test/4", country="UK"),
                        Station("3", "Jazz FM", "https://jazz.test/live", country="UK")])
    custom = db.add_custom("My Stream", "https://mine.test/live")
    db.add_favorite(Station("2", "BBC Radio 4", "https://bbc.test/4", country="UK"))
    db.add_favorite(Station("9", "Offline Favorite", "not-a-url"))
    return db, custom


def sources_for(db):
    return ScheduleSources(db, None, lambda: (None, "nothing"))


def test_with_nothing_typed_favorites_and_custom_stations_are_listed(stations):
    db, _ = stations
    names = [s.name for s in sources_for(db).stations("")]
    assert names == ["BBC Radio 4", "My Stream"]                # online favorites first, then custom


def test_searching_finds_catalog_stations_without_repeating_favorites(stations):
    db, _ = stations
    names = [s.name for s in sources_for(db).stations("bbc")]
    assert names == ["BBC Radio 4", "BBC Radio 2"] and len(set(names)) == 2   # the favorite leads, once
    assert [s.name for s in sources_for(db).stations("jazz")] == ["Jazz FM"]
    assert sources_for(db).stations("nothing like this") == []


def test_search_text_also_narrows_favorites_and_custom_stations(stations):
    db, _ = stations
    assert [s.name for s in sources_for(db).stations("my str")] == ["My Stream"]


def test_now_playing_failures_are_reported_not_raised():
    def broken():
        raise RuntimeError("engine gone")
    pick, why = ScheduleSources(None, None, broken).now_playing()
    assert pick is None and "Could not tell" in why


@pytest.fixture
def podcasts(tmp_path):
    db = DatabaseManager(str(tmp_path))
    db.initialize()
    db.execute("INSERT INTO podcasts (feed_url, title) VALUES ('https://f/1', 'Show One')")
    show = db.fetchone("SELECT id FROM podcasts")["id"]
    for n, url in ((1, "https://pod.test/1.mp3"), (2, ""), (3, "https://pod.test/3.mp3")):
        db.execute("INSERT INTO episodes (podcast_id, title, audio_url, published_date) VALUES (?, ?, ?, ?)",
                   (show, f"Episode {n}", url, f"2026-11-0{n}"))
    db.commit()
    yield db, show
    db.close()


def test_subscribed_shows_and_their_playable_episodes_are_listed(podcasts):
    db, show = podcasts
    sources = ScheduleSources(None, db, lambda: (None, ""))
    assert [s["title"] for s in sources.podcast_shows()] == ["Show One"]
    assert [e["title"] for e in sources.episodes(show)] == ["Episode 3", "Episode 1"]   # newest first, no empty address


# --- the dialogs ---------------------------------------------------------------------------------

@pytest.fixture
def app():
    gc.collect()
    application = wx.App(False)
    yield application
    wx.Yield()


def schedule_dialog(sources, data=None, tmp_path=None):
    from radiomaster.ui.schedule_dialog import ScheduleDialog
    return ScheduleDialog(None, SimpleNamespace(), data, sources=sources)


class FakeSources:
    def __init__(self, pick=None, reason="", stations=None):
        self._pick, self._reason, self._stations = pick, reason, stations or []
        self.queries = []

    def now_playing(self):
        return self._pick, self._reason

    def stations(self, query=""):
        self.queries.append(query)
        return list(self._stations)

    def podcast_shows(self):
        return []

    def episodes(self, show_id):
        return []


def patch_repo(monkeypatch):
    monkeypatch.setattr("radiomaster.ui.schedule_dialog.ScheduleRepository", lambda db: SimpleNamespace())


def test_the_pick_buttons_are_disabled_without_sources(app, monkeypatch):
    patch_repo(monkeypatch)
    dialog = schedule_dialog(None)
    assert not any(b.IsEnabled() for b in (dialog._btn_now, dialog._btn_station, dialog._btn_episode))
    dialog.Destroy()


def test_use_now_playing_fills_the_address_title_and_type(app, monkeypatch):
    patch_repo(monkeypatch)
    pick = SourcePick("https://pod.test/42.mp3", "Double Tap: Ep 42", SOURCE_PODCAST)
    dialog = schedule_dialog(FakeSources(pick))
    assert dialog._btn_now.IsEnabled()
    dialog._on_use_now_playing(None)
    assert dialog._url_ctrl.GetValue() == "https://pod.test/42.mp3"
    assert dialog._title_ctrl.GetValue() == "Double Tap: Ep 42"
    assert dialog._type_combo.GetValue() == SOURCE_PODCAST
    dialog.Destroy()


def test_use_now_playing_explains_when_there_is_nothing_to_use(app, monkeypatch):
    patch_repo(monkeypatch)
    shown = []
    monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: shown.append(a[0]))
    dialog = schedule_dialog(FakeSources(None, "Nothing is loaded in the player."))
    dialog._url_ctrl.SetValue("https://typed.test/keep")
    dialog._on_use_now_playing(None)
    assert shown == ["Nothing is loaded in the player."]
    assert dialog._url_ctrl.GetValue() == "https://typed.test/keep"      # nothing was overwritten
    dialog.Destroy()


def test_a_typed_title_is_kept_but_an_auto_filled_one_is_replaced(app, monkeypatch):
    patch_repo(monkeypatch)
    dialog = schedule_dialog(FakeSources())
    dialog._title_ctrl.SetValue("My own name")
    dialog._apply_pick(SourcePick("https://a.test/1", "Station One", SOURCE_STATION))
    assert dialog._title_ctrl.GetValue() == "My own name" and dialog._url_ctrl.GetValue() == "https://a.test/1"
    dialog._title_ctrl.SetValue("")
    dialog._apply_pick(SourcePick("https://a.test/1", "Station One", SOURCE_STATION))
    dialog._apply_pick(SourcePick("https://a.test/2", "Station Two", SOURCE_STATION))   # still the auto title
    assert dialog._title_ctrl.GetValue() == "Station Two"
    dialog.Destroy()


def test_station_picker_lists_picks_and_reports_no_results(app):
    from radiomaster.ui.source_picker_dialogs import StationPickerDialog
    found = [Station("1", "BBC Radio 2", "https://bbc.test/2", country="UK", bitrate=128),
             Station("2", "Jazz FM", "https://jazz.test/live")]
    sources = FakeSources(stations=found)
    dialog = StationPickerDialog(None, sources)
    assert dialog.results.GetStrings() == ["BBC Radio 2 (UK, 128 kbps)", "Jazz FM"]
    assert dialog.FindWindowById(wx.ID_OK).IsEnabled()
    dialog.results.SetSelection(1)
    dialog._on_ok()
    assert dialog.pick() == SourcePick("https://jazz.test/live", "Jazz FM", SOURCE_STATION)
    sources._stations = []
    dialog.query.SetValue("zzz")
    dialog.search()
    assert sources.queries[-1] == "zzz" and "No stations found" in dialog.status.GetLabel()
    assert not dialog.FindWindowById(wx.ID_OK).IsEnabled()
    dialog.Destroy()


def test_episode_picker_follows_the_chosen_show(app, podcasts):
    from radiomaster.ui.source_picker_dialogs import EpisodePickerDialog
    db, show = podcasts
    dialog = EpisodePickerDialog(None, ScheduleSources(None, db, lambda: (None, "")))
    assert dialog.show_choice.GetStringSelection() == "Show One"
    assert dialog.results.GetStrings() == ["Episode 3 (2026-11-03)", "Episode 1 (2026-11-01)"]
    dialog.results.SetSelection(1)
    dialog._on_ok()
    assert dialog.pick() == SourcePick("https://pod.test/1.mp3", "Show One: Episode 1", SOURCE_PODCAST)
    dialog.Destroy()


def test_episode_picker_says_when_there_are_no_subscriptions(app, tmp_path):
    from radiomaster.ui.source_picker_dialogs import EpisodePickerDialog
    empty = DatabaseManager(str(tmp_path))
    empty.initialize()
    dialog = EpisodePickerDialog(None, ScheduleSources(None, empty, lambda: (None, "")))
    assert "not subscribed" in dialog.status.GetLabel()
    assert not dialog.FindWindowById(wx.ID_OK).IsEnabled()
    dialog.Destroy()
    empty.close()


def test_main_window_describes_what_is_playing_for_the_scheduler():
    from radiomaster.ui.main_window import MainWindow
    engine = SimpleNamespace(current_url="https://bbc.test/live.m3u8", current_title="BBC Radio 2", is_video=False)
    window = SimpleNamespace(_engine=engine, _stats_source_context=lambda: ("station", "https://bbc.test/live.m3u8", "BBC Radio 2"))
    pick, why = MainWindow._schedule_now_playing(window)
    assert pick == SourcePick("https://bbc.test/live.m3u8", "BBC Radio 2", SOURCE_STATION) and why == ""
    engine.current_url = ""
    pick, why = MainWindow._schedule_now_playing(window)
    assert pick is None and "Nothing is loaded" in why
