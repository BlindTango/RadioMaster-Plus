"""Audiobook tab panel with DAISY support, chapter navigation, and SAPI TTS."""

import os
from typing import Any

import wx

from radiomaster.database.connection import DatabaseManager
from radiomaster.engine.playback_engine import PlaybackEngine
from radiomaster.services.daisy_parser import DaisyParser
from radiomaster.utils.accessibility import set_accessible_name


class AudiobookPanel(wx.Panel):
    """Panel for browsing and playing audiobooks including DAISY format."""

    AUDIO_EXTENSIONS = (
        ".m4b", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wav", ".wma",
    )

    def __init__(self, parent: wx.Window, db: DatabaseManager, engine: PlaybackEngine) -> None:
        super().__init__(parent)
        self._db = db
        self._engine = engine
        self._current_book: dict[str, Any] | None = None
        self._current_path: str | None = None
        self._current_book_id: int | None = None
        self._resume_position: float = 0.0
        self._setup_ui()

        # Periodically persist playback position for the loaded book so
        # "resume from last position" survives switching chapters/books,
        # closing the app, etc. -- self-contained, no engine callback wiring
        # needed from MainWindow.
        self._position_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_position_timer, self._position_timer)
        self._position_timer.Start(15000)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)

    def _on_destroy(self, event: wx.WindowDestroyEvent) -> None:
        if event.GetEventObject() is self:
            self._save_position()
        event.Skip()

    def _on_position_timer(self, event: wx.TimerEvent) -> None:
        self._save_position()

    def _save_position(self) -> None:
        if self._current_book_id is not None and self._engine.state in ("playing", "paused"):
            from radiomaster.database.repository import AudiobookRepository
            AudiobookRepository(self._db).update_position(
                self._current_book_id, self._engine.position
            )

    def _setup_ui(self) -> None:
        """Create the audiobook panel layout."""
        main_sizer = wx.BoxSizer(wx.HORIZONTAL)

        # Left: Library tree
        left_panel = wx.Panel(self)
        left_sizer = wx.BoxSizer(wx.VERTICAL)

        left_sizer.Add(wx.StaticText(left_panel, label="Library"), 0, wx.ALL, 4)

        self._library_tree = wx.TreeCtrl(left_panel, style=wx.TR_DEFAULT_STYLE | wx.TR_HIDE_ROOT)
        set_accessible_name(self._library_tree, "Audiobook Library")
        root = self._library_tree.AddRoot("Audiobooks")
        child = self._library_tree.AppendItem(root, "📁 My Audiobooks")
        self._library_tree.Expand(child)
        left_sizer.Add(self._library_tree, 1, wx.EXPAND | wx.ALL, 4)

        self._btn_browse = wx.Button(left_panel, label="Browse Folder...")
        set_accessible_name(self._btn_browse, "Browse Audiobook Folder")
        left_sizer.Add(self._btn_browse, 0, wx.EXPAND | wx.ALL, 4)

        self._btn_browse_file = wx.Button(left_panel, label="Browse File...")
        set_accessible_name(self._btn_browse_file, "Browse Audiobook File")
        left_sizer.Add(self._btn_browse_file, 0, wx.EXPAND | wx.ALL, 4)

        left_panel.SetSizer(left_sizer)
        main_sizer.Add(left_panel, 0, wx.EXPAND | wx.RIGHT, 4)

        # Right: Book info and chapters
        right_panel = wx.Panel(self)
        right_sizer = wx.BoxSizer(wx.VERTICAL)

        # Book info
        info_sizer = wx.BoxSizer(wx.HORIZONTAL)
        info_sizer.Add(wx.StaticText(right_panel, label="Title:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._title_text = wx.TextCtrl(right_panel, style=wx.TE_READONLY, size=(200, -1))
        set_accessible_name(self._title_text, "Book Title")
        info_sizer.Add(self._title_text, 1, wx.LEFT, 4)
        right_sizer.Add(info_sizer, 0, wx.EXPAND | wx.ALL, 4)

        # Chapter list
        right_sizer.Add(wx.StaticText(right_panel, label="Chapters"), 0, wx.LEFT | wx.RIGHT, 4)
        self._chapter_list = wx.ListCtrl(right_panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        set_accessible_name(self._chapter_list, "Chapter List")
        self._chapter_list.AppendColumn("Chapter", width=250)
        self._chapter_list.AppendColumn("Duration", width=80)
        right_sizer.Add(self._chapter_list, 1, wx.EXPAND | wx.ALL, 4)

        # Controls
        ctrl_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self._btn_tts = wx.Button(right_panel, label="Read with TTS")
        set_accessible_name(self._btn_tts, "Read with Text to Speech")
        ctrl_sizer.Add(self._btn_tts, 0, wx.RIGHT, 4)

        self._btn_bookmark = wx.Button(right_panel, label="Add Bookmark")
        set_accessible_name(self._btn_bookmark, "Add Bookmark")
        ctrl_sizer.Add(self._btn_bookmark, 0)

        right_sizer.Add(ctrl_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 4)

        right_panel.SetSizer(right_sizer)
        main_sizer.Add(right_panel, 1, wx.EXPAND)

        self.SetSizer(main_sizer)

        self._btn_browse.Bind(wx.EVT_BUTTON, self._on_browse)
        self._btn_browse_file.Bind(wx.EVT_BUTTON, self._on_browse_file)
        self._btn_tts.Bind(wx.EVT_BUTTON, self._on_tts)
        self._btn_bookmark.Bind(wx.EVT_BUTTON, self._on_bookmark)
        self._chapter_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_chapter_selected)
        self._chapter_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_play)
        self._library_tree.Bind(wx.EVT_TREE_SEL_CHANGED, self._on_tree_sel_changed)

    def _on_browse(self, event: wx.CommandEvent) -> None:
        """Browse for an audiobook folder."""
        dlg = wx.DirDialog(self, "Select audiobook folder")
        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            self._current_path = path
            
            # Parse DAISY book
            book = DaisyParser.parse(path)
            
            if book:
                self._current_book = book
                self._title_text.SetValue(book.get('title', os.path.basename(path)))
                
                # Populate chapter list
                self._chapter_list.DeleteAllItems()
                chapters = book.get('chapters', [])
                
                if chapters:
                    for i, chapter in enumerate(chapters):
                        idx = self._chapter_list.InsertItem(i, chapter.get('title', f'Chapter {i+1}'))
                        self._chapter_list.SetItem(idx, 1, '')  # Duration if available
                        self._chapter_list.SetItemData(idx, i)
                    
                    wx.MessageBox(
                        f"DAISY book loaded: {len(chapters)} chapters found.\n\n"
                        f"Format: {book.get('format', 'Unknown')}\n"
                        f"Audio files: {len(book.get('audio_files', []))}",
                        "DAISY Book Loaded",
                        wx.OK | wx.ICON_INFORMATION,
                    )
                else:
                    # No chapters found, use audio files
                    audio_files = book.get('audio_files', [])
                    for i, audio_file in enumerate(audio_files):
                        idx = self._chapter_list.InsertItem(i, os.path.basename(audio_file))
                        self._chapter_list.SetItem(idx, 1, '')
                        self._chapter_list.SetItemData(idx, i)
                    
                    self._title_text.SetValue(book.get('title', os.path.basename(path)))
            else:
                # Not a DAISY book, treat as regular folder
                self._current_book = None
                self._title_text.SetValue(os.path.basename(path))
                
                # List audio files
                self._chapter_list.DeleteAllItems()
                audio_files = [
                    filename for filename in os.listdir(path)
                    if filename.lower().endswith(self.AUDIO_EXTENSIONS)
                ]
                
                for i, audio_file in enumerate(sorted(audio_files)):
                    idx = self._chapter_list.InsertItem(i, audio_file)
                    self._chapter_list.SetItem(idx, 1, '')
                    self._chapter_list.SetItemData(idx, i)

            self._register_book(path, self._title_text.GetValue())

        dlg.Destroy()

    def _on_browse_file(self, event: wx.CommandEvent) -> None:
        """Choose one audiobook media file and show it in the chapter list."""
        wildcard = (
            "Audiobook and audio files|*.m4b;*.mp3;*.m4a;*.aac;*.flac;*.ogg;*.opus;"
            "*.wav;*.wma|All files|*.*"
        )
        dlg = wx.FileDialog(
            self,
            "Select audiobook file",
            wildcard=wildcard,
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        )
        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            title = os.path.splitext(os.path.basename(path))[0]
            self._current_path = path
            self._current_book = None
            self._title_text.SetValue(title)
            self._chapter_list.DeleteAllItems()
            item = self._chapter_list.InsertItem(0, os.path.basename(path))
            self._chapter_list.SetItem(item, 1, "")
            self._chapter_list.SetItemData(item, 0)
            self._chapter_list.Select(item)
            self._register_book(path, title)
            self._chapter_list.SetFocus()
        dlg.Destroy()

    def _register_book(self, path: str, title: str) -> None:
        """Look up or create this book's row in the audiobooks table, and
        offer to resume if it was previously played partway through."""
        from radiomaster.database.repository import AudiobookRepository
        repo = AudiobookRepository(self._db)
        existing = next((b for b in repo.get_all() if b.get("folder_path") == path), None)
        if existing:
            self._current_book_id = existing["id"]
            last_position = existing.get("last_position") or 0.0
            if last_position > 0:
                from radiomaster.utils.helpers import format_time
                if wx.MessageBox(
                    f"Resume '{title}' from {format_time(last_position)}?",
                    "Resume Playback", wx.YES_NO | wx.ICON_QUESTION,
                ) == wx.YES:
                    self._resume_position = last_position
        else:
            self._current_book_id = repo.add(title=title, folder_path=path, is_daisy=1 if self._current_book else 0)
            self._resume_position = 0.0

    def _on_play(self, event: wx.CommandEvent) -> None:
        """Play the selected audiobook chapter."""
        if not self._current_path:
            wx.MessageBox("Please select an audiobook first.", "No Book Selected",
                         wx.OK | wx.ICON_WARNING)
            return
        
        idx = self._chapter_list.GetFirstSelected()
        if idx < 0:
            wx.MessageBox("Please select a chapter to play.", "No Chapter Selected",
                         wx.OK | wx.ICON_WARNING)
            return
        
        chapter_idx = self._chapter_list.GetItemData(idx)
        
        if self._current_book:
            # DAISY book
            chapters = self._current_book.get('chapters', [])
            audio_files = self._current_book.get('audio_files', [])
            
            if chapter_idx < len(audio_files):
                audio_path = audio_files[chapter_idx]
                title = self._current_book.get('title', 'Audiobook')
                chapter_title = chapters[chapter_idx]['title'] if chapter_idx < len(chapters) else f'Chapter {chapter_idx + 1}'

                self._engine.play(audio_path, title=f"{title} - {chapter_title}")
                self._apply_resume_seek()
        else:
            if os.path.isfile(self._current_path):
                audio_path = self._current_path
                self._engine.play(audio_path, title=os.path.basename(audio_path))
                self._apply_resume_seek()
            else:
                # Regular folder
                audio_files = sorted(
                    f for f in os.listdir(self._current_path)
                    if f.lower().endswith(self.AUDIO_EXTENSIONS)
                )
                if chapter_idx < len(audio_files):
                    audio_path = os.path.join(self._current_path, audio_files[chapter_idx])
                    self._engine.play(audio_path, title=os.path.basename(audio_path))
                    self._apply_resume_seek()

    def _apply_resume_seek(self) -> None:
        """Seek to the saved position once, shortly after playback starts."""
        if self._resume_position > 0:
            position = self._resume_position
            self._resume_position = 0.0
            import threading
            threading.Timer(1.0, lambda: self._engine.seek(position)).start()

    def _on_tts(self, event: wx.CommandEvent) -> None:
        """Start SAPI TTS reading."""
        if not self._current_path:
            wx.MessageBox("Please select an audiobook first.", "No Book Selected",
                         wx.OK | wx.ICON_WARNING)
            return
        
        idx = self._chapter_list.GetFirstSelected()
        if idx < 0:
            wx.MessageBox("Please select a chapter to read.", "No Chapter Selected",
                         wx.OK | wx.ICON_WARNING)
            return
        
        # Get the chapter text content
        if self._current_book:
            chapters = self._current_book.get('chapters', [])
            chapter_idx = self._chapter_list.GetItemData(idx)
            if chapter_idx < len(chapters):
                chapter = chapters[chapter_idx]
                text = chapter.get('text', '')
                if not text:
                    wx.MessageBox("This chapter has no text content to read.",
                                 "No Text", wx.OK | wx.ICON_WARNING)
                    return
                try:
                    from radiomaster.services.sapi_tts import SAPITTS
                    tts = SAPITTS()
                    tts.speak(text)
                except Exception as e:
                    wx.MessageBox(f"TTS failed: {e}\n\nPlease ensure SAPI is available.",
                                 "TTS Error", wx.OK | wx.ICON_ERROR)
                    return
        else:
            wx.MessageBox(
                "SAPI Text-to-Speech reading will start. "
                "Configure voice and speed in Settings.",
                "TTS Reading",
                wx.OK | wx.ICON_INFORMATION,
            )

    def _on_bookmark(self, event: wx.CommandEvent) -> None:
        """Add a bookmark at the current position."""
        if not self._current_path:
            wx.MessageBox("Please select an audiobook first.", "No Book Selected",
                         wx.OK | wx.ICON_WARNING)
            return

        idx = self._chapter_list.GetFirstSelected()
        if idx < 0:
            wx.MessageBox("Please select a chapter to bookmark.", "No Chapter Selected",
                         wx.OK | wx.ICON_WARNING)
            return

        chapter_idx = self._chapter_list.GetItemData(idx)
        chapter_title = self._chapter_list.GetItemText(idx)

        # Add bookmark to database
        from radiomaster.database.repository import BookmarkRepository
        repo = BookmarkRepository(self._db)

        try:
            repo.add(
                title=chapter_title,
                source_type="audiobook",
                url=self._current_path,
                position=self._engine.position,
            )
            wx.MessageBox(f"Bookmark added: {chapter_title}", "Bookmark Added",
                         wx.OK | wx.ICON_INFORMATION)
        except Exception as e:
            wx.MessageBox(f"Error adding bookmark: {str(e)}", "Error",
                         wx.OK | wx.ICON_ERROR)

    def _on_chapter_selected(self, event: wx.ListEvent) -> None:
        """Handle chapter selection."""
        idx = event.GetIndex()
        if idx >= 0 and self._current_book:
            chapter_idx = self._chapter_list.GetItemData(idx)
            chapters = self._current_book.get('chapters', [])
            if chapter_idx < len(chapters):
                # Could show chapter description or notes here
                pass

    def _on_tree_sel_changed(self, event: wx.TreeEvent) -> None:
        """Handle tree selection change."""
        item = event.GetItem()
        if item.IsOk():
            label = self._library_tree.GetItemText(item)
            # Could load book from library here
            pass
