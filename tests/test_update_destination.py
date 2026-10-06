"""Updates must follow the running copy rather than a registry installation."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from radiomaster.services.update_checker import installer_command
from radiomaster.ui.main_window import MainWindow
from radiomaster.utils import paths


@pytest.mark.parametrize("portable", [True, False])
def test_update_targets_running_executable(monkeypatch, portable):
    monkeypatch.setattr(paths.sys, "frozen", True, raising=False)
    monkeypatch.setattr(paths.sys, "executable", r"F:\Radio Master+\RadioMaster+.exe")
    monkeypatch.setattr(paths, "is_portable_mode", lambda: portable)
    assert installer_command(r"C:\Temp\Setup.exe") == [
        r"C:\Temp\Setup.exe", r"/DIR=F:\Radio Master+",
        f"/PORTABLE={int(portable)}",
    ]


def test_install_launch_passes_destination_before_exit(monkeypatch):
    command = ["setup.exe", r"/DIR=F:\RadioMaster+", "/PORTABLE=1"]
    monkeypatch.setattr("radiomaster.services.update_checker.installer_command",
                        lambda path: command)
    launch = Mock()
    monkeypatch.setattr("subprocess.Popen", launch)
    window = SimpleNamespace(request_exit=Mock())
    MainWindow._on_ready_to_install(window, "setup.exe")
    launch.assert_called_once_with(command)
    window.request_exit.assert_called_once_with()


def test_failed_installer_launch_keeps_app_open(monkeypatch):
    monkeypatch.setattr("radiomaster.services.update_checker.installer_command",
                        lambda path: [path])
    monkeypatch.setattr("subprocess.Popen", Mock(side_effect=OSError("blocked")))
    monkeypatch.setattr("radiomaster.ui.main_window.wx.MessageBox", Mock())
    window = SimpleNamespace(request_exit=Mock())
    MainWindow._on_ready_to_install(window, "setup.exe")
    window.request_exit.assert_not_called()
