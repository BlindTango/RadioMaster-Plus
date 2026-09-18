"""Bulk retries include hidden history and preserve stored download settings."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from radiomaster.database.connection import DatabaseManager
from radiomaster.database.repository import DownloadRepository
from radiomaster.ui.downloads_panel import DownloadsPanel
from radiomaster.services.download_manager import DownloadManager


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
    panel._history_list.GetPopupMenuSelectionFromUser.assert_called_once()


def test_missing_manager_leaves_failure_unchanged(monkeypatch):
    monkeypatch.setattr("wx.GetApp", lambda: SimpleNamespace())
    panel = SimpleNamespace(_db=MagicMock())
    DownloadsPanel._resubmit(panel, {"id": 1}, refresh=False)
    panel._db.execute.assert_not_called()


@pytest.mark.parametrize("source,stored_format,expected_format,audio", [
    ("podcast", "mp3", "mp3", True),
    ("youtube", "ogg", "opus", True),
    ("youtube", "", "bestvideo+bestaudio/best", False),
    ("youtube", "720p", "bestvideo[height<=720]+bestaudio/best[height<=720]", False),
])
def test_legacy_retry_moves_to_active_and_reaches_downloader(
    tmp_path, monkeypatch, source, stored_format, expected_format, audio,
):
    db = DatabaseManager(str(tmp_path / "db"))
    db.initialize()
    try:
        repo = DownloadRepository(db)
        download_id = repo.add("https://example.test/media", source_type=source,
                               format=stored_format)
        repo.update_progress(download_id, 0, status="failed")
        manager = DownloadManager()
        manager.on_progress(lambda did, pct: repo.update_progress(did, pct, "downloading"))
        manager.on_error(lambda did, msg: repo.update_progress(did, 0, "failed"))
        manager.on_complete(repo.mark_completed)
        monkeypatch.setattr("wx.GetApp", lambda: SimpleNamespace(download_manager=manager))
        for kind in ("podcasts", "downloads"):
            monkeypatch.setattr(f"radiomaster.utils.paths.get_{kind}_dir",
                                lambda kind=kind: str(tmp_path / kind))
        monkeypatch.setattr("radiomaster.services.download_manager.get_ytdlp", lambda: "yt-dlp")
        monkeypatch.setattr("radiomaster.services.download_manager.get_ffmpeg", lambda: "ffmpeg")
        monkeypatch.setattr("radiomaster.utils.network.get_yt_dlp_proxy_args", lambda: [])
        monkeypatch.setattr("radiomaster.utils.network.get_timeout", lambda **kwargs: 10)
        monkeypatch.setattr("radiomaster.utils.config.ConfigManager.get_instance",
                            lambda: SimpleNamespace(get=lambda *args, **kwargs: False))
        panel = SimpleNamespace(_db=db, _active_rows=[], _history_rows=[],
                                _active_list=MagicMock(), _history_list=MagicMock(),
                                _history_limit=lambda: 50)
        panel._active_list.GetFirstSelected.return_value = -1
        panel._history_list.GetFirstSelected.return_value = -1
        panel._load_data = lambda: DownloadsPanel._load_data(panel)
        panel._resubmit = lambda row, **kwargs: DownloadsPanel._resubmit(panel, row, **kwargs)

        DownloadsPanel._on_retry_all_failed(panel, None)
        assert [row["id"] for row in panel._active_rows] == [download_id]
        assert panel._history_rows == []

        def progress():
            yield "[download] 25%"
            panel._load_data()
            assert panel._active_rows[0]["status"] == "downloading"
            assert panel._history_rows == []

        process = MagicMock(stdout=progress(), returncode=0)
        launch = MagicMock(return_value=process)
        monkeypatch.setattr("radiomaster.services.download_manager.subprocess.Popen", launch)
        manager._execute_download(manager._queue.get_nowait())
        command = launch.call_args.args[0]
        assert expected_format in command
        assert ("-x" in command) is audio
        assert (tmp_path / ("podcasts" if source == "podcast" else "downloads")).is_dir()
        assert repo.get(download_id)["status"] == "completed"
    finally:
        db.close()
