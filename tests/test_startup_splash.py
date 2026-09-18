"""Startup feedback appears before initialization and survives slow startup."""

import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from radiomaster.app import RadioMasterApp


@pytest.mark.parametrize("fails", [False, True])
def test_startup_indicator_lifetime(monkeypatch, fails):
    events = []
    splash = MagicMock()
    splash.Destroy.side_effect = lambda: events.append("destroy")

    def show():
        events.append("show")
        return splash

    def initialize():
        events.append("initialize")
        splash.Destroy.assert_not_called()
        if fails:
            raise RuntimeError("startup failed")
        return True

    monkeypatch.setattr("radiomaster.ui.splash.show_splash", show)
    monkeypatch.setattr("wx.Yield", lambda: events.append("paint"))
    window = MagicMock()
    panel = SimpleNamespace(SetAppName=MagicMock(), SetVendorName=MagicMock(),
                            _initialize=initialize, _main_window=None if fails else window)
    if fails:
        with pytest.raises(RuntimeError, match="startup failed"):
            RadioMasterApp.OnInit(panel)
    else:
        assert RadioMasterApp.OnInit(panel) is True
        window.Raise.assert_called_once()
    assert events == ["show", "paint", "initialize", "destroy"]


def test_app_import_defers_main_window():
    subprocess.run(
        [sys.executable, "-c", "import sys; import radiomaster.app; "
         "assert 'radiomaster.ui.main_window' not in sys.modules; "
         "assert 'radiomaster.services.scheduler_service' not in sys.modules"],
        check=True, capture_output=True, text=True,
    )


def test_native_splash_stays_until_destroyed():
    # Isolate wx.App ownership from the application's GUI test fixtures.
    subprocess.run([sys.executable, "-c", """
import time
import wx
from radiomaster.ui.splash import show_splash
app = wx.App(False)
window = show_splash()
wx.Yield()
message = next(child for child in window.GetChildren() if isinstance(child, wx.TextCtrl))
assert 'is starting' in message.GetValue()
assert not message.IsEditable()
assert message.HasFocus()
time.sleep(2)
wx.Yield()
assert window.IsShown()
window.Close()
wx.Yield()
assert not window.IsShown()
window.Destroy()
wx.Yield()
"""], check=True, capture_output=True, text=True)
