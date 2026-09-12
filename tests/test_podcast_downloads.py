"""Download All must leave the UI free while preparing a stable episode snapshot."""
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from test_podcast_import import panel_method


def batch_panel():
    return SimpleNamespace(
        _episode_data=[{"id": 1, "audio_url": "https://one"},
                       {"id": 2, "audio_url": "https://two"}, {"id": 3}],
        _current_podcast_title="Original show", _db=MagicMock(),
        _set_status=MagicMock(), _finish_download_all=MagicMock(),
        _podcast_download_settings=MagicMock(return_value=("folder", "mp3", "192k", "192K")),
        _queue_podcast_episode=MagicMock(),
    )


def batch_handler(monkeypatch):
    workers = []
    monkeypatch.setattr(threading, "Thread", lambda **kwargs: (
        workers.append(kwargs["target"]) or MagicMock()
    ))
    wx = SimpleNamespace(YES=1, NO=2, YES_NO=3, OK=4, ICON_QUESTION=8,
                         ICON_INFORMATION=16, ICON_WARNING=32,
                         MessageBox=MagicMock(return_value=1),
                         GetApp=MagicMock(return_value=SimpleNamespace(download_manager=MagicMock())))
    callbacks = MagicMock()
    method = panel_method("_on_download_all", wx=wx, call_after_safe=callbacks, logger=MagicMock())
    return method, workers, wx, callbacks


def test_batch_returns_before_io_and_uses_confirmed_snapshot(monkeypatch):
    method, workers, wx, callbacks = batch_handler(monkeypatch)
    panel = batch_panel()
    method(panel)
    panel._podcast_download_settings.assert_not_called()
    panel._queue_podcast_episode.assert_not_called()
    assert len(workers) == 1
    panel._episode_data[0]["audio_url"] = "https://changed"
    panel._episode_data = []
    panel._current_podcast_title = "Different show"
    method(panel)  # A second command must not start another batch.
    assert len(workers) == 1
    workers[0]()
    panel._podcast_download_settings.assert_called_once_with("Original show")
    assert panel._queue_podcast_episode.call_count == 2
    first = panel._queue_podcast_episode.call_args_list[0].args
    assert first[0]["audio_url"] == "https://one"
    assert first[1] == "Original show"
    callbacks.assert_called_once_with(panel, panel._finish_download_all, "Original show", 2, 1, 0)
    panel._db.close.assert_called_once()


def test_batch_continues_after_one_episode_fails(monkeypatch):
    method, workers, wx, callbacks = batch_handler(monkeypatch)
    panel = batch_panel()
    panel._queue_podcast_episode.side_effect = [OSError("disk error"), None]
    method(panel)
    workers[0]()
    assert panel._queue_podcast_episode.call_count == 2
    panel._db.conn.rollback.assert_called_once()
    callbacks.assert_called_once_with(panel, panel._finish_download_all, "Original show", 1, 1, 1)


def test_cancel_does_not_start_worker(monkeypatch):
    method, workers, wx, callbacks = batch_handler(monkeypatch)
    wx.MessageBox.return_value = wx.NO
    method(batch_panel())
    assert workers == []


def test_settings_error_still_completes_batch(monkeypatch):
    method, workers, wx, callbacks = batch_handler(monkeypatch)
    panel = batch_panel()
    panel._podcast_download_settings.side_effect = OSError("drive unavailable")
    method(panel)
    workers[0]()
    callbacks.assert_called_once_with(panel, panel._finish_download_all, "Original show", 0, 0, 3)
    panel._db.close.assert_called_once()
