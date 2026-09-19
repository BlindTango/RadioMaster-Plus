"""History menu actions survive refreshes and remove only history records."""

from types import SimpleNamespace
import errno
import sqlite3
from unittest.mock import MagicMock

import pytest
import wx

from radiomaster.database.connection import DatabaseManager
from radiomaster.database.repository import DownloadRepository
from radiomaster.ui.downloads_panel import DownloadsPanel


@pytest.fixture
def history(tmp_path, monkeypatch):
    db = DatabaseManager(str(tmp_path / "db"))
    db.initialize()
    repo = DownloadRepository(db)
    media = tmp_path / "episode.mp3"
    media.write_bytes(b"audio")
    completed = repo.add_completed("https://example.test/1", "Completed", file_path=str(media))
    failed = repo.add("https://example.test/2", title="Failed")
    repo.update_progress(failed, 0, "failed")
    queued = repo.add("https://example.test/3")
    panel = SimpleNamespace(
        _db=db, _history_rows=[repo.get(completed)], _history_list=MagicMock(),
        _playing_history_id=completed, _load_data=MagicMock(),
    )
    panel._history_list.GetFirstSelected.return_value = 0
    panel._on_remove_history = lambda event, **kwargs: DownloadsPanel._on_remove_history(
        panel, event, **kwargs)
    panel._on_remove_all_history = lambda event: DownloadsPanel._on_remove_all_history(panel, event)
    panel._delete_history_entries = lambda *args: DownloadsPanel._delete_history_entries(panel, *args)
    confirmation = MagicMock(return_value=wx.YES)
    monkeypatch.setattr(wx, "MessageBox", confirmation)
    yield panel, repo, completed, failed, queued, media, confirmation
    db.close()


def select_menu_action(monkeypatch, panel, label, refresh=None):
    menu = MagicMock()
    items = {}

    def append(item_id, text):
        item = MagicMock()
        item.GetId.return_value = 100 + len(items)
        items[text] = item
        return item

    menu.Append.side_effect = append
    monkeypatch.setattr(wx, "Menu", lambda: menu)
    monkeypatch.setattr("radiomaster.ui.downloads_panel.context_menu_pos", lambda *args: (0, 0))

    def choose(*args):
        if refresh:
            refresh()
        return items[label].GetId() if label else wx.ID_NONE

    panel._history_list.GetPopupMenuSelectionFromUser.side_effect = choose
    return menu


@pytest.mark.parametrize("label", ["R&emove", "Remove &All"])
@pytest.mark.parametrize("confirm", [True, False])
def test_history_menu_removal(history, monkeypatch, label, confirm):
    panel, repo, completed, failed, queued, media, confirmation = history

    def refresh():
        panel._history_rows = []
        panel._history_list.GetFirstSelected.return_value = -1

    menu = select_menu_action(monkeypatch, panel, label, refresh)

    def respond(*args):
        menu.Destroy.assert_called_once()
        assert args[3] is panel
        return wx.YES if confirm else wx.NO

    confirmation.side_effect = respond
    DownloadsPanel._on_history_context_menu(panel, MagicMock())
    assert (repo.get(completed) is None) is confirm
    assert (repo.get(failed) is None) is (confirm and label == "Remove &All")
    assert repo.get(queued)["status"] == "queued"
    assert media.read_bytes() == b"audio"
    assert panel._load_data.call_count == int(confirm)
    if label == "Remove &All":
        assert "Remove all 2 entries" in confirmation.call_args.args[0]


def test_dismissing_menu_does_nothing(history, monkeypatch):
    panel, repo, completed, failed, queued, media, confirmation = history
    select_menu_action(monkeypatch, panel, None)
    DownloadsPanel._on_history_context_menu(panel, MagicMock())
    confirmation.assert_not_called()
    assert repo.get(completed)
    assert repo.get(failed)


def test_refresh_available_without_history_selection(history, monkeypatch):
    panel, repo, completed, failed, queued, media, confirmation = history
    panel._history_rows = []
    panel._history_list.GetFirstSelected.return_value = -1
    select_menu_action(monkeypatch, panel, "Re&fresh")
    DownloadsPanel._on_history_context_menu(panel, MagicMock())
    panel._load_data.assert_called_once()
    confirmation.assert_not_called()


def test_remove_does_not_delete_entry_retried_while_menu_open(history, monkeypatch):
    panel, repo, completed, failed, queued, media, confirmation = history
    select_menu_action(monkeypatch, panel, "R&emove", lambda: repo.reset_for_retry(completed))
    DownloadsPanel._on_history_context_menu(panel, MagicMock())
    assert repo.get(completed)["status"] == "queued"


def test_history_refresh_preserves_selection(history):
    panel, repo, completed, failed, queued, media, confirmation = history
    panel._active_rows = []
    panel._active_list = MagicMock()
    panel._active_list.GetFirstSelected.return_value = -1
    panel._history_limit = lambda: 50
    panel._history_list.GetItemData.return_value = completed
    panel._history_list.InsertItem.side_effect = lambda index, title: index
    DownloadsPanel._load_data(panel)
    assert [row["id"] for row in panel._history_rows] == [failed, completed]
    panel._history_list.Select.assert_called_once_with(1)


@pytest.mark.parametrize("remove_all", [False, True])
@pytest.mark.parametrize("stage", ["execute", "commit"])
@pytest.mark.parametrize("kind", ["sqlite_full", "os_full", "locked"])
def test_history_write_failure_warns_and_rolls_back(history, monkeypatch, remove_all, stage, kind):
    panel, repo, completed, failed, queued, media, confirmation = history
    if kind == "sqlite_full":
        error = sqlite3.OperationalError("database or disk is full")
        error.sqlite_errorcode = sqlite3.SQLITE_FULL
    elif kind == "os_full":
        error = OSError(errno.ENOSPC, "No space left on device")
    else:
        error = sqlite3.OperationalError("database is locked")
        error.sqlite_errorcode = sqlite3.SQLITE_BUSY
    original = getattr(panel._db, stage)
    monkeypatch.setattr(panel._db, stage, MagicMock(side_effect=error))
    handler = panel._on_remove_all_history if remove_all else panel._on_remove_history
    handler(None)

    assert confirmation.call_count == 2
    message, title, style, parent = confirmation.call_args.args
    assert parent is panel
    assert style == wx.OK | wx.ICON_ERROR
    if kind == "locked":
        assert title == "Could Not Update Download History"
        assert "database is locked" in message
    else:
        assert title == "Drive Full"
        assert "Free some space" in message
    assert repo.get(completed)
    assert repo.get(failed)
    assert repo.get(queued)
    assert not panel._db.conn.in_transaction
    assert panel._playing_history_id == completed
    panel._load_data.assert_not_called()
    assert media.read_bytes() == b"audio"

    # After space is available, retrying the same action succeeds.
    monkeypatch.setattr(panel._db, stage, original)
    handler(None)
    assert repo.get(completed) is None
    assert (repo.get(failed) is None) is remove_all
    panel._load_data.assert_called_once()
