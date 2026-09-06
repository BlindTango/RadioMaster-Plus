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
