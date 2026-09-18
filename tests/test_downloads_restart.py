"""Restart must execute replacements without stale cancellation or callbacks."""

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import wx

from radiomaster.database.connection import DatabaseManager
from radiomaster.database.repository import DownloadRepository
from radiomaster.services.download_manager import DownloadManager
from radiomaster.ui.downloads_panel import DownloadsPanel


@pytest.fixture
def manager(monkeypatch):
    monkeypatch.setattr("radiomaster.services.download_manager.get_ytdlp", lambda: "yt-dlp")
    monkeypatch.setattr("radiomaster.services.download_manager.get_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr("radiomaster.utils.network.get_yt_dlp_proxy_args", lambda: [])
    monkeypatch.setattr("radiomaster.utils.network.get_timeout", lambda **kwargs: 10)
    monkeypatch.setattr("radiomaster.utils.config.ConfigManager.get_instance",
                        lambda: SimpleNamespace(get=lambda *args, **kwargs: False))
    result = DownloadManager(max_concurrent=2)
    yield result
    result.stop()
    for thread in result._threads:
        thread.join(timeout=3)
        assert not thread.is_alive()


@pytest.mark.parametrize("queued", [False, True])
def test_restart_executes_latest_attempt_even_when_paused(manager, tmp_path, monkeypatch, queued):
    launch = MagicMock(return_value=MagicMock(stdout=[], returncode=0))
    monkeypatch.setattr("radiomaster.services.download_manager.subprocess.Popen", launch)
    complete = threading.Event()
    manager.on_complete(lambda *args: complete.set())
    manager.pause()
    if queued:
        manager.add_download(1, "old", str(tmp_path))
    manager.cancel(1)
    manager.add_download(1, "intermediate", str(tmp_path))
    manager.cancel(1)
    manager.add_download(1, "replacement", str(tmp_path))
    manager.start()
    assert complete.wait(3)
    assert not manager.is_paused
    launch.assert_called_once()
    assert launch.call_args.args[0][-1] == "replacement"


def test_restart_waits_for_old_exit_and_ignores_old_progress(manager, tmp_path, monkeypatch):
    launched = threading.Event()
    killed = threading.Event()
    release_old = threading.Event()
    replacement_started = threading.Event()
    complete = threading.Event()
    progress = []
    errors = []

    def old_output():
        launched.set()
        assert killed.wait(3)
        yield "[download] 70%"  # Buffered output from the cancelled attempt.
        assert release_old.wait(3)

    old = MagicMock(stdout=old_output(), returncode=1)
    old.kill.side_effect = killed.set

    def launch(command, **kwargs):
        if command[-1] == "old":
            return old
        replacement_started.set()
        return MagicMock(stdout=["[download] 25%"], returncode=0)

    monkeypatch.setattr("radiomaster.services.download_manager.subprocess.Popen", launch)
    manager.on_progress(lambda did, pct: progress.append(pct))
    manager.on_error(lambda *args: errors.append(args))
    manager.on_complete(lambda *args: complete.set())
    manager.add_download(1, "old", str(tmp_path))
    manager.start()
    try:
        assert launched.wait(3)
        manager.cancel(1)
        manager.add_download(1, "replacement", str(tmp_path))
        assert not replacement_started.wait(0.1)
        release_old.set()
        assert complete.wait(3)
        assert replacement_started.is_set()
        assert 25 in progress
        assert 70 not in progress
        assert not errors
        old.wait.assert_called_once()
    finally:
        killed.set()
        release_old.set()


@pytest.mark.parametrize("confirm", [True, False])
def test_restart_all_starts_active_downloads_only(tmp_path, monkeypatch, confirm):
    db = DatabaseManager(str(tmp_path / "db"))
    db.initialize()
    try:
        repo = DownloadRepository(db)
        queued = repo.add("queued", output_dir=str(tmp_path))
        running = repo.add("running", output_dir=str(tmp_path))
        repo.update_progress(running, 30, "downloading")
        recording = repo.add("recording", source_type="radio_recording")
        failed = repo.add("failed")
        repo.update_progress(failed, 0, "failed")
        completed = repo.add_completed("done", "Done")
        manager = MagicMock()
        manager.prepare_restart.side_effect = lambda did, prepare: (
            (manager.cancel(did) or True) if prepare() else False)
        monkeypatch.setattr(wx, "GetApp", lambda: SimpleNamespace(download_manager=manager))
        monkeypatch.setattr(wx, "MessageBox", lambda *args: wx.YES if confirm else wx.NO)
        panel = SimpleNamespace(_db=db, _load_data=MagicMock())
        panel._resubmit = lambda row, **kwargs: DownloadsPanel._resubmit(panel, row, **kwargs)
        DownloadsPanel._on_restart_all_active(panel, None)
        assert [call.args[0] for call in manager.cancel.call_args_list] == (
            [queued, running] if confirm else [])
        assert manager.add_download.call_count == (2 if confirm else 0)
        assert manager.start.call_count == (2 if confirm else 0)
        assert panel._load_data.call_count == int(confirm)
        assert repo.get(recording)["status"] == "queued"
        assert repo.get(failed)["status"] == "failed"
        assert repo.get(completed)["status"] == "completed"
    finally:
        db.close()


def test_failed_restart_preparation_keeps_current_attempt(manager, tmp_path):
    manager.add_download(1, "old", str(tmp_path))
    current = manager._attempts[1]
    assert not manager.prepare_restart(1, lambda: False)
    assert not current["_cancel_event"].is_set()


def test_callback_storage_failure_keeps_workers_alive(manager, tmp_path, monkeypatch):
    import sqlite3
    error = sqlite3.OperationalError("database or disk is full")
    callback_error = MagicMock()
    manager.on_callback_error(callback_error)
    manager.on_progress(MagicMock(side_effect=error))
    completed = []
    done = threading.Event()

    def complete(did, path):
        completed.append(did)
        if len(completed) == 2:
            done.set()

    manager.on_complete(complete)
    monkeypatch.setattr("radiomaster.services.download_manager.subprocess.Popen",
                        lambda *args, **kwargs: MagicMock(stdout=[], returncode=0))
    for did in (1, 2):
        manager.add_download(did, str(did), str(tmp_path))
    manager.start()
    assert done.wait(3)
    manager._queue.join()
    assert sorted(completed) == [1, 2]
    assert callback_error.call_count == 2
    assert all(thread.is_alive() for thread in manager._threads)


def test_download_status_warning_rolls_back_and_is_announced_once(monkeypatch):
    import sqlite3
    from radiomaster.app import RadioMasterApp
    app = SimpleNamespace(_db=MagicMock(), _download_status_warning_shown=False)
    notify = MagicMock()
    monkeypatch.setattr(wx, "CallAfter", notify)
    error = sqlite3.OperationalError("database or disk is full")
    for _ in range(2):
        RadioMasterApp._on_download_status_error(app, error)
    assert app._db.conn.rollback.call_count == 2
    notify.assert_called_once()
    assert notify.call_args.args[2] == "Drive Full"
