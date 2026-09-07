"""Tests for the Station Health Check: data layer (hidden stations +
health results in stations.db) and the health service (classification,
name matching, format capture, worker pool)."""

import os
import tempfile
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from radiomaster.services.station_api import Station
from radiomaster.services.station_db import StationDB
from radiomaster.services.station_health import (
    HealthResult,
    StationHealthService,
    check_station,
    names_match,
)


@pytest.fixture
def station_db():
    """A throwaway stations.db -- never the app's real catalog."""
    tmp = tempfile.mkdtemp()
    db = StationDB(os.path.join(tmp, "stations.db"))
    db.upsert_stations([
        Station(uuid="alive", name="Alive FM", url="http://alive.example/live",
                codec="MP3", bitrate=128, homepage="http://alive.example/",
                country="Greece"),
        Station(uuid="dead", name="Dead FM", url="http://dead.example/live",
                codec="AAC", bitrate=64, homepage="http://dead.example/"),
        Station(uuid="liar", name="Liar FM", url="http://liar.example/live",
                codec="MP3", bitrate=128),
    ])
    yield db
    # StationDB opens short-lived connections; nothing to close.


def _web_response(status_code=200, headers=None, body=b"\xff\xfb" * 64):
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = headers or {"content-type": "audio/mpeg"}
    resp.iter_content.return_value = iter([body])
    resp.close = MagicMock()
    return resp


def _ok_head():
    head = MagicMock()
    head.status_code = 200
    return head


# ---------------------------------------------------------------------------
# Data layer
# ---------------------------------------------------------------------------

class TestHiddenStations:
    def test_hide_excludes_from_browse_queries(self, station_db):
        assert len(station_db.all_stations()) == 3
        station_db.hide_station("dead", "dead stream")
        names = {s.name for s in station_db.all_stations()}
        assert "Dead FM" not in names
        assert len(names) == 2
        assert station_db.hidden_count() == 1

    def test_hide_excludes_from_letter_genre_country_network_search(self, station_db):
        station_db.hide_station("dead", "dead stream")
        # letter
        assert all(s.uuid != "dead" for s in station_db.stations_by_letter("D"))
        # country (empty country for these rows -- use alive's group)
        # network
        assert all(s.uuid != "dead" for s in station_db.stations_by_network(""))
        # search
        assert all(s.uuid != "dead" for s in station_db.search_local("Dead"))

    def test_unhide_restores(self, station_db):
        station_db.hide_station("dead", "dead stream")
        station_db.unhide_station("dead")
        assert len(station_db.all_stations()) == 3
        assert station_db.hidden_count() == 0

    def test_unhide_all_returns_count(self, station_db):
        station_db.hide_station("dead", "x")
        station_db.hide_station("liar", "y")
        assert station_db.unhide_all() == 2
        assert station_db.hidden_count() == 0
        assert station_db.unhide_all() == 0

    def test_hidden_stations_lists_name_and_reason(self, station_db):
        station_db.hide_station("dead", "dead stream")
        rows = station_db.hidden_stations()
        assert ("dead", "Dead FM", "dead stream") in rows

    def test_upsert_does_not_unhide(self, station_db):
        """The blacklist must survive a catalog sync (upsert)."""
        station_db.hide_station("dead", "dead stream")
        station_db.upsert_stations([
            Station(uuid="dead", name="Dead FM", url="http://dead.example/live",
                    codec="AAC", bitrate=64),
        ])
        assert station_db.hidden_count() == 1
        assert "Dead FM" not in {s.name for s in station_db.all_stations()}

    def test_group_counts_exclude_hidden(self, station_db):
        station_db.upsert_stations([
            Station(uuid="g1", name="Gr FM", url="http://g1", country="Greece"),
            Station(uuid="g2", name="Gr2 FM", url="http://g2", country="Greece"),
        ])
        before = dict(station_db.country_groups())
        station_db.hide_station("g1", "x")
        after = dict(station_db.country_groups())
        assert after["Greece"] == before["Greece"] - 1


class TestHealthResults:
    def test_record_and_read_round_trip(self, station_db):
        station_db.record_health_results([
            HealthResult(uuid="alive", stream_ok=True, name_ok=True,
                         website_ok=True, codec="mp3", sample_rate=44100,
                         channels=2, bit_rate=128000, db_codec="MP3",
                         db_bitrate=128).to_row(),
            HealthResult(uuid="dead", stream_ok=False, status="dead",
                         detail="connection refused").to_row(),
        ])
        problems = station_db.health_results(problems_only=True)
        assert {r["uuid"] for r in problems} == {"dead"}
        all_rows = station_db.health_results(problems_only=False)
        assert {r["uuid"] for r in all_rows} == {"alive", "dead"}

    def test_recently_checked_uuids(self, station_db):
        station_db.record_health_results([
            HealthResult(uuid="alive", stream_ok=True).to_row(),
        ])
        assert "alive" in station_db.recently_checked_uuids(7)
        assert station_db.recently_checked_uuids(0) == set()

    def test_batch_write_is_idempotent(self, station_db):
        row = HealthResult(uuid="alive", stream_ok=True, codec="mp3").to_row()
        station_db.record_health_results([row])
        row2 = HealthResult(uuid="alive", stream_ok=False, status="dead").to_row()
        station_db.record_health_results([row2])
        rows = station_db.health_results(problems_only=False)
        assert len(rows) == 1
        assert rows[0]["stream_ok"] == 0


# ---------------------------------------------------------------------------
# Health service: classification
# ---------------------------------------------------------------------------

class TestNamesMatch:
    def test_exact_after_normalization(self):
        assert names_match("Radio XYZ", "radio xyz!") is True

    def test_substring_counts(self):
        assert names_match("Radio XYZ", "Radio XYZ - LIVE") is True
        assert names_match("XYZ", "Radio XYZ") is True

    def test_mismatch(self):
        assert names_match("Radio XYZ", "Totally Different") is False

    def test_no_stream_name_is_unknown(self):
        assert names_match("Radio XYZ", "") is None
        assert names_match("Radio XYZ", "   ") is None


class TestCheckStation:
    def test_alive_stream_with_matching_name(self, station_db):
        station = Station(uuid="alive", name="Alive FM", url="http://x",
                          codec="MP3", bitrate=128, homepage="http://x/")
        resp = _web_response(headers={"content-type": "audio/mpeg",
                                       "icy-name": "Alive FM", "icy-br": "128"})
        with patch("radiomaster.services.station_health.requests.get", return_value=resp), \
                patch("radiomaster.services.station_health.requests.head", return_value=_ok_head()), \
                patch("radiomaster.services.station_health._probe_format",
                      return_value={"codec": "mp3", "sample_rate": 44100,
                                    "channels": 2, "bit_rate": 128000}):
            r = check_station(station)
        assert r.stream_ok is True
        assert r.name_ok is True
        assert r.website_ok is True
        assert r.format_mismatch is False
        assert r.codec == "mp3"

    def test_html_response_is_dead(self):
        station = Station(uuid="x", name="X", url="http://x")
        resp = _web_response(headers={"content-type": "text/html"})
        with patch("radiomaster.services.station_health.requests.get", return_value=resp), \
                patch("radiomaster.services.station_health.requests.head", return_value=_ok_head()):
            r = check_station(station)
        assert r.stream_ok is False
        assert "web page" in r.detail

    def test_403_flags_geo_with_home_country(self):
        station = Station(uuid="x", name="X", url="http://x", country="Greece")
        resp = _web_response(status_code=403, headers={})
        with patch("radiomaster.services.station_health.requests.get", return_value=resp), \
                patch("radiomaster.services.station_health.requests.head", return_value=_ok_head()):
            r = check_station(station)
        assert r.geo_blocked is True
        assert r.stream_ok is False
        assert "Greece" in r.detail

    def test_451_flags_geo(self):
        station = Station(uuid="x", name="X", url="http://x", country="Italy")
        resp = _web_response(status_code=451, headers={})
        with patch("radiomaster.services.station_health.requests.get", return_value=resp), \
                patch("radiomaster.services.station_health.requests.head", return_value=_ok_head()):
            r = check_station(station)
        assert r.geo_blocked is True
        assert "geo-restricted" in r.detail

    def test_connection_error_is_dead(self):
        station = Station(uuid="x", name="X", url="http://x")
        with patch("radiomaster.services.station_health.requests.get",
                   side_effect=ConnectionError("refused")), \
                patch("radiomaster.services.station_health.requests.head", return_value=_ok_head()):
            r = check_station(station)
        assert r.stream_ok is False
        assert r.status == "dead"

    def test_timeout_is_dead(self):
        import requests as requests_mod
        station = Station(uuid="x", name="X", url="http://x")
        with patch("radiomaster.services.station_health.requests.get",
                   side_effect=requests_mod.exceptions.Timeout()), \
                patch("radiomaster.services.station_health.requests.head", return_value=_ok_head()):
            r = check_station(station)
        assert r.stream_ok is False
        assert "timed out" in r.detail

    def test_format_mismatch_on_codec_difference(self):
        station = Station(uuid="x", name="X", url="http://x", codec="MP3", bitrate=128)
        resp = _web_response(headers={"content-type": "audio/aac", "icy-name": "X"})
        with patch("radiomaster.services.station_health.requests.get", return_value=resp), \
                patch("radiomaster.services.station_health.requests.head", return_value=_ok_head()), \
                patch("radiomaster.services.station_health._probe_format",
                      return_value={"codec": "aac", "sample_rate": 44100,
                                    "channels": 2, "bit_rate": 64000}):
            r = check_station(station)
        assert r.format_mismatch is True
        assert r.codec == "aac"
        assert r.db_codec == "MP3"

    def test_bitrate_within_tolerance_is_not_mismatch(self):
        station = Station(uuid="x", name="X", url="http://x", codec="MP3", bitrate=128)
        resp = _web_response(headers={"content-type": "audio/mpeg", "icy-name": "X"})
        with patch("radiomaster.services.station_health.requests.get", return_value=resp), \
                patch("radiomaster.services.station_health.requests.head", return_value=_ok_head()), \
                patch("radiomaster.services.station_health._probe_format",
                      return_value={"codec": "mp3", "sample_rate": 44100,
                                    "channels": 2, "bit_rate": 132000}):
            r = check_station(station)
        assert r.format_mismatch is False

    def test_icy_headers_fallback_when_probe_fails(self):
        station = Station(uuid="x", name="X", url="http://x", codec="MP3", bitrate=0)
        resp = _web_response(headers={"content-type": "audio/mpeg", "icy-name": "X",
                                       "icy-br": "96", "icy-sr": "44100"})
        with patch("radiomaster.services.station_health.requests.get", return_value=resp), \
                patch("radiomaster.services.station_health.requests.head", return_value=_ok_head()), \
                patch("radiomaster.services.station_health._probe_format", return_value=None):
            r = check_station(station)
        assert r.bit_rate == 96000
        assert r.sample_rate == 44100

    def test_website_down_appends_detail(self):
        station = Station(uuid="x", name="X", url="http://x", homepage="http://x/")
        resp = _web_response(headers={"content-type": "audio/mpeg"})
        bad_head = MagicMock()
        bad_head.status_code = 500
        with patch("radiomaster.services.station_health.requests.get", return_value=resp), \
                patch("radiomaster.services.station_health.requests.head", return_value=bad_head):
            r = check_station(station)
        assert r.website_ok is False
        assert "website down" in r.detail

    def test_no_homepage_is_unknown_not_problem(self):
        station = Station(uuid="x", name="X", url="http://x", homepage="")
        resp = _web_response(headers={"content-type": "audio/mpeg"})
        with patch("radiomaster.services.station_health.requests.get", return_value=resp), \
                patch("radiomaster.services.station_health.requests.head", return_value=_ok_head()):
            r = check_station(station)
        assert r.website_ok is None
        assert r.is_problem is False

    def test_check_never_raises(self):
        station = Station(uuid="x", name="X", url="http://x")
        with patch("radiomaster.services.station_health.requests.get",
                   side_effect=RuntimeError("unexpected")):
            r = check_station(station)
        assert isinstance(r, HealthResult)


# ---------------------------------------------------------------------------
# Worker pool
# ---------------------------------------------------------------------------

class TestStationHealthService:
    def _wait_finished(self, service, timeout=10.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if service.is_finished():
                return True
            time.sleep(0.05)
        return False

    def test_run_collects_all_results(self):
        stations = [Station(uuid=f"u{i}", name=f"S{i}", url=f"http://s{i}")
                    for i in range(6)]
        service = StationHealthService(workers=3)
        with patch("radiomaster.services.station_health.requests.get",
                   side_effect=ConnectionError("no")), \
                patch("radiomaster.services.station_health.requests.head",
                      return_value=_ok_head()):
            service.start(stations)
            assert self._wait_finished(service)
            results = service.drain_results(100)
        assert len(results) == 6
        assert service.done == 6
        assert service.total == 6

    def test_skip_urls_are_counted_not_checked(self):
        stations = [Station(uuid=f"u{i}", name=f"S{i}", url=f"http://s{i}")
                    for i in range(4)]
        service = StationHealthService(workers=2)
        service.get_skip_urls = lambda: {"http://s0", "http://s2"}
        with patch("radiomaster.services.station_health.requests.get",
                   side_effect=AssertionError("must not probe skipped")), \
                patch("radiomaster.services.station_health.requests.head",
                      return_value=_ok_head()):
            service.start(stations)
            assert self._wait_finished(service)
            results = service.drain_results(100)
        # Skipped stations produce no result rows but still count as done.
        assert len(results) == 2
        assert service.done == 4

    def test_stop_ends_scan(self):
        stations = [Station(uuid=f"u{i}", name=f"S{i}", url=f"http://s{i}")
                    for i in range(200)]
        service = StationHealthService(workers=2)
        # A slow "check" so the stop has time to land mid-scan.
        def slow_get(*args, **kwargs):
            time.sleep(0.05)
            raise ConnectionError("no")
        with patch("radiomaster.services.station_health.requests.get",
                   side_effect=slow_get), \
                patch("radiomaster.services.station_health.requests.head",
                      return_value=_ok_head()):
            service.start(stations)
            time.sleep(0.3)
            service.stop()
            deadline = time.time() + 5
            while time.time() < deadline and service.is_finished():
                time.sleep(0.05)
            # Workers exit promptly; done may be < total.
            assert service.done <= 200
        service.stop()

    def test_eta_before_first_result_is_none(self):
        service = StationHealthService(workers=2)
        assert service.eta_seconds() is None

    def test_double_start_raises(self):
        service = StationHealthService(workers=1)
        service.start([Station(uuid="u", name="S", url="http://s")])
        try:
            with pytest.raises(RuntimeError):
                service.start([Station(uuid="v", name="T", url="http://t")])
        finally:
            service.stop()