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


NCC = """<html><head><title>Sample Book</title>
<meta name="dc:creator" content="A. Author"/></head><body>
<h1 id="h1"><a href="c1.smil#p1">Chapter One</a></h1>
<span class="page-normal" id="pg1"><a href="c1.smil#p2">1</a></span>
<span class="page-normal" id="pg2"><a href="c1.smil#p3">2</a></span>
<h1 id="h2"><a href="c2.smil#q1">Chapter Two</a></h1>
</body></html>"""

SMIL1 = """<smil><body><seq>
<par id="p1"><text src="book.html#t1" id="x1"/><audio src="a1.mp3" clip-begin="npt=0.000s" clip-end="npt=5.000s"/></par>
<par id="p2"><text src="book.html#t2" id="x2"/><audio src="a1.mp3" clip-begin="npt=5.000s" clip-end="npt=9.500s"/></par>
<par id="p3"><text src="book.html#t3" id="x3"/><audio src="a1.mp3" clip-begin="npt=0:00:09.500" clip-end="npt=12.000s"/></par>
</seq></body></smil>"""

SMIL2 = """<smil><body><seq>
<par id="q1"><text src="book.html#t4"/><audio src="a2.mp3" clip-begin="npt=0.000s" clip-end="npt=3.000s"/></par>
</seq></body></smil>"""

CONTENT = """<html><body>
<h1 id="t1">Chapter One</h1><p id="t2">Page one text.</p><p id="t3">Page two text.</p>
<h1 id="t4">Chapter Two</h1></body></html>"""


def _make_daisy2(tmp):
    for name, body in (("ncc.html", NCC), ("c1.smil", SMIL1), ("c2.smil", SMIL2),
                       ("book.html", CONTENT)):
        with open(os.path.join(tmp, name), "w", encoding="utf-8") as fh:
            fh.write(body)
    for a in ("a1.mp3", "a2.mp3"):
        open(os.path.join(tmp, a), "wb").close()


class TestDaisyNavigation:
    def test_daisy2_chapters_point_at_audio_clips_and_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _make_daisy2(tmp)
            book = DaisyParser.parse(tmp)
            assert [c["title"] for c in book["chapters"]] == ["Chapter One", "Chapter Two"]
            one, two = book["chapters"]
            assert os.path.basename(one["audio"]) == "a1.mp3" and one["start"] == 0.0
            assert os.path.basename(two["audio"]) == "a2.mp3"
            assert "Page one text." in one["text"] and "Page two text." in one["text"]
            assert "Chapter Two" not in one["text"]
            assert book["author"] == "A. Author"
            assert one["duration"] == 12.0 and two["duration"] == 3.0

    def test_daisy2_pages_have_offsets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _make_daisy2(tmp)
            pages = DaisyParser.parse(tmp)["pages"]
            assert [p["label"] for p in pages] == ["1", "2"]
            assert pages[0]["start"] == 5.0
            assert pages[1]["start"] == 9.5
            assert os.path.basename(pages[1]["audio"]) == "a1.mp3"

    def test_daisy3_ncx_chapters_and_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            files = {
                "book.opf": ('<package xmlns="http://www.idpf.org/2007/opf"><metadata>'
                             '<dc:title xmlns:dc="http://purl.org/dc/elements/1.1/">Three</dc:title>'
                             '</metadata><manifest><item id="n" href="book.ncx" '
                             'media-type="application/x-dtbncx+xml"/></manifest></package>'),
                "book.ncx": ('<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"><navMap>'
                             '<navPoint id="a"><navLabel><text>Intro</text></navLabel>'
                             '<content src="s.smil#p1"/>'
                             '<navPoint id="b"><navLabel><text>Sub</text></navLabel>'
                             '<content src="s.smil#p2"/></navPoint></navPoint></navMap>'
                             '<pageList><pageTarget value="7"><navLabel><text>7</text></navLabel>'
                             '<content src="s.smil#p2"/></pageTarget></pageList></ncx>'),
                "s.smil": ('<smil xmlns="http://www.w3.org/2001/SMIL20/"><body><seq>'
                           '<par id="p1"><text src="b.xml#d1"/><audio src="x.mp3" clipBegin="npt=1s" clipEnd="npt=2s"/></par>'
                           '<par id="p2"><text src="b.xml#d2"/><audio src="x.mp3" clipBegin="npt=2s" clipEnd="npt=4s"/></par>'
                           '</seq></body></smil>'),
                "b.xml": '<dtbook><book><p id="d1">First para.</p><p id="d2">Second para.</p></book></dtbook>',
            }
            for name, body in files.items():
                with open(os.path.join(tmp, name), "w", encoding="utf-8") as fh:
                    fh.write(body)
            open(os.path.join(tmp, "x.mp3"), "wb").close()
            book = DaisyParser.parse(tmp)
            assert [(c["title"], c["level"]) for c in book["chapters"]] == [("Intro", 1), ("Sub", 2)]
            assert book["chapters"][1]["start"] == 2.0
            assert "First para." in book["chapters"][0]["text"]
            assert book["pages"][0]["label"] == "7" and book["pages"][0]["start"] == 2.0

    def test_clock_formats(self) -> None:
        from radiomaster.services.daisy_parser import parse_clock
        assert parse_clock("npt=12.5s") == 12.5
        assert parse_clock("npt=0:01:02.500") == 62.5
        assert parse_clock("1500ms") == 1.5
        assert parse_clock("junk") is None
