"""Media Player tab panel with file tree, playlist, and playback."""

import os

import wx

from radiomaster.database.connection import DatabaseManager
from radiomaster.engine.playback_engine import PlaybackEngine
from radiomaster.ui.file_tree import FileTreePanel
from radiomaster.utils.accessibility import set_accessible_name


class MediaPlayerPanel(wx.Panel):
    """Panel for browsing and playing local media files."""

    MEDIA_EXTENSIONS = {
        ".mp3", ".flac", ".ogg", ".wav", ".aac", ".m4a", ".wma", ".opus",
        ".mp4", ".mkv", ".avi", ".webm", ".mov", ".m4b",
    }

    def __init__(self, parent: wx.Window, db: DatabaseManager, engine: PlaybackEngine) -> None:
        super().__init__(parent)
        self._db = db
        self._engine = engine
        self._paths: list[str] = []
        self._current_index: int = -1
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Create the media player panel layout."""
        main_sizer = wx.BoxSizer(wx.HORIZONTAL)

        # Left: File tree
        self._file_tree = FileTreePanel(self)
        main_sizer.Add(self._file_tree, 0, wx.EXPAND | wx.RIGHT, 4)

        # Right: Playlist and controls
        right_panel = wx.Panel(self)
        right_sizer = wx.BoxSizer(wx.VERTICAL)

        right_sizer.Add(wx.StaticText(right_panel, label="Playlist"), 0, wx.ALL, 4)

        self._playlist = wx.ListCtrl(right_panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        set_accessible_name(self._playlist, "Playlist")
        self._playlist.AppendColumn("Title", width=250)
        self._playlist.AppendColumn("Artist", width=150)
        self._playlist.AppendColumn("Duration", width=70)
        right_sizer.Add(self._playlist, 1, wx.EXPAND | wx.ALL, 4)

        # Controls
        ctrl_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self._btn_add = wx.Button(right_panel, label="Add to Playlist")
        set_accessible_name(self._btn_add, "Add to Playlist")
        ctrl_sizer.Add(self._btn_add, 0, wx.RIGHT, 4)

        self._btn_clear = wx.Button(right_panel, label="Clear")
        set_accessible_name(self._btn_clear, "Clear Playlist")
        ctrl_sizer.Add(self._btn_clear, 0)

        right_sizer.Add(ctrl_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 4)

        right_panel.SetSizer(right_sizer)
        main_sizer.Add(right_panel, 1, wx.EXPAND)

        self.SetSizer(main_sizer)

        self._btn_add.Bind(wx.EVT_BUTTON, self._on_add)
        self._btn_clear.Bind(wx.EVT_BUTTON, self._on_clear)
        self._playlist.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_play)
        self._file_tree.on_file_selected(self._add_path)

    def _on_play(self, event: wx.CommandEvent) -> None:
        """Play the selected playlist item."""
        idx = self._playlist.GetFirstSelected()
        if idx >= 0 and idx < len(self._paths):
            self._current_index = idx
            title = self._playlist.GetItemText(idx)
            artist = self._playlist.GetItemText(idx, 1)
            self._engine.play(self._paths[idx], title=title, artist=artist)

    def try_auto_advance(self) -> bool:
        """Called when the engine reports a track finished naturally. If
        the track that just finished was this panel's current playlist
        item and there's a next one, crossfade into it and return True.
        Returns False if this panel has nothing to advance (not the
        active source, or already at the end of the playlist) so the
        caller can leave playback stopped instead."""
        if self._current_index < 0 or self._current_index >= len(self._paths):
            return False
        # Guard against a stray natural-end notification for a track this
        # panel isn't actually the source of (e.g. the user switched to
        # Radio and a station happened to end) -- only advance if the
        # engine's current URL still matches what we last played.
        if self._engine.current_url != self._paths[self._current_index]:
            return False
        next_index = self._current_index + 1
        if next_index >= len(self._paths):
            self._current_index = -1
            return False
        self._current_index = next_index
        title = self._playlist.GetItemText(next_index)
        artist = self._playlist.GetItemText(next_index, 1)
        from radiomaster.utils.config import ConfigManager
        fade_seconds = ConfigManager.get_instance().get("playback.crossfade_duration", default=0)
        if fade_seconds:
            self._engine.crossfade_to(self._paths[next_index], title=title, artist=artist, fade_seconds=fade_seconds)
        else:
            self._engine.play(self._paths[next_index], title=title, artist=artist)
        return True

    def _on_add(self, event: wx.CommandEvent) -> None:
        """Add selected file from tree to playlist."""
        path = self._file_tree.get_selected_path()
        if path and os.path.isfile(path):
            self._add_path(path)

    def _add_path(self, path: str) -> None:
        """Append one media file to the visible playlist and playback path list."""
        name = os.path.basename(path)
        title, artist = self._read_tags(path)
        idx = self._playlist.InsertItem(self._playlist.GetItemCount(), title or name)
        self._playlist.SetItem(idx, 1, artist)
        self._playlist.SetItem(idx, 2, "")
        self._paths.append(path)

    def load_folder(self, path: str) -> int:
        """Replace the playlist with supported media files from a folder tree."""
        media_paths = sorted(
            (
                os.path.join(root, filename)
                for root, _dirs, files in os.walk(path)
                for filename in files
                if os.path.splitext(filename)[1].lower() in self.MEDIA_EXTENSIONS
            ),
            key=str.casefold,
        )
        self._on_clear(wx.CommandEvent())
        for media_path in media_paths:
            self._add_path(media_path)
        if media_paths:
            self._playlist.Select(0)
            self._playlist.SetFocus()
        return len(media_paths)

    @staticmethod
    def _read_tags(path: str) -> tuple[str, str]:
        """Read Title/Artist tags via mutagen, if the file has any.

        Previously the playlist's Artist column was always left blank and
        engine.play() was never given an artist at all -- harmless for
        playback itself, but it meant lyrics lookups for local files had
        no artist to search with and could never match anything.
        """
        try:
            import mutagen
            audio = mutagen.File(path, easy=True)
            if audio is None:
                return "", ""
            title = (audio.get("title") or [""])[0]
            artist = (audio.get("artist") or [""])[0]
            return title.strip(), artist.strip()
        except Exception:
            return "", ""

    def _on_clear(self, event: wx.CommandEvent) -> None:
        """Clear the playlist."""
        self._playlist.DeleteAllItems()
        self._paths.clear()
        self._current_index = -1
