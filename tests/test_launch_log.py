"""Tests for the pre-logging launch recorder (utils/launch_log.py)."""

import os
import sys
from unittest import mock

import pytest

from radiomaster.utils import launch_log


@pytest.fixture(autouse=True)
def reset_state():
    yield
    launch_log._LINES.clear()
    launch_log._PATH = None


def test_start_is_idempotent(tmp_path):
    with mock.patch.object(launch_log, "_resolve_log_path", return_value=str(tmp_path / "launch.log")):
        launch_log.start()
        first = launch_log.path()
        launch_log.start()
        assert launch_log.path() == first


def test_record_writes_to_disk(tmp_path):
    log_path = tmp_path / "launch.log"
    with mock.patch.object(launch_log, "_resolve_log_path", return_value=str(log_path)):
        launch_log.start()
        launch_log.record("hello")
    assert log_path.exists()
    content = log_path.read_text(encoding="utf-8")
    assert "hello" in content


def test_record_survives_unwritable_path(tmp_path):
    # A path whose parent is a *file* cannot be created -- record() must
    # keep buffering in memory rather than crash (the disk being the
    # problem is exactly when the log matters most).
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    with mock.patch.object(launch_log, "_resolve_log_path",
                           return_value=str(blocker / "sub" / "launch.log")):
        launch_log.start()
        launch_log.record("still here")
    assert any("still here" in line for line in launch_log.recent_lines())


def test_record_exception_captures_traceback(tmp_path):
    with mock.patch.object(launch_log, "_resolve_log_path", return_value=str(tmp_path / "launch.log")):
        launch_log.start()
        try:
            raise ValueError("boom")
        except ValueError as exc:
            launch_log.record_exception(exc)
    content = (tmp_path / "launch.log").read_text(encoding="utf-8")
    assert "ValueError: boom" in content
    assert "test_record_exception_captures_traceback" in content


def test_classify_missing_file():
    exc = FileNotFoundError("no such file: bass.dll")
    assert "missing" in launch_log.classify_failure(exc)
    assert "reinstall" in launch_log.classify_failure(exc).lower()


def test_classify_dll_load():
    exc = OSError("LoadLibrary: the specified module could not be found")
    assert "could not be loaded" in launch_log.classify_failure(exc)


def test_classify_access_denied():
    exc = PermissionError("access is denied")
    assert "refused access" in launch_log.classify_failure(exc)


def test_classify_database():
    exc = RuntimeError("sqlite3.OperationalError: database is locked")
    assert "database" in launch_log.classify_failure(exc)


def test_classify_generic_quotes_message():
    exc = RuntimeError("startup failed")
    reason = launch_log.classify_failure(exc)
    assert "startup failed" in reason
    assert "launch log" in reason


def test_classify_generic_without_message():
    reason = launch_log.classify_failure(RuntimeError())
    assert "RuntimeError" in reason
    assert "launch log" in reason


def test_check_bundle_ignored_for_source_runs():
    # Not frozen -> no-op, never raises.
    with mock.patch.object(sys, "frozen", False, create=True):
        launch_log.check_bundle()


def test_check_bundle_raises_for_missing_internal(tmp_path):
    exe = tmp_path / "RadioMaster+.exe"
    exe.write_text("stub")
    with mock.patch.object(sys, "frozen", True, create=True), \
            mock.patch.object(sys, "executable", str(exe), create=True):
        with pytest.raises(launch_log.BundleIncompleteError):
            launch_log.check_bundle()


def test_check_bundle_passes_with_python_dll(tmp_path):
    exe = tmp_path / "RadioMaster+.exe"
    exe.write_text("stub")
    internal = tmp_path / "_internal"
    internal.mkdir()
    (internal / "python312.dll").write_text("dll")
    with mock.patch.object(sys, "frozen", True, create=True), \
            mock.patch.object(sys, "executable", str(exe), create=True):
        launch_log.check_bundle()  # must not raise


def test_check_bundle_raises_without_python_dll(tmp_path):
    exe = tmp_path / "RadioMaster+.exe"
    exe.write_text("stub")
    internal = tmp_path / "_internal"
    internal.mkdir()
    (internal / "something.txt").write_text("x")
    with mock.patch.object(sys, "frozen", True, create=True), \
            mock.patch.object(sys, "executable", str(exe), create=True):
        with pytest.raises(launch_log.BundleIncompleteError):
            launch_log.check_bundle()