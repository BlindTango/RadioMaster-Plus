"""Media Player tab panel with file tree, playlist, and playback."""

import wx
from typing import Any
from radiomaster.database.connection import DatabaseManager
from radiomaster.engine.playback_engine import PlaybackEngine
from radiomaster.ui.file_tree import FileTreePanel
from radiomaster.utils.accessibility import set_accessible_name


class MediaPlayerPanel(wx.Panel):
    """Panel for browsing and playing local media files."""

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
        self._btn_play = wx.Button(right_panel, label="Play")
        set_accessible_name(self._btn_play, "Play")
        ctrl_sizer.Add(self._btn_play, 0, wx.RIGHT, 4)

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

        self._btn_play.Bind(wx.EVT_BUTTON, self._on_play)
        self._btn_add.Bind(wx.EVT_BUTTON, self._on_add)
        self._btn_clear.Bind(wx.EVT_BUTTON, self._on_clear)

    def _on_play(self, event: wx.CommandEvent) -> None:
        """Play the selected playlist item."""
        idx = self._playlist.GetFirstSelected()
        if idx >= 0 and idx < len(self._paths):
            self._current_index = idx
            title = self._playlist.GetItemText(idx)
            self._engine.play(self._paths[idx], title=title)

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
        from radiomaster.utils.config import ConfigManager
        fade_seconds = ConfigManager.get_instance().get("playback.crossfade_duration", default=0)
        if fade_seconds:
            self._engine.crossfade_to(self._paths[next_index], title=title, fade_seconds=fade_seconds)
        else:
            self._engine.play(self._paths[next_index], title=title)
        return True

    def _on_add(self, event: wx.CommandEvent) -> None:
        """Add selected file from tree to playlist."""
        path = self._file_tree.get_selected_path()
        if path:
            import os
            name = os.path.basename(path)
            idx = self._playlist.InsertItem(self._playlist.GetItemCount(), name)
            self._playlist.SetItem(idx, 1, "")
            self._playlist.SetItem(idx, 2, "")
            self._paths.insert(idx, path)

    def _on_clear(self, event: wx.CommandEvent) -> None:
        """Clear the playlist."""
        self._playlist.DeleteAllItems()
        self._paths.clear()
