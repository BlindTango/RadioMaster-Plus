"""Errors dispatched inside a modal event loop must not stack dialogs."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from radiomaster.ui.main_window import MainWindow


def test_nested_playback_error_updates_status_without_opening_second_dialog():
    window = SimpleNamespace(_status_bar=Mock(), _playback_error_visible=False, _exiting=False)

    def show(*args, **kwargs):
        assert kwargs["parent"] is window
        MainWindow._on_engine_error(window, "Second failure")

    with patch("radiomaster.ui.main_window.wx.MessageBox", side_effect=show) as dialog:
        MainWindow._on_engine_error(window, "First failure")
    dialog.assert_called_once()
    assert window._status_bar.set_status.call_count == 2
    assert not window._playback_error_visible


def test_error_dialog_guard_is_released_even_if_dialog_fails():
    window = SimpleNamespace(_status_bar=Mock(), _playback_error_visible=False, _exiting=False)
    with patch("radiomaster.ui.main_window.wx.MessageBox", side_effect=RuntimeError), \
            pytest.raises(RuntimeError):
        MainWindow._on_engine_error(window, "Failure")
    assert not window._playback_error_visible
