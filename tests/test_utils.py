"""Tests for utility functions."""

import os
import pytest
from radiomaster.utils.helpers import format_time, parse_time, sanitize_filename, truncate
from radiomaster.utils import paths


class TestFormatTime:
    """Test time formatting."""

    def test_zero(self) -> None:
        assert format_time(0) == "00:00:00"

    def test_seconds_only(self) -> None:
        assert format_time(45) == "00:00:45"

    def test_minutes(self) -> None:
        assert format_time(125) == "00:02:05"

    def test_hours(self) -> None:
        assert format_time(3661) == "01:01:01"

    def test_negative(self) -> None:
        assert format_time(-1) == "00:00:00"


class TestParseTime:
    """Test time parsing."""

    def test_hms(self) -> None:
        assert parse_time("01:30:45") == 5445

    def test_ms(self) -> None:
        assert parse_time("05:30") == 330

    def test_empty(self) -> None:
        assert parse_time("") == 0


class TestSanitizeFilename:
    """Test filename sanitization."""

    def test_remove_invalid_chars(self) -> None:
        assert sanitize_filename('file:name/test*') == 'file_name_test_'

    def test_keep_valid(self) -> None:
        assert sanitize_filename("valid_file.mp3") == "valid_file.mp3"


class TestTruncate:
    """Test text truncation."""

    def test_short_text(self) -> None:
        assert truncate("Hello", 10) == "Hello"

    def test_long_text(self) -> None:
        text = "This is a very long text that should be truncated"
        result = truncate(text, 20)
        assert len(result) <= 20
        assert result.endswith("...")


class TestPortablePaths:
    """Portable locations survive an application drive-letter change."""

    def test_app_path_is_stored_relative(self, monkeypatch) -> None:
        monkeypatch.setattr(paths, "_app_dir", lambda: r"F:\RadioMaster+")
        monkeypatch.setattr(paths, "is_portable_mode", lambda: True)
        stored = paths.path_for_storage(r"F:\RadioMaster+\data\downloads")
        assert stored == os.path.join(".", "data", "downloads")

    def test_external_path_remains_absolute(self, monkeypatch) -> None:
        monkeypatch.setattr(paths, "_app_dir", lambda: r"F:\RadioMaster+")
        monkeypatch.setattr(paths, "is_portable_mode", lambda: True)
        assert paths.path_for_storage(r"C:\My Music") == r"C:\My Music"

    def test_relative_path_uses_current_app_drive(self, monkeypatch) -> None:
        monkeypatch.setattr(paths, "_app_dir", lambda: r"F:\RadioMaster+")
        monkeypatch.setattr(paths, "is_portable_mode", lambda: True)
        assert paths.resolve_stored_path(r".\data\recordings") == \
            os.path.normpath(r"F:\RadioMaster+\data\recordings")

    def test_legacy_portable_path_moves_to_current_drive(self, monkeypatch) -> None:
        monkeypatch.setattr(paths, "_app_dir", lambda: r"F:\RadioMaster+")
        monkeypatch.setattr(paths, "is_portable_mode", lambda: True)
        monkeypatch.setattr(paths.os.path, "exists", lambda _path: False)
        assert paths.resolve_stored_path(r"E:\RadioMaster+\data\downloads\Podcasts") == \
            os.path.normpath(r"F:\RadioMaster+\data\downloads\Podcasts")
