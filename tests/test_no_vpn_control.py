"""RadioMaster+ does not drive a VPN. Reconnecting the last station at start-up used to wait
for one and freeze the program, so nothing may sit between choosing a station and playing it."""

import importlib.util
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from radiomaster.engine.playback_engine import PlaybackEngine
from radiomaster.services.station_api import Station


@pytest.mark.parametrize("module", [
    "radiomaster.services.routing", "radiomaster.services.vpn_verify",
    "radiomaster.services.vpn_regions", "radiomaster.ui.routing_dialog"])
def test_the_vpn_modules_are_gone(module):
    assert importlib.util.find_spec(module) is None


def test_the_player_has_no_vpn_hooks():
    assert not hasattr(PlaybackEngine, "on_region_blocked")
    assert not hasattr(PlaybackEngine, "on_open_failed")


def test_choosing_a_station_starts_the_player_directly(monkeypatch):
    from radiomaster.ui.radio_panel import RadioPanel

    started = []
    monkeypatch.setattr("radiomaster.ui.radio_panel.threading.Thread",
                        lambda target=None, args=(), kwargs=None, **kw:
                        SimpleNamespace(start=lambda: started.append((target, args, kwargs or {}))))
    engine = MagicMock()
    config = SimpleNamespace(get=lambda key, default=None: 0, set=lambda *a, **k: None, save=lambda: None)
    monkeypatch.setattr("radiomaster.utils.config.ConfigManager.get_instance", staticmethod(lambda: config))
    panel = SimpleNamespace(
        engine=engine, _playing_station=None, _push_history=lambda s: None,
        now_playing=MagicMock(), set_status=lambda text: None, station_api=MagicMock(),
        _now_playing_generation=0, _poll_now_playing=lambda *a: None,
        _probe_and_report_format=lambda *a: None, on_format_detected=None,
        _reported_stream_format="", _source_browse_path={}, tree=MagicMock())
    station = Station("u", "BBC Radio 5 Live", "https://bbc.test/live.m3u8",
                      country="United Kingdom Of Great Britain And Northern Ireland")
    RadioPanel._play_station(panel, station)
    targets = [target for target, _args, _kwargs in started]
    assert engine.play in targets                             # the player is started straight away
    play_args = next(args for target, args, _kw in started if target == engine.play)
    assert play_args == (station.url,)


def test_the_network_settings_page_has_no_vpn_controls():
    import inspect
    from radiomaster.ui import settings_dialog
    source = inspect.getsource(settings_dialog.NetworkPanel)
    assert "routing" not in source.lower() and "vpn" not in source.lower()


def test_routing_settings_saved_by_older_versions_are_dropped(tmp_path):
    import json
    from radiomaster.utils.config import ConfigManager
    saved = {"general": {"language": "en"}, "network": {"timeout": 12},
             "routing": {"enabled": True, "mode": "always",
                         "routes": [{"country": "UK", "method": "expressvpn", "target": "uk-london"}]}}
    (tmp_path / "settings.json").write_text(json.dumps(saved), encoding="utf-8")
    config = ConfigManager(str(tmp_path))
    assert config.get("routing") is None and config.get("routing", "enabled") is None
    assert config.get("network", "timeout") == 12                # everything else is untouched
    config.save()
    on_disk = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert "routing" not in on_disk and on_disk["network"]["timeout"] == 12


def test_no_record_is_kept_of_which_stations_need_a_vpn(tmp_path):
    from radiomaster.services.station_db import StationDB
    db = StationDB(str(tmp_path / "s.db"))
    assert not hasattr(db, "vpn_required_uuids") and not hasattr(db, "mark_vpn_required")
    with db._connect() as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "station_vpn" not in tables


def test_the_old_vpn_table_is_dropped_from_an_existing_database(tmp_path):
    import sqlite3
    from radiomaster.services.station_db import StationDB
    path = str(tmp_path / "old.db")
    StationDB(path)                                           # a normal database
    with sqlite3.connect(path) as conn:                       # as versions 1.4.0 to 1.4.2 left it
        conn.execute("CREATE TABLE station_vpn (uuid TEXT PRIMARY KEY, country TEXT, verified INTEGER, checked_at TEXT)")
        conn.execute("INSERT INTO station_vpn VALUES ('a', 'UK', 1, '2026-11-22')")
    StationDB(path)                                           # opening it cleans it
    with sqlite3.connect(path) as conn:
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "station_vpn" not in names and "stations" in names  # nothing else is touched
