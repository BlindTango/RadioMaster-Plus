"""Station format fallback, stale-result handling, and accessible status."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
import wx

from radiomaster.ui.radio_panel import RadioPanel
from radiomaster.ui.status_bar import StatusBar


@pytest.mark.parametrize("reported,detected,expected", [
    ("MP3, 128 kbps (station reported)", "", None),
    ("", "", "Stream format unavailable"),
    ("MP3, 128 kbps (station reported)", "AAC, 44.1 kHz, Stereo, 192 kbps",
     "AAC, 44.1 kHz, Stereo, 192 kbps"),
])
def test_format_result_preserves_reported_fallback(reported, detected, expected):
    panel = SimpleNamespace(_now_playing_generation=2,
                            _reported_stream_format=reported, on_format_detected=Mock())
    RadioPanel._report_stream_format(panel, detected, 2)
    if expected is None:
        panel.on_format_detected.assert_not_called()
    else:
        panel.on_format_detected.assert_called_once_with(expected)


def test_queued_format_from_previous_station_is_ignored():
    panel = SimpleNamespace(_now_playing_generation=3, on_format_detected=Mock())
    RadioPanel._report_stream_format(panel, "MP3, 128 kbps", 2)
    panel.on_format_detected.assert_not_called()


def test_screen_reader_can_read_all_fields_without_automatic_announcements():
    app = wx.App.Get() or wx.App(False)
    frame = wx.Frame(None)
    bar = StatusBar(frame)
    try:
        with patch.object(wx.Accessible, "NotifyEvent") as notify:
            bar.set_status("Playing")
            bar.set_source("Radio")
            bar.set_format("AAC, 44.1 kHz, Stereo, 192 kbps")
            bar.set_time_info(30, 0)
        status, name = bar._accessible.GetName(0)
        assert status == wx.ACC_OK
        assert "AAC, 44.1 kHz, Stereo, 192 kbps" in name
        assert "Elapsed 0:30" in name
        assert "Radio" in name
        notify.assert_not_called()
    finally:
        frame.Destroy()
        app.ProcessPendingEvents()


def test_status_burst_is_coalesced_and_progress_and_disable_cancel_pending():
    app = wx.App.Get() or wx.App(False)
    frame = wx.Frame(None)
    bar = StatusBar(frame)
    try:
        with patch.object(wx.Accessible, "NotifyEvent") as notify:
            bar.set_screen_reader_announcements(True)
            for index in range(100):
                bar.set_status(f"Connecting {index}")
            notify.assert_not_called()
            assert bar._announcement_timer.IsRunning()
            bar._announce_status()
            notify.assert_called_once_with(
                wx.ACC_EVENT_OBJECT_NAMECHANGE, bar, wx.OBJID_CLIENT, 1
            )
            bar.set_status("Download 10%", False)
            assert not bar._announcement_timer.IsRunning()
            bar.set_status("Starting download")
            bar.set_status("Download 20%", False)
            assert not bar._announcement_timer.IsRunning()
            bar.set_status("Finished")
            bar.set_screen_reader_announcements(False)
            assert not bar._announcement_timer.IsRunning()
            bar._announce_status()
            assert notify.call_count == 1
        assert bar._accessible.GetChildCount() == (wx.ACC_OK, 5)
        assert bar._accessible.GetRole(0) == (wx.ACC_OK, wx.ROLE_SYSTEM_STATUSBAR)
        assert bar._accessible.GetName(1) == (wx.ACC_OK, "Finished")
    finally:
        frame.Destroy()
        app.ProcessPendingEvents()


@pytest.mark.skipif(__import__("sys").platform != "win32", reason="Windows MSAA event regression")
def test_live_status_fields_do_not_emit_native_name_changes():
    import subprocess
    import sys
    from pathlib import Path

    probe = Path(__file__).with_name("status_event_probe.py")
    result = subprocess.run([sys.executable, str(probe)], capture_output=True,
                            text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
