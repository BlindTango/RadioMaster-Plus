"""Callbacks must tolerate both queuing-time and delivery-time shutdown."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from radiomaster.utils import wx_safe


class Lifetime:
    alive = True

    def __bool__(self):
        return self.alive


@pytest.fixture
def dispatcher(monkeypatch):
    app, window = Lifetime(), Lifetime()
    wx = SimpleNamespace(GetApp=MagicMock(return_value=app), CallAfter=MagicMock())
    monkeypatch.setattr(wx_safe, "wx", wx)
    return wx, app, window


def test_live_callback_receives_arguments(dispatcher):
    wx, _, window = dispatcher
    callback = MagicMock()
    wx_safe.call_after_safe(window, callback, "ready", 3)
    callback.assert_not_called()
    wx.CallAfter.call_args.args[0]()
    callback.assert_called_once_with("ready", 3)


@pytest.mark.parametrize("gone", ["app", "window", "no_app"])
def test_no_callback_queued_after_shutdown(dispatcher, gone):
    wx, app, window = dispatcher
    if gone == "no_app":
        wx.GetApp.return_value = None
    else:
        (app if gone == "app" else window).alive = False
    wx_safe.call_after_safe(window, MagicMock())
    wx.CallAfter.assert_not_called()


@pytest.mark.parametrize("gone", ["app", "window", "replacement_app"])
def test_callback_dropped_if_owner_dies_before_delivery(dispatcher, gone):
    wx, app, window = dispatcher
    callback = MagicMock()
    wx_safe.call_after_safe(window, callback)
    if gone == "replacement_app":
        wx.GetApp.return_value = Lifetime()
    else:
        (app if gone == "app" else window).alive = False
    wx.CallAfter.call_args.args[0]()
    callback.assert_not_called()


@pytest.mark.parametrize("error", [RuntimeError, AssertionError])
def test_app_destroyed_while_posting_is_safe(dispatcher, error):
    wx, app, window = dispatcher
    def shutdown(callback):
        app.alive = False
        raise error("application destroyed while posting")
    wx.CallAfter.side_effect = shutdown
    wx_safe.call_after_safe(window, MagicMock())


def test_unrelated_posting_error_is_not_swallowed(dispatcher):
    wx, _, window = dispatcher
    wx.CallAfter.side_effect = RuntimeError("unexpected error")
    with pytest.raises(RuntimeError, match="unexpected error"):
        wx_safe.call_after_safe(window, MagicMock())


@pytest.mark.parametrize("ok", [True, False])
def test_first_station_download_guards_progress_and_completion(monkeypatch, ok):
    import ast
    from pathlib import Path
    import threading
    source = ast.parse(Path("src/radiomaster/ui/radio_panel.py").read_text(encoding="utf-8"))
    cls = next(node for node in source.body if isinstance(node, ast.ClassDef) and node.name == "RadioPanel")
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "_load_stations")
    queued, workers = MagicMock(), []
    monkeypatch.setattr(threading, "Thread", lambda **kwargs: (
        workers.append(kwargs["target"]) or MagicMock()))
    namespace = {"threading": threading, "call_after_safe": queued}
    exec(compile(ast.Module(body=[method], type_ignores=[]), "radio_panel.py", "exec"), namespace)
    panel = SimpleNamespace(station_db=MagicMock(), station_updater=MagicMock(),
                            set_status=MagicMock(), _apply_sections=MagicMock())
    panel.station_db.station_count.return_value = 0
    def update(progress_cb):
        progress_cb(50, 100)
        progress_cb(1024, None)
        return SimpleNamespace(ok=ok, error="offline")
    panel.station_updater.update_now.side_effect = update
    namespace["_load_stations"](panel)
    workers[0]()
    assert queued.call_count == 3
    assert all(call.args[0] is panel for call in queued.call_args_list)
    if ok:
        queued.assert_called_with(panel, panel._apply_sections)
    else:
        queued.assert_called_with(panel, panel.set_status, "Status: Could not load stations (offline)")
