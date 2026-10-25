"""Real MediaPlayerPanel / FileTreePanel: playlists, navigation, ZIP playback."""

import os
import zipfile
from unittest.mock import MagicMock

import pytest
import wx

from radiomaster.database.connection import DatabaseManager
from radiomaster.ui.file_tree import FileTreePanel
from radiomaster.ui.media_player_panel import MediaPlayerPanel
from radiomaster.utils.config import ConfigManager


@pytest.fixture
def media(tmp_path):
    app = wx.App.Get() or wx.App(False)
    db = DatabaseManager(str(tmp_path / "data"))
    db.initialize()
    ConfigManager(str(tmp_path / "cfg"))
    engine = MagicMock()
    engine.current_url = ""
    engine.position = 0.0
    played = []
    engine.play.side_effect = lambda url, **kw: (setattr(engine, "current_url", url), played.append(url))
    frame = wx.Frame(None)
    panel = MediaPlayerPanel(frame, db, engine)
    yield panel, engine, played, tmp_path
    frame.Destroy()
    app.ProcessPendingEvents()


def test_m3u_import_navigation_and_save(media):
    panel, engine, played, tmp = media
    for n in ("a.mp3", "b.mp3", "c.mp3"):
        (tmp / n).write_bytes(b"x")
    (tmp / "list.m3u").write_text("a.mp3\nb.mp3\nc.mp3\nhttp://example.com/live\n", encoding="utf-8")
    panel._add_path(str(tmp / "list.m3u"))
    assert panel._playlist.GetItemCount() == 4
    assert panel.navigate("first").startswith("Track 1 of 4")
    assert panel.navigate("next").startswith("Track 2 of 4")
    assert panel.navigate("last").startswith("Track 4 of 4")
    assert panel.navigate("next") == "End of playlist"
    assert os.path.basename(played[0]) == "a.mp3"
    from radiomaster.utils.playlists import read_playlist, write_m3u
    out = tmp / "saved.m3u8"
    write_m3u(str(out), panel._paths)
    assert read_playlist(str(out)) == panel._paths


def test_zip_member_is_extracted_for_playback(tmp_path):
    app = wx.App.Get() or wx.App(False)
    archive = tmp_path / "pack.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("album/track1.mp3", b"audio-bytes")
        zf.writestr("album/readme.txt", b"hi")
    frame = wx.Frame(None)
    tree = FileTreePanel(frame)
    tree._add_zip_to_tree(str(archive))
    tree.Layout()

    def find(item, label):
        child, cookie = tree._tree.GetFirstChild(item)
        while child.IsOk():
            if tree._tree.GetItemText(child) == label:
                return child
            found = find(child, label)
            if found:
                return found
            child, cookie = tree._tree.GetNextChild(item, cookie)
        return None

    item = find(tree._tree.GetRootItem(), "track1.mp3")
    assert item is not None
    tree._tree.SelectItem(item)
    path = tree.get_selected_path()
    assert path and os.path.isfile(path)
    with open(path, "rb") as fh:
        assert fh.read() == b"audio-bytes"
    txt = find(tree._tree.GetRootItem(), "readme.txt")
    tree._tree.SelectItem(txt)
    assert tree.get_selected_path() is None   # non-media members are not playable
    frame.Destroy()
    app.ProcessPendingEvents()
