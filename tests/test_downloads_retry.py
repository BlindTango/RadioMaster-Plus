"""Bulk retries include hidden history and preserve stored download settings."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from radiomaster.database.connection import DatabaseManager
from radiomaster.database.repository import DownloadRepository
from radiomaster.ui.downloads_panel import DownloadsPanel


def test_retry_all_failed_uses_full_history(tmp_path, monkeypatch):
    db = DatabaseManager(str(tmp_path))
    db.initialize()
    try:
        repo = DownloadRepository(db)
        failed = []
        for index in range(3):
            download_id = repo.add(
                f"https://example.com/{index}", title=f"Episode {index}",
                source_type="podcast", format="mp3", quality="192k",
                output_dir=str(tmp_path), extract_audio=True, filename_base=f"episode-{index}",
            )
            db.execute("UPDATE downloads SET status = 'failed', progress = 42, error = 'error' "
                       "WHERE id = ?", (download_id,))
            failed.append(download_id)
        completed = repo.add_completed("https://example.com/done", "Done")
        queued = repo.add("https://example.com/queued")
        db.commit()
        manager = MagicMock()
        monkeypatch.setattr("wx.GetApp", lambda: SimpleNamespace(download_manager=manager))
        panel = SimpleNamespace(_db=db, _history_rows=[repo.get(completed)],
                                _load_data=MagicMock())
        panel._resubmit = lambda row, **kwargs: DownloadsPanel._resubmit(panel, row, **kwargs)

        DownloadsPanel._on_retry_all_failed(panel, None)

        assert [call.args[0] for call in manager.add_download.call_args_list] == failed
        for index, call in enumerate(manager.add_download.call_args_list):
            assert call.kwargs["format"] == "mp3"
            assert call.kwargs["audio_quality"] == "192K"
            assert call.kwargs["extract_audio"] is True
            assert call.kwargs["filename_base"] == f"episode-{index}"
            row = repo.get(failed[index])
            assert (row["status"], row["progress"], row["error"]) == ("queued", 0, None)
        assert repo.get(completed)["status"] == "completed"
        assert repo.get(queued)["status"] == "queued"
        panel._load_data.assert_called_once()

        DownloadsPanel._on_retry_all_failed(panel, None)
        assert manager.add_download.call_count == 3
    finally:
        db.close()


def test_history_menu_allows_bulk_retry_without_selection(monkeypatch):
    menu = MagicMock()
    monkeypatch.setattr("wx.Menu", lambda: menu)
    monkeypatch.setattr("radiomaster.ui.downloads_panel.context_menu_pos", lambda *args: (0, 0))
    panel = SimpleNamespace(
        _history_list=MagicMock(), _history_rows=[], _db=MagicMock(),
        Bind=MagicMock(), _on_retry_all_failed=MagicMock(),
    )
    panel._history_list.GetFirstSelected.return_value = -1
    DownloadsPanel._on_history_context_menu(panel, MagicMock())
    assert "Retry all &failed downloads" in [call.args[1] for call in menu.Append.call_args_list]
    panel._history_list.PopupMenu.assert_called_once()


def test_missing_manager_leaves_failure_unchanged(monkeypatch):
    monkeypatch.setattr("wx.GetApp", lambda: SimpleNamespace())
    panel = SimpleNamespace(_db=MagicMock())
    DownloadsPanel._resubmit(panel, {"id": 1}, refresh=False)
    panel._db.execute.assert_not_called()
