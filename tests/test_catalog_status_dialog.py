"""Tests for the Station Catalog Status dialog and its relative-time helper."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
import wx

from radiomaster.services.station_api import Station
from radiomaster.services.station_db import StationDB
from radiomaster.ui.catalog_status_dialog import (
    CatalogStatusDialog,
    _next_run,
    relative_time,
)


@pytest.fixture
def app():
    existing = wx.GetApp()
    if existing is None:
        app = wx.App(False)
        wx.Log.SetActiveTarget(wx.LogStderr())
        yield app
    else:
        yield existing


@pytest.fixture
def station_db(tmp_path):
    db = StationDB(str(tmp_path / "stations.db"))
    db.upsert_stations([
        Station(uuid="a", name="A Radio", url="http://a"),
        Station(uuid="b", name="B Radio", url="http://b"),
    ])
    return db


class TestRelativeTime:
    def test_none_is_never(self) -> None:
        # A missing timestamp gets its own sentence, never silence.
        assert relative_time(None) == "never"

    def test_just_now(self) -> None:
        now = datetime(2026, 10, 9, 12, 0, 0)
        assert relative_time(now - timedelta(seconds=30), now) == "just now"

    def test_minutes(self) -> None:
        now = datetime(2026, 10, 9, 12, 0, 0)
        assert relative_time(now - timedelta(minutes=5), now) == "5 minutes ago"
        assert relative_time(now - timedelta(minutes=1), now) == "1 minute ago"

    def test_hours(self) -> None:
        now = datetime(2026, 10, 9, 12, 0, 0)
        assert relative_time(now - timedelta(hours=3), now) == "3 hours ago"
        assert relative_time(now - timedelta(hours=1), now) == "1 hour ago"

    def test_days(self) -> None:
        now = datetime(2026, 10, 9, 12, 0, 0)
        assert relative_time(now - timedelta(days=3), now) == "3 days ago"
        assert relative_time(now - timedelta(days=1), now) == "1 day ago"

    def test_months_and_years(self) -> None:
        now = datetime(2026, 10, 9, 12, 0, 0)
        assert relative_time(now - timedelta(days=62), now) == "2 months ago"
        assert relative_time(now - timedelta(days=400), now) == "1 year ago"

    def test_future_is_just_now(self) -> None:
        now = datetime(2026, 10, 9, 12, 0, 0)
        assert relative_time(now + timedelta(minutes=5), now) == "just now"


class TestNextRun:
    def test_off_has_no_next_run(self) -> None:
        now = datetime(2026, 10, 9, 12, 0, 0)
        assert _next_run("off", None, now) is None

    def test_unknown_frequency_has_no_next_run(self) -> None:
        now = datetime(2026, 10, 9, 12, 0, 0)
        assert _next_run("bogus", None, now) is None

    def test_daily_tomorrow_when_past_off_hour(self) -> None:
        now = datetime(2026, 10, 9, 12, 0, 0)  # after 3 AM
        nxt = _next_run("daily", None, now)
        assert nxt == datetime(2026, 10, 10, 3, 0, 0)

    def test_daily_today_when_before_off_hour(self) -> None:
        now = datetime(2026, 10, 9, 1, 0, 0)  # before 3 AM
        nxt = _next_run("daily", None, now)
        assert nxt == datetime(2026, 10, 9, 3, 0, 0)

    def test_weekly_is_sunday_3am(self) -> None:
        # 2026-10-09 is a Friday; next Sunday is 2026-10-11.
        now = datetime(2026, 10, 9, 12, 0, 0)
        nxt = _next_run("weekly", None, now)
        assert nxt == datetime(2026, 10, 11, 3, 0, 0)
        assert nxt.weekday() == 6  # Sunday


class TestCatalogStatusDialog:
    def test_summary_sentences(self, app, station_db) -> None:
        station_db.set_metadata("last_updated", datetime.now().isoformat())
        dlg = CatalogStatusDialog(None, station_db, MagicMock(), frequency="weekly")
        try:
            text = dlg._summary.GetValue()
            assert "2 stations stored in the offline catalog." in text
            assert "Last updated just now." in text
            assert "Refreshes weekly." in text
            assert "Next scheduled update" in text
        finally:
            dlg.Destroy()

    def test_summary_announces_on_open(self, app, station_db) -> None:
        station_db.set_metadata("last_updated", datetime.now().isoformat())
        dlg = CatalogStatusDialog(None, station_db, MagicMock(), frequency="weekly")
        try:
            sentence = dlg.summary_sentence()
            assert sentence == "2 stations stored. Last updated just now. Refreshes weekly."
        finally:
            dlg.Destroy()

    def test_never_updated_gets_its_own_sentence(self, app, tmp_path) -> None:
        # A DB with stations but no last_updated metadata: upsert_stations
        # stamps the metadata, so build the rows without it.
        db = StationDB(str(tmp_path / "never.db"))
        db.upsert_stations([
            Station(uuid="a", name="A Radio", url="http://a"),
        ])
        db.set_metadata("last_updated", "")  # simulate a never-updated catalog
        dlg = CatalogStatusDialog(None, db, MagicMock(), frequency="weekly")
        try:
            text = dlg._summary.GetValue()
            assert "Last updated never." in text
        finally:
            dlg.Destroy()

    def test_off_frequency_gets_its_own_sentence(self, app, station_db) -> None:
        dlg = CatalogStatusDialog(None, station_db, MagicMock(), frequency="off")
        try:
            text = dlg._summary.GetValue()
            assert "Automatic refresh is off." in text
            assert "No update is currently scheduled." in text
        finally:
            dlg.Destroy()

    def test_update_now_reuses_updater_flow(self, app, station_db) -> None:
        """Update Now must call the existing StationUpdater.update_now
        (with its progress callback), not a duplicated fetch."""
        from radiomaster.services.station_updater import UpdateResult

        updater = MagicMock()
        updater.update_now.return_value = UpdateResult(ok=True, changed=1, unchanged=1)
        dlg = CatalogStatusDialog(None, station_db, updater, frequency="weekly")
        try:
            dlg._on_update_now(MagicMock())
            # The worker thread runs update_now; wait for it.
            import time
            deadline = time.monotonic() + 5
            while not updater.update_now.called and time.monotonic() < deadline:
                wx.Yield()
                time.sleep(0.01)
            assert updater.update_now.called
            assert updater.update_now.call_args.kwargs.get("progress_cb") is not None
        finally:
            dlg.Destroy()

    def test_update_failure_gets_specific_sentence(self, app, station_db) -> None:
        from radiomaster.services.station_updater import UpdateResult

        updater = MagicMock()
        updater.update_now.return_value = UpdateResult(ok=False, error="Network unreachable")
        dlg = CatalogStatusDialog(None, station_db, updater, frequency="weekly")
        try:
            dlg._on_update_now(MagicMock())
            import time
            deadline = time.monotonic() + 5
            while "Update failed" not in dlg._summary.GetValue() and time.monotonic() < deadline:
                wx.Yield()
                time.sleep(0.01)
            assert "Update failed: Network unreachable" in dlg._summary.GetValue()
            assert dlg._update_btn.IsEnabled()
        finally:
            dlg.Destroy()