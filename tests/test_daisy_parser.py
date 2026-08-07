"""Tests for DAISY parser."""

import pytest
import os
import tempfile
from radiomaster.services.daisy_parser import DaisyParser


class TestDaisyParser:
    """Test DAISY format detection and parsing."""

    def test_detect_daisy2_ncc(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "ncc.html"), "w").close()
            fmt = DaisyParser.detect_format(tmp)
            assert fmt == "daisy2"

    def test_detect_daisy2_smil(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "master.smil"), "w").close()
            fmt = DaisyParser.detect_format(tmp)
            assert fmt == "daisy2"

    def test_detect_daisy3_opf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "book.opf"), "w").close()
            fmt = DaisyParser.detect_format(tmp)
            assert fmt == "daisy3"

    def test_detect_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fmt = DaisyParser.detect_format(tmp)
            assert fmt is None
