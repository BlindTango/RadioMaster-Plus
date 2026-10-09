"""Tests for the Listening Statistics dialog and the first-run wizard."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
import wx

from radiomaster.database.connection import DatabaseManager
from radiomaster.services.stats_service import StatsService
from radiomaster.ui.first_run_dialog import FirstRunDialog, PAGES
from radiomaster.ui.stats_dialog import StatsDialog, format_duration


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
def db() -> DatabaseManager:
    import tempfile
    tmp_dir = tempfile.mkdtemp()
    manager = DatabaseManager(tmp_dir)
    manager.initialize()
    yield manager
    manager.close()


@pytest.fixture
def stats(db: DatabaseManager) -> StatsService:
    return StatsService(db)


class TestFormatDuration:
    def test_hours_and_minutes(self) -> None:
        assert format_duration(4 * 3600 + 12 * 60) == "4 hours 12 minutes"

    def test_one_hour(self) -> None:
        assert format_duration(3600) == "1 hour 0 minutes"

    def test_minutes(self) -> None:
        assert format_duration(300) == "5 minutes 0 seconds"

    def test_seconds(self) -> None:
        assert format_duration(30) == "30 seconds"
        assert format_duration(1) == "1 second"


class TestStatsDialog:
    def test_summary_sentences(self, app, stats, db) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        db.execute(
            "INSERT INTO listening_sessions (source_type, source_id, title, "
            "started_at, ended_at, seconds_listened) VALUES (?, ?, ?, ?, ?, ?)",
            ("station", "u1", "A Radio", now, now, 4 * 3600 + 12 * 60),
        )
        db.commit()
        dlg = StatsDialog(None, stats)
        try:
            text = dlg._summary.GetValue()
            assert "This week: 4 hours 12 minutes across 1 session." in text
            assert "Today: 4 hours 12 minutes across 1 session." in text
            assert "All time: 4 hours 12 minutes across 1 session." in text
        finally:
            dlg.Destroy()

    def test_announcement_on_open(self, app, stats, db) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        db.execute(
            "INSERT INTO listening_sessions (source_type, source_id, title, "
            "started_at, ended_at, seconds_listened) VALUES (?, ?, ?, ?, ?, ?)",
            ("station", "u1", "A Radio", now, now, 4 * 3600 + 12 * 60),
        )
        db.commit()
        dlg = StatsDialog(None, stats)
        try:
            assert dlg.summary_sentence() == (
                "You have listened for 4 hours 12 minutes this week."
            )
        finally:
            dlg.Destroy()

    def test_empty_stats_get_their_own_sentences(self, app, stats) -> None:
        dlg = StatsDialog(None, stats)
        try:
            text = dlg._summary.GetValue()
            assert "Today: 0 seconds across 0 sessions." in text
            assert dlg._top_list.GetItemCount() == 2
            assert dlg._top_list.GetItemText(0, 0) == "Top stations"
            assert dlg._top_list.GetItemText(0, 1) == "No stations listened to yet."
            assert dlg._top_list.GetItemText(1, 1) == "No shows listened to yet."
        finally:
            dlg.Destroy()

    def test_top_list_rows(self, app, stats, db) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        db.execute(
            "INSERT INTO listening_sessions (source_type, source_id, title, "
            "started_at, ended_at, seconds_listened) VALUES (?, ?, ?, ?, ?, ?)",
            ("station", "u1", "A Radio", now, now, 100),
        )
        db.execute(
            "INSERT INTO listening_sessions (source_type, source_id, title, "
            "started_at, ended_at, seconds_listened) VALUES (?, ?, ?, ?, ?, ?)",
            ("podcast", "p1", "A Show", now, now, 200),
        )
        db.commit()
        dlg = StatsDialog(None, stats)
        try:
            assert dlg._top_list.GetItemText(1, 0) == "A Radio"
            assert dlg._top_list.GetItemText(1, 1) == "1 minute 40 seconds"
            assert dlg._top_list.GetItemText(3, 0) == "A Show"
        finally:
            dlg.Destroy()


class TestFirstRunDialog:
    def test_pages_are_arrow_through_text(self, app) -> None:
        """Each page must be a read-only TextCtrl the user can arrow
        through -- Quill's contract, not a wall of static labels."""
        dlg = FirstRunDialog(None)
        try:
            assert isinstance(dlg._page_text, wx.TextCtrl)
            assert dlg._page_text.IsEditable() is False
            assert dlg._page_text.GetValue() == PAGES[0][1]
        finally:
            dlg.Destroy()

    def test_next_walks_all_pages_then_finishes(self, app) -> None:
        dlg = FirstRunDialog(None)
        try:
            for expected_index in range(1, len(PAGES)):
                dlg._on_next(MagicMock())
                assert dlg._page_text.GetValue() == PAGES[expected_index][1]
            assert dlg._next_btn.GetLabel() == "&Finish"
        finally:
            dlg.Destroy()

    def test_skip_leaves_in_one_keystroke(self, app) -> None:
        """Skip must end the dialog immediately -- one keystroke, no
        confirmation, no extra page."""
        dlg = FirstRunDialog(None)
        ended = []
        dlg.EndModal = lambda code: ended.append(code)
        dlg._skip_btn.GetEventHandler().ProcessEvent(
            wx.CommandEvent(wx.wxEVT_COMMAND_BUTTON_CLICKED, dlg._skip_btn.GetId())
        )
        assert ended == [wx.ID_CANCEL]
        dlg.Destroy()

    def test_focus_starts_in_the_text_box(self, app) -> None:
        dlg = FirstRunDialog(None)
        try:
            assert wx.Window.FindFocus() is dlg._page_text
        finally:
            dlg.Destroy()

    def test_wizard_has_no_network_or_account(self) -> None:
        """The wizard is pure text pages -- no network, no account."""
        import inspect
        source = inspect.getsource(FirstRunDialog)
        for forbidden in ("requests", "urllib", "http", "socket", "webbrowser"):
            assert forbidden not in source, forbidden