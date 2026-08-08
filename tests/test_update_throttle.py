"""Tests for MainWindow._update_check_due() -- the throttle that stops the
silent startup update check from running on every single launch (which
burns through GitHub's 60-req/hour unauthenticated rate limit fast).
Doesn't need a real wx.App/MainWindow: _update_check_due() only touches
self._config, so a bare, un-__init__'d instance with a stub config is
enough.
"""

import time

from radiomaster.ui.main_window import MainWindow


class _StubConfig:
    def __init__(self, days: float = 7, last_check: float = 0) -> None:
        self._values = {
            "updates.check_frequency_days": days,
            "updates.last_check_timestamp": last_check,
        }

    def get(self, key, default=None):
        return self._values.get(key, default)


def _window_with_config(config: _StubConfig) -> MainWindow:
    win = MainWindow.__new__(MainWindow)
    win._config = config
    return win


def test_due_when_never_checked() -> None:
    win = _window_with_config(_StubConfig(days=7, last_check=0))
    assert win._update_check_due() is True


def test_not_due_right_after_a_check() -> None:
    win = _window_with_config(_StubConfig(days=7, last_check=time.time()))
    assert win._update_check_due() is False


def test_due_once_the_interval_has_elapsed() -> None:
    win = _window_with_config(_StubConfig(days=7, last_check=time.time() - 8 * 86400))
    assert win._update_check_due() is True


def test_not_due_just_short_of_the_interval() -> None:
    win = _window_with_config(_StubConfig(days=7, last_check=time.time() - 6 * 86400))
    assert win._update_check_due() is False
