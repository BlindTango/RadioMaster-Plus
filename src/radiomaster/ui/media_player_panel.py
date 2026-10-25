"""Media Player tab panel with file tree, playlist, and playback."""

import os
import time

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
        self._next_transition_not_before: float = 0.0
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
        ctrl_sizer.Add(self._btn_clear, 0, wx.RIGHT, 4)

        self._btn_save = wx.Button(right_panel, label="Save Playlist...")
        set_accessible_name(self._btn_save, "Save Playlist")
        ctrl_sizer.Add(self._btn_save, 0)

        right_sizer.Add(ctrl_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 4)

        right_panel.SetSizer(right_sizer)
        main_sizer.Add(right_panel, 1, wx.EXPAND)

        self.SetSizer(main_sizer)

        self._btn_add.Bind(wx.EVT_BUTTON, self._on_add)
        self._btn_clear.Bind(wx.EVT_BUTTON, self._on_clear)
        self._btn_save.Bind(wx.EVT_BUTTON, self._on_save_playlist)
        self._playlist.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_play)
        self._file_tree.on_file_selected(self._add_path)

    def _on_play(self, event: wx.CommandEvent) -> None:
        """Play the selected playlist item."""
        idx = self._playlist.GetFirstSelected()
        if idx >= 0 and idx < len(self._paths):
            self._save_position()
            self._current_index = idx
            title = self._playlist.GetItemText(idx)
            artist = self._playlist.GetItemText(idx, 1)
            self._engine.play(self._paths[idx], title=title, artist=artist)

    def _on_save_playlist(self, event: wx.CommandEvent) -> None:
        """Write the visible playlist to an M3U8 file."""
        if not self._paths:
            wx.MessageBox("The playlist is empty.", "Save Playlist", wx.OK | wx.ICON_INFORMATION)
            return
        dlg = wx.FileDialog(self, "Save playlist", wildcard="M3U8 playlist (*.m3u8)|*.m3u8",
                            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            target = dlg.GetPath()
        finally:
            dlg.Destroy()
        from radiomaster.utils.playlists import write_m3u
        try:
            write_m3u(target, self._paths,
                      [self._playlist.GetItemText(i) for i in range(len(self._paths))])
        except OSError as exc:
            wx.MessageBox(f"The playlist could not be saved: {exc}", "Save Playlist",
                          wx.OK | wx.ICON_ERROR)
            return
        wx.MessageBox(f"Saved {len(self._paths)} entries to {target}.", "Save Playlist",
                      wx.OK | wx.ICON_INFORMATION)

    def navigate(self, kind: str) -> str | None:
        """Move within the playlist and play that item. Returns the message
        to announce, or None when the playlist is empty."""
        count = len(self._paths)
        if count == 0:
            return None
        cur = self._current_index if 0 <= self._current_index < count else -1
        target = {"first": 0, "last": count - 1,
                  "next": cur + 1 if cur >= 0 else 0,
                  "prev": cur - 1 if cur >= 0 else count - 1}[kind]
        if not 0 <= target < count:
            return "End of playlist" if kind == "next" else "Start of playlist"
        for i in range(count):
            self._playlist.Select(i, i == target)
        self._playlist.Focus(target)
        self._on_play(None)
        return f"Track {target + 1} of {count}: {self._playlist.GetItemText(target)}"

    def _save_position(self) -> None:
        idx = self._current_index
        if not (0 <= idx < len(self._paths)) or self._engine.current_url != self._paths[idx]:
            return
        if self._engine.state not in ("playing", "paused"):
            return
        self._db.execute(
            "INSERT INTO media_files (file_path, title, artist, last_position, duration, last_listened_at) "
            "VALUES (?, ?, ?, ?, ?, datetime('now')) ON CONFLICT(file_path) DO UPDATE SET "
            "last_position = excluded.last_position, duration = excluded.duration, "
            "last_listened_at = excluded.last_listened_at",
            (self._paths[idx], self._playlist.GetItemText(idx), self._playlist.GetItemText(idx, 1),
             self._engine.position, self._engine.duration),
        )
        self._db.commit()

    def finish_current_file(self) -> None:
        idx = self._current_index
        if 0 <= idx < len(self._paths) and self._engine.current_url == self._paths[idx]:
            self._db.execute("UPDATE media_files SET last_position = 0 WHERE file_path = ?",
                             (self._paths[idx],))
            self._db.commit()

    def resume_file(self, path: str, position: float) -> None:
        if path not in self._paths:
            self._add_path(path)
        index = self._paths.index(path)
        self._playlist.Select(index)
        self._playlist.Focus(index)
        self._on_play(wx.CommandEvent())
        self._engine.seek_when_ready(position)

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
        config = ConfigManager.get_instance()
        fade_seconds = config.get("playback.crossfade_duration", default=0)
        # Gapless and crossfade are distinct transition styles. Gapless
        # starts the next decoder immediately at natural end; crossfade is
        # initiated before natural end by try_crossfade_advance().
        gapless = config.get("playback.gapless", default=False)
        if fade_seconds and not gapless:
            self._engine.crossfade_to(self._paths[next_index], title=title, artist=artist, fade_seconds=fade_seconds)
        else:
            self._engine.play(self._paths[next_index], title=title, artist=artist)
        return True

    def try_crossfade_advance(self, position: float, duration: float) -> bool:
        """Start the next playlist item early enough for a real overlap.

        Natural-end notification is too late to crossfade: the outgoing
        decoder has already stopped. Position updates provide the advance
        notice needed to start the incoming decoder while both can play.
        Gapless mode deliberately wins over crossfade and waits for the
        natural-end path above.
        """
        if time.monotonic() < self._next_transition_not_before:
            return False
        if self._current_index < 0 or self._current_index >= len(self._paths):
            return False
        if self._engine.current_url != self._paths[self._current_index]:
            return False
        next_index = self._current_index + 1
        if next_index >= len(self._paths) or duration <= 0:
            return False
        from radiomaster.utils.config import ConfigManager
        config = ConfigManager.get_instance()
        fade_seconds = float(config.get("playback.crossfade_duration", default=0))
        if config.get("playback.gapless", default=False) or fade_seconds <= 0:
            return False
        if duration - position > fade_seconds:
            return False
        self._current_index = next_index
        title = self._playlist.GetItemText(next_index)
        artist = self._playlist.GetItemText(next_index, 1)
        actual_fade = min(fade_seconds, max(0.1, duration - position))
        # During an overlap, both decoders briefly emit position updates.
        # Ignore them until the outgoing decoder has been stopped so its
        # near-end position cannot accidentally skip another playlist item.
        self._next_transition_not_before = time.monotonic() + actual_fade + 0.5
        self._engine.crossfade_to(
            self._paths[next_index], title=title, artist=artist,
            fade_seconds=actual_fade,
        )
        return True

    def _on_add(self, event: wx.CommandEvent) -> None:
        """Add selected file from tree to playlist."""
        path = self._file_tree.get_selected_path()
        if path and os.path.isfile(path):
            self._add_path(path)

    def _add_path(self, path: str) -> None:
        """Append one media file to the visible playlist and playback path list.
        An M3U/PLS file adds every entry it lists."""
        from radiomaster.utils.playlists import is_playlist, read_playlist
        if is_playlist(path):
            entries = [e for e in read_playlist(path)
                       if "://" in e or os.path.isfile(e)]
            if not entries:
                wx.MessageBox("That playlist has no playable entries.", "Playlist",
                              wx.OK | wx.ICON_INFORMATION)
                return
            for entry in entries:
                self._add_path(entry)
            return
        name = os.path.basename(path) or path
        title, artist = ("", "") if "://" in path else self._read_tags(path)
        idx = self._playlist.InsertItem(self._playlist.GetItemCount(), title or name)
        self._playlist.SetItem(idx, 1, artist)
        self._playlist.SetItem(idx, 2, "")
        self._paths.append(path)

    def show_search_results(self, paths: list[str]) -> None:
        """Replace the playlist with files found by the global search."""
        self._on_clear(wx.CommandEvent())
        for path in paths:
            self._add_path(path)
        if paths:
            self._playlist.Select(0)

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
        self._next_transition_not_before = 0.0
