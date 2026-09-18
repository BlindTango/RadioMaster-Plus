"""Bulk removal follows single-entry removal semantics and protects recordings."""

import sqlite3
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import wx

from radiomaster.database.connection import DatabaseManager
from radiomaster.database.repository import DownloadRepository
from radiomaster.ui.downloads_panel import DownloadsPanel


@pytest.mark.parametrize("outcome", ["yes", "no", "full"])
def test_remove_all_active(tmp_path, monkeypatch, outcome):
    db = DatabaseManager(str(tmp_path))
    db.initialize()
    try:
        repo = DownloadRepository(db)
        queued = repo.add("queued")
        running = repo.add("running")
        repo.update_progress(running, 25, "downloading")
        recording = repo.add("live", source_type="radio_recording")
        stale = repo.add("stale", source_type="radio_recording")
        completed = repo.add_completed("done", "Done")
        failed = repo.add("failed")
        repo.update_progress(failed, 0, "failed")
        panel = SimpleNamespace(
            _db=db, _load_data=MagicMock(),
            on_check_recording_active=lambda did: did == recording,
        )
        panel._delete_history_entries = lambda *args, **kwargs: (
            DownloadsPanel._delete_history_entries(panel, *args, **kwargs))
        prompt = MagicMock(return_value=wx.NO if outcome == "no" else wx.YES)
        monkeypatch.setattr(wx, "MessageBox", prompt)
        if outcome == "full":
            monkeypatch.setattr(db, "commit", MagicMock(
                side_effect=sqlite3.OperationalError("database or disk is full")))
        DownloadsPanel._on_remove_all_active(panel, None)
        for did in (queued, running, stale):
            assert (repo.get(did) is None) is (outcome == "yes")
        for did in (recording, completed, failed):
            assert repo.get(did)
        assert "3 removable entries" in prompt.call_args_list[0].args[0]
        assert "continue" in prompt.call_args_list[0].args[0]
        assert panel._load_data.call_count == int(outcome == "yes")
        assert not db.conn.in_transaction
        if outcome == "full":
            assert prompt.call_args.args[1] == "Drive Full"
    finally:
        db.close()


def test_active_menu_remove_all_without_selection(monkeypatch):
    menu = MagicMock()
    items = {}

    def append(item_id, label):
        item = MagicMock()
        item.GetId.return_value = len(items) + 100
        items[label] = item
        return item

    menu.Append.side_effect = append
    monkeypatch.setattr(wx, "Menu", lambda: menu)
    monkeypatch.setattr("radiomaster.ui.downloads_panel.context_menu_pos", lambda *args: (0, 0))
    panel = SimpleNamespace(_active_list=MagicMock(), _active_rows=[], _db=MagicMock(),
                            _on_remove_all_active=MagicMock())
    panel._active_list.GetFirstSelected.return_value = -1
    panel._active_list.GetPopupMenuSelectionFromUser.side_effect = (
        lambda *args: items["Remove &All"].GetId())
    DownloadsPanel._on_active_context_menu(panel, None)
    menu.Destroy.assert_called_once()
    panel._on_remove_all_active.assert_called_once()
    items["Re&move"].Enable.assert_called_once_with(False)
    items["Remove &All"].Enable.assert_called_once_with(True)


@pytest.mark.parametrize("source,status,live,enabled", [
    ("radio_recording", "downloading", True, True),
    ("radio_recording", "downloading", False, False),
    ("radio_recording", "queued", True, False),
    ("radio_recording", "completed", False, False),
    ("podcast", "downloading", True, False),
])
def test_stop_recording_menu_availability_and_target(monkeypatch, source, status, live, enabled):
    menu = MagicMock()
    items = {}

    def append(item_id, label):
        item = MagicMock()
        item.GetId.return_value = len(items) + 100
        items[label] = item
        return item

    menu.Append.side_effect = append
    monkeypatch.setattr(wx, "Menu", lambda: menu)
    monkeypatch.setattr("radiomaster.ui.downloads_panel.context_menu_pos", lambda *args: (0, 0))
    row = {"id": 1, "source_type": source, "status": status}
    panel = SimpleNamespace(
        _active_list=MagicMock(), _active_rows=[row], _db=MagicMock(),
        on_stop_recording=MagicMock(), on_check_recording_active=lambda did: live,
        _on_stop_recording=MagicMock(),
    )
    panel._active_list.GetFirstSelected.return_value = 0

    def choose(*args):
        # A timer refresh must not change which recording the command stops.
        panel._active_rows = [{"id": 2}]
        return items["Stop &Recording"].GetId() if enabled else wx.ID_NONE

    panel._active_list.GetPopupMenuSelectionFromUser.side_effect = choose
    DownloadsPanel._on_active_context_menu(panel, None)
    items["Stop &Recording"].Enable.assert_called_once_with(enabled)
    if enabled:
        panel._on_stop_recording.assert_called_once_with(None, row=row)
    else:
        panel._on_stop_recording.assert_not_called()
