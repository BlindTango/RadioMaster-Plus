"""Tests for utility functions."""

import pytest
from radiomaster.utils.helpers import format_time, parse_time, sanitize_filename, truncate


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
