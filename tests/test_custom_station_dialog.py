"""The stream finder must remain usable while its network worker is blocked."""

import gc
import threading
import time
from unittest.mock import Mock, patch

import pytest
import wx

from radiomaster.services.stream_discovery import DiscoveredStream, DiscoveryResult
from radiomaster.ui.custom_station_dialog import CustomStationDialog


@pytest.fixture
def dialog():
    gc.collect()
    app = wx.App(False)
    wx.Log.SetActiveTarget(wx.LogStderr())
    dlg = CustomStationDialog(None)
    dlg.Show()
    wx.Yield()
    yield dlg
    if dlg:
        dlg.Destroy()
    wx.Yield()
    assert app


def pump_until(predicate):
    deadline = time.monotonic() + 3
    while not predicate() and time.monotonic() < deadline:
        wx.Yield()
        time.sleep(0.005)
    assert predicate()


def stream_result():
    return DiscoveryResult(
        (DiscoveredStream("https://radio.test/live", "aac", "https://radio.test/"),), 2
    )


def test_scan_completes_in_worker_and_selected_stream_can_be_used_and_saved(dialog):
    dialog.page_ctrl.SetValue("https://radio.test/")
    dialog.name_ctrl.SetValue("Test Station")
    with patch(
        "radiomaster.ui.custom_station_dialog.discover_streams", return_value=stream_result()
    ):
        dialog._on_scan(None)
        pump_until(lambda: not dialog._scanning)
    assert dialog.results.GetCount() == 1
    assert dialog.use_btn.IsEnabled()
    assert dialog.copy_btn.IsEnabled()
    assert dialog.url_ctrl.GetValue() == ""  # scanning alone does not save a webpage as audio
    dialog._on_use(None)
    assert dialog.station_values() == ("Test Station", "https://radio.test/live")
    with patch.object(dialog, "EndModal") as end:
        dialog._on_save(None)
    end.assert_called_once_with(wx.ID_OK)


def test_stop_returns_immediately_and_old_scan_cannot_replace_new_results(dialog):
    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def slow_scan(url, *, cancel):
        started.set()
        release.wait(3)
        finished.set()
        return stream_result()

    dialog.page_ctrl.SetValue("https://radio.test/")
    try:
        with patch("radiomaster.ui.custom_station_dialog.discover_streams", side_effect=slow_scan):
            dialog._on_scan(None)
            assert started.wait(1)
            generation = dialog._scan_generation
            began = time.monotonic()
            dialog._on_stop_scan(None)
            assert time.monotonic() - began < 0.5
            assert not dialog._scanning
            assert dialog._scan_cancel.is_set()
            assert dialog.scan_btn.IsEnabled()
            dialog._finish_scan(generation, stream_result())
            assert dialog.results.GetCount() == 0
    finally:
        release.set()
        assert finished.wait(2)
        wx.Yield()
    assert "stopped" in dialog.status.GetValue().lower()


def test_invalid_page_never_starts_a_scan_and_missing_stream_cannot_save(dialog):
    dialog.page_ctrl.SetValue("javascript:play()")
    with patch("radiomaster.ui.custom_station_dialog.discover_streams") as scan:
        dialog._on_scan(None)
    scan.assert_not_called()
    with patch.object(dialog, "EndModal") as end:
        dialog._on_save(None)
    end.assert_not_called()
    assert "stream URL" in dialog.status.GetValue()


def test_no_results_and_network_errors_are_visible_without_modal_error_dialogs(dialog):
    dialog._finish_scan(0, DiscoveryResult((), 1))
    assert "No accessible audio stream" in dialog.status.GetValue()
    assert not dialog.use_btn.IsEnabled()
    dialog._finish_scan(0, DiscoveryResult((), 1, error="Connection refused"))
    assert "Connection refused" in dialog.status.GetValue()


def test_copy_uses_selected_stream_without_changing_station_address(dialog):
    dialog._finish_scan(0, stream_result())
    clipboard = Mock()
    with patch("radiomaster.ui.custom_station_dialog.wx.TheClipboard", clipboard):
        dialog._on_copy(None)
    assert clipboard.SetData.call_args.args[0].GetText() == "https://radio.test/live"
    clipboard.Close.assert_called_once()
    assert dialog.url_ctrl.GetValue() == ""
    assert "copied" in dialog.status.GetValue()


def test_closing_cancels_scan_and_ignores_late_results(dialog):
    with (
        patch.object(dialog, "IsModal", return_value=True),
        patch.object(dialog, "EndModal") as end,
    ):
        dialog._on_cancel(None)
    end.assert_called_once_with(wx.ID_CANCEL)
    assert dialog._scan_cancel.is_set()
    dialog._finish_scan(0, stream_result())
    assert dialog.results.GetCount() == 0


def test_keyboard_tab_order_and_control_names(dialog):
    dialog.name_ctrl.SetFocus()
    wx.Yield()
    expected = [
        dialog.url_ctrl,
        dialog.page_ctrl,
        dialog.scan_btn,
        dialog.results,
        dialog.status,
        dialog.save_btn,
    ]
    for target in expected:
        dialog.FindFocus().Navigate(wx.NavigationKeyEvent.IsForward)
        wx.Yield()
        assert dialog.FindFocus() is target
        assert target.GetName()
