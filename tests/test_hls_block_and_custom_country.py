"""HLS streams blocked behind an open playlist, and the optional country of a custom station."""

import threading

import pytest

from radiomaster.services.region_block import region_block_status
from radiomaster.services.station_api import Station
from radiomaster.services.station_db import StationDB

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

def test_custom_station_keeps_its_country(db):
    station = db.add_custom("BBC Sports Extra", "https://bbc.test/live.m3u8", UK)
    assert station.country == UK
    assert [(s.name, s.country) for s in db.get_custom_stations()] == [("BBC Sports Extra", UK)]


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


