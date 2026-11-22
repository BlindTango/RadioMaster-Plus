"""Stations that need a VPN are recorded, checked through the VPN, and labelled."""

import threading
from types import SimpleNamespace

import pytest

from radiomaster.services import vpn_verify
from radiomaster.services.region_block import region_block_status
from radiomaster.services.routing import RouteError, RoutingManager
from radiomaster.services.station_api import Station
from radiomaster.services.station_db import StationDB
from radiomaster.services.vpn_verify import verify_vpn_stations

UK = "United Kingdom Of Great Britain And Northern Ireland"


@pytest.fixture
def db(tmp_path):
    database = StationDB(str(tmp_path / "s.db"))
    database.upsert_stations([
        Station("a", "BBC Five", "http://s/a", country=UK),
        Station("b", "BBC Two", "http://s/b", country=UK),
        Station("c", "Radio France", "http://s/c", country="France"),
        Station("d", "Open Station", "http://s/d", country=UK)])
    return database


def row(uuid, blocked):
    return {"uuid": uuid, "stream_ok": not blocked, "geo_blocked": blocked,
            "status": "blocked" if blocked else "alive"}


def test_health_check_records_blocked_stations_and_clears_ones_that_play(db):
    db.record_health_results([row("a", True), row("b", True), row("d", False)])
    assert db.vpn_required_uuids() == {"a", "b"}
    entry = {r["uuid"]: r for r in db.vpn_required()}
    assert entry["a"]["country"] == UK and entry["a"]["name"] == "BBC Five"
    db.record_health_results([row("b", False)])             # plays now: no longer needs one
    assert db.vpn_required_uuids() == {"a"}


def test_a_station_confirmed_through_a_vpn_stays_listed_when_the_scan_runs_without_it(db):
    db.record_health_results([row("a", True)])
    db.set_vpn_verified("a", True)
    db.record_health_results([row("a", True)])               # still blocked: stays confirmed
    assert {r["uuid"]: r["verified"] for r in db.vpn_required()} == {"a": 1}
    db.record_health_results([row("a", False)])              # confirmed ones are kept until re-verified
    assert db.vpn_required_uuids() == {"a"}


def test_results_recorded_before_the_list_existed_are_picked_up(db, tmp_path):
    with db._connect() as conn:
        conn.execute("DELETE FROM station_vpn")
        conn.execute(
            "INSERT INTO station_health (uuid, checked_at, geo_blocked, status) "
            "VALUES ('c', '2026-01-01', 1, 'blocked')")
    assert StationDB(str(tmp_path / "s.db")).vpn_required_uuids() == {"c"}


# --- verification ----------------------------------------------------------------

class FakeManager:
    def __init__(self, routes=("United Kingdom Of Great Britain And Northern Ireland",), fail=()):
        self.routes, self.fail = set(routes), set(fail)
        self.prepared, self.released = [], 0
        self.servers, self.index = ["server-1"], 0

    @property
    def server(self):
        return self.servers[self.index]

    def advance(self):
        if self.index + 1 >= len(self.servers):
            return None
        self.index += 1
        return self.servers[self.index]

    def route_for(self, country):
        return object() if country in self.routes else None

    def prepare(self, country):
        if country in self.fail:
            raise RouteError("VPN is off")
        self.prepared.append(country)

    def release(self):
        self.released += 1


def test_blocked_stations_that_play_through_the_vpn_are_confirmed(db, monkeypatch):
    db.record_health_results([row("a", True), row("b", True), row("c", True)])
    monkeypatch.setattr(vpn_verify, "_plays", lambda url: url.endswith("/a"))
    manager = FakeManager()
    result = verify_vpn_stations(db, manager)
    assert (result.confirmed, result.still_failing) == (1, 1)
    assert result.skipped_countries == ["France"]            # no route set for it
    assert manager.prepared == [UK] and manager.released == 1
    # "a" plays through the VPN: confirmed. "b" refused us and is silent from inside
    # the country too, so it is dead, not region-blocked. "c" had no route: unchanged.
    assert {r["uuid"]: r["verified"] for r in db.vpn_required()} == {"a": 1, "c": 0}
    assert db.vpn_required_uuids(confirmed_only=True) == {"a"}
    dead = {r["uuid"]: r for r in db.health_results(problems_only=False)}["b"]
    assert dead["status"] == "dead" and not dead["geo_blocked"] and not dead["stream_ok"]
    assert "did not play even through the VPN" in result.summary() and "France" in result.summary()


def test_the_vpn_is_put_back_even_when_a_route_fails_or_it_is_stopped(db, monkeypatch):
    db.record_health_results([row("a", True), row("c", True)])
    monkeypatch.setattr(vpn_verify, "_plays", lambda url: True)
    manager = FakeManager(routes=(UK, "France"), fail=(UK,))
    result = verify_vpn_stations(db, manager)
    assert result.errors == [f"{UK}: VPN is off"] and result.confirmed == 1
    assert manager.released == 1
    cancel = threading.Event()
    cancel.set()
    manager = FakeManager()
    assert verify_vpn_stations(db, manager, cancel=cancel).cancelled
    assert manager.released == 1


# --- the station list ----------------------------------------------------------------

def test_station_list_labels_stations_that_need_a_vpn():
    from radiomaster.ui.widgets.station_tree import _VirtualStationList
    stations = [Station("a", "BBC Five", "http://s/a"), Station("d", "Open Station", "http://s/d")]
    fake = SimpleNamespace(source_rows=[], stations=stations, vpn_uuids={"a"})
    text = lambda i, col=0: _VirtualStationList.OnGetItemText(fake, i, col)
    assert text(0) == "BBC Five (requires VPN)" and text(1) == "Open Station"
    assert stations[0].name == "BBC Five"                    # type-ahead still uses the plain name


# --- HLS blocks hide one level down ---------------------------------------------------

def test_hls_playlist_that_points_at_a_refused_playlist_is_a_region_block(monkeypatch):
    import http.server

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            if self.path == "/master.m3u8":
                body, code = (b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\n/uk/media.m3u8\n"), 200
            elif self.path == "/open.m3u8":
                body, code = (b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\n/ok/media.m3u8\n"), 200
            elif self.path == "/ok/media.m3u8":
                body, code = b"#EXTM3U\n#EXTINF:6,\nseg1.aac\n", 200
            elif self.path == "/ok/seg1.aac":
                body, code = b"\xff\xf1audio", 200
            else:
                body, code = b"Access Denied", 403
            self.send_response(code)
            kind = ("audio/aac" if self.path.endswith(".aac") else "application/x-mpegurl") \
                if code == 200 else "text/html"
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        assert region_block_status(base + "/master.m3u8") == 403
        assert region_block_status(base + "/open.m3u8") is None
    finally:
        server.shutdown()


# --- custom stations ------------------------------------------------------------------

def test_custom_station_keeps_its_country_and_can_be_marked_as_needing_a_vpn(db):
    station = db.add_custom("BBC Sports Extra", "https://bbc.test/live.m3u8", UK)
    assert station.country == UK
    assert [(s.name, s.country) for s in db.get_custom_stations()] == [("BBC Sports Extra", UK)]
    db.mark_vpn_required(station.uuid, UK, verified=True)
    assert station.uuid in db.vpn_required_uuids(confirmed_only=True)
    entry = {r["uuid"]: r for r in db.vpn_required()}[station.uuid]
    assert entry["name"] == "BBC Sports Extra" and entry["url"] == "https://bbc.test/live.m3u8"


def test_custom_station_without_a_country_still_works(db):
    assert db.add_custom("Mine", "http://x/live").country == ""
    assert db.get_custom_stations()[0].country == ""


def test_an_older_database_gains_the_custom_country_column(tmp_path):
    import sqlite3
    path = str(tmp_path / "old.db")
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE custom_stations (uuid TEXT PRIMARY KEY, name TEXT NOT NULL, "
                     "url TEXT NOT NULL, created_at TEXT)")
        conn.execute("INSERT INTO custom_stations VALUES ('custom-1', 'Old', 'http://old', '')")
    old = StationDB(path)
    assert [(s.name, s.country) for s in old.get_custom_stations()] == [("Old", "")]


def test_verification_keeps_a_custom_station_that_is_off_the_air(db, monkeypatch):
    station = db.add_custom("Sports Extra", "http://s/x", UK)
    db.mark_vpn_required(station.uuid, UK, verified=True)
    monkeypatch.setattr(vpn_verify, "_plays", lambda url: False)
    result = verify_vpn_stations(db, FakeManager())
    assert result.custom_unconfirmed == 1 and result.still_failing == 0
    assert station.uuid in db.vpn_required_uuids(confirmed_only=True)
    assert "may be off the air" in result.summary()


def test_a_station_that_only_plays_through_the_second_server_is_confirmed_not_dead(db, monkeypatch):
    db.record_health_results([row("a", True), row("b", True)])
    manager = FakeManager()
    manager.servers = ["uk-london", "uk-manchester"]
    # "a" plays through either server; "b" is only reachable through the second one
    monkeypatch.setattr(vpn_verify, "_plays",
                        lambda url: url.endswith("/a") or manager.server == "uk-manchester")
    result = verify_vpn_stations(db, manager)
    assert (result.confirmed, result.still_failing) == (2, 0)
    assert db.vpn_required_uuids(confirmed_only=True) == {"a", "b"}


def test_a_station_that_fails_through_every_server_is_dead(db, monkeypatch):
    db.record_health_results([row("b", True)])
    manager = FakeManager()
    manager.servers = ["uk-london", "uk-manchester", "uk-docklands"]
    seen = []
    monkeypatch.setattr(vpn_verify, "_plays", lambda url: seen.append(manager.server) or False)
    result = verify_vpn_stations(db, manager)
    assert result.still_failing == 1 and seen == manager.servers
    assert db.vpn_required_uuids() == set()
