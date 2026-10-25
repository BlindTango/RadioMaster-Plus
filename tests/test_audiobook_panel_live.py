"""Real AudiobookPanel (real wx widgets, real database) driven through a
synthetic DAISY book: chapter/page navigation, bookmarks, TTS highlighting."""

import json
import os
from unittest.mock import MagicMock

import pytest
import wx

from radiomaster.database.connection import DatabaseManager
from radiomaster.services.daisy_parser import DaisyParser
from radiomaster.ui.audiobook_panel import AudiobookPanel
from radiomaster.utils.config import ConfigManager

NCC = """<html><head><title>Live Book</title></head><body>
<h1><a href="c1.smil#a">One</a></h1>
<span class="page-normal"><a href="c1.smil#b">1</a></span>
<span class="page-normal"><a href="c1.smil#c">2</a></span>
<h1><a href="c2.smil#d">Two</a></h1></body></html>"""
SMIL1 = """<smil><body><seq>
<par id="a"><text src="t.html#t1"/><audio src="one.mp3" clip-begin="npt=0s" clip-end="npt=4s"/></par>
<par id="b"><text src="t.html#t2"/><audio src="one.mp3" clip-begin="npt=4s" clip-end="npt=8s"/></par>
<par id="c"><text src="t.html#t3"/><audio src="one.mp3" clip-begin="npt=8s" clip-end="npt=12s"/></par>
</seq></body></smil>"""
SMIL2 = """<smil><body><seq><par id="d"><text src="t.html#t4"/><audio src="two.mp3" clip-begin="npt=0s" clip-end="npt=5s"/></par></seq></body></smil>"""
TEXT = ('<html><body><h1 id="t1">One.</h1><p id="t2">First sentence. Second sentence!</p>'
        '<p id="t3">Third.</p><h1 id="t4">Two.</h1></body></html>')


@pytest.fixture
def live(tmp_path):
    app = wx.App.Get() or wx.App(False)
    book_dir = tmp_path / "book"
    book_dir.mkdir()
    for name, body in (("ncc.html", NCC), ("c1.smil", SMIL1), ("c2.smil", SMIL2), ("t.html", TEXT)):
        (book_dir / name).write_text(body, encoding="utf-8")
    for a in ("one.mp3", "two.mp3"):
        (book_dir / a).write_bytes(b"")
    db = DatabaseManager(str(tmp_path / "data"))
    db.initialize()
    ConfigManager(str(tmp_path / "cfg"))
    engine = MagicMock()
    engine.position = 0.0
    engine.current_url = ""
    played = []
    engine.play.side_effect = lambda url, **kw: (setattr(engine, "current_url", url), played.append(url))
    frame = wx.Frame(None)
    panel = AudiobookPanel(frame, db, engine)
    messages = []
    panel.on_status = messages.append
    book = DaisyParser.parse(str(book_dir))
    panel._current_path = str(book_dir)
    panel._current_book = book
    for i, ch in enumerate(book["chapters"]):
        idx = panel._chapter_list.InsertItem(i, ch["title"])
        panel._chapter_list.SetItemData(idx, i)
    yield panel, engine, played, messages, str(book_dir)
    frame.Destroy()
    app.ProcessPendingEvents()


def test_chapter_navigation_plays_each_chapters_own_audio(live):
    panel, engine, played, messages, d = live
    assert panel.navigate("first").startswith("Chapter 1 of 2")
    assert os.path.basename(played[-1]) == "one.mp3"
    assert panel.navigate("next").startswith("Chapter 2 of 2")
    assert os.path.basename(played[-1]) == "two.mp3"
    assert panel.navigate("next") == "Last chapter"


def test_page_commands_seek_inside_the_chapter_audio(live):
    panel, engine, played, messages, d = live
    assert panel.go_to_page("2") == "Page 2"
    assert os.path.basename(played[-1]) == "one.mp3"
    engine.seek_when_ready.assert_called_with(8.0)
    engine.position = 8.5
    assert panel.navigate_page(-1) == "Page 1"
    engine.seek_when_ready.assert_called_with(4.0)


def test_chapter_text_is_shown_and_highlight_follows_sentences(live):
    panel, engine, played, messages, d = live
    panel._chapter_list.Select(0)
    panel._show_chapter_text(panel._current_book["chapters"][0]["text"])
    shown = panel._text_view.GetValue()
    assert "First sentence." in shown
    panel._sentences = panel._split_sentences(shown)
    panel._highlight_sentence(1)   # must not raise on the real rich text control
    panel._clear_highlight()


def test_bookmark_round_trip_goes_to_saved_chapter_and_position(live):
    panel, engine, played, messages, d = live
    panel._chapter_list.Select(1)
    engine.position = 3.5
    import radiomaster.ui.audiobook_panel as mod
    mod.wx.MessageBox = lambda *a, **k: wx.OK
    panel._on_bookmark(None)
    from radiomaster.database.repository import BookmarkRepository
    marks = BookmarkRepository(panel._db).get_all("audiobook")
    assert json.loads(marks[0]["notes"]) == {"chapter": 1}
    panel._chapter_list.Select(1, False)
    panel._go_to_bookmark(marks[0])
    assert os.path.basename(played[-1]) == "two.mp3"
    engine.seek_when_ready.assert_called_with(3.5)


def test_chapter_end_advances_to_next_chapter(live):
    panel, engine, played, messages, d = live
    panel.navigate("first")
    assert panel.try_auto_advance() is True
    assert os.path.basename(played[-1]) == "two.mp3"
    assert panel.try_auto_advance() is False
