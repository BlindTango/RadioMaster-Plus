"""YouTube tab panel with search, playback, and downloads."""

import wx
from typing import Any
from radiomaster.database.connection import DatabaseManager
from radiomaster.engine.playback_engine import PlaybackEngine
from radiomaster.utils.accessibility import set_accessible_name, set_search_ctrl_accessible_name


class YouTubePanel(wx.Panel):
    """Panel for searching and playing YouTube content."""

    def __init__(self, parent: wx.Window, db: DatabaseManager, engine: PlaybackEngine) -> None:
        super().__init__(parent)
        self._db = db
        self._engine = engine
        # Store the latest search results so we can retrieve URLs later
        self._search_results: list[dict] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Create the YouTube panel layout."""
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # Search bar
        search_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self._search_ctrl = wx.SearchCtrl(self, style=wx.TE_PROCESS_ENTER, size=(400, -1))
        set_search_ctrl_accessible_name(self._search_ctrl, "Search YouTube")
        self._search_ctrl.ShowSearchButton(True)
        search_sizer.Add(self._search_ctrl, 0, wx.ALL, 4)

        self._btn_search = wx.Button(self, label="Search")
        set_accessible_name(self._btn_search, "Search YouTube")
        search_sizer.Add(self._btn_search, 0, wx.ALL, 4)

        self._btn_play_url = wx.Button(self, label="Play URL...")
        set_accessible_name(self._btn_play_url, "Play YouTube URL")
        search_sizer.Add(self._btn_play_url, 0, wx.ALL, 4)

        main_sizer.Add(search_sizer, 0, wx.EXPAND)

        # Results list
        self._results_list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        set_accessible_name(self._results_list, "YouTube Results")
        self._results_list.AppendColumn("Title", width=350)
        self._results_list.AppendColumn("Duration", width=70)
        self._results_list.AppendColumn("Channel", width=150)
        main_sizer.Add(self._results_list, 1, wx.EXPAND | wx.ALL, 4)

        # Controls
        ctrl_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self._btn_play = wx.Button(self, label="Play Video")
        set_accessible_name(self._btn_play, "Play Video")
        ctrl_sizer.Add(self._btn_play, 0, wx.RIGHT, 4)

        self._btn_playlist = wx.Button(self, label="Load Playlist")
        set_accessible_name(self._btn_playlist, "Load Playlist")
        ctrl_sizer.Add(self._btn_playlist, 0, wx.RIGHT, 4)

        self._btn_download = wx.Button(self, label="Download")
        set_accessible_name(self._btn_download, "Download")
        ctrl_sizer.Add(self._btn_download, 0, wx.RIGHT, 4)

        self._btn_download_audio = wx.Button(self, label="Download Audio")
        set_accessible_name(self._btn_download_audio, "Download Audio Only")
        ctrl_sizer.Add(self._btn_download_audio, 0)

        main_sizer.Add(ctrl_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 4)

        # Quality selection
        qual_sizer = wx.BoxSizer(wx.HORIZONTAL)
        qual_sizer.Add(wx.StaticText(self, label="Quality:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._quality_choice = wx.Choice(self, choices=["best", "1080p", "720p", "480p", "360p", "audio only"])
        self._quality_choice.SetSelection(0)
        set_accessible_name(self._quality_choice, "Download Quality")
        qual_sizer.Add(self._quality_choice, 0, wx.LEFT, 4)
        qual_sizer.Add(wx.StaticText(self, label="Audio Format:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        audio_format_choices = ["mp3", "opus", "flac", "m4a"]
        self._audio_format_choice = wx.Choice(self, choices=audio_format_choices)
        # Settings > Downloads > Audio Format previously only seeded the
        # download's DB row label -- the panel's own dropdown (what
        # actually drives yt-dlp) always started back at "mp3" regardless.
        from radiomaster.utils.config import ConfigManager
        default_format = ConfigManager.get_instance().get("downloads.audio_format", default="mp3")
        self._audio_format_choice.SetSelection(
            audio_format_choices.index(default_format) if default_format in audio_format_choices else 0
        )
        set_accessible_name(self._audio_format_choice, "Audio Format")
        qual_sizer.Add(self._audio_format_choice, 0, wx.LEFT, 4)
        main_sizer.Add(qual_sizer, 0, wx.ALL, 4)

        self.SetSizer(main_sizer)

        self._btn_search.Bind(wx.EVT_BUTTON, self._on_search)
        self._btn_play_url.Bind(wx.EVT_BUTTON, self._on_play_url)
        self._btn_play.Bind(wx.EVT_BUTTON, self._on_play)
        self._btn_playlist.Bind(wx.EVT_BUTTON, self._on_load_playlist)
        self._btn_download.Bind(wx.EVT_BUTTON, self._on_download)
        self._btn_download_audio.Bind(wx.EVT_BUTTON, self._on_download_audio)
        self._search_ctrl.Bind(wx.EVT_SEARCHCTRL_SEARCH_BTN, self._on_search)
        self._search_ctrl.Bind(wx.EVT_TEXT_ENTER, self._on_search)

    def _on_search(self, event: wx.Event) -> None:
        """Search YouTube using yt-dlp, off the UI thread.

        This used to call YouTubeService()/service.search() directly on
        the UI thread -- a real ytsearch20 query is a single yt-dlp
        process that has to actually reach and scrape YouTube for all 20
        results before returning anything at all, easily several
        seconds, sometimes much longer. For that whole time the entire
        app was frozen: no repaints, no other tab, nothing -- exactly
        "freezes the application ... after a while returns 20 searches."
        """
        query = self._search_ctrl.GetValue().strip()
        if not query:
            return

        self._results_list.DeleteAllItems()
        self._search_results = []
        self._btn_search.Disable()
        self._set_status(f"Searching YouTube for '{query}'...")

        def worker():
            from radiomaster.services.youtube_dl import YouTubeService
            try:
                service = YouTubeService()
                results = service.search(query, max_results=20)
            except Exception as e:
                wx.CallAfter(self._on_search_failed, str(e))
                return
            wx.CallAfter(self._apply_search_results, results, query)

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _set_status(self, text: str) -> None:
        top = wx.GetTopLevelParent(self)
        if hasattr(top, "_status_bar"):
            top._status_bar.set_status(text)

    def _on_search_failed(self, message: str) -> None:
        self._btn_search.Enable()
        wx.MessageBox(f"Search failed: {message}", "Search Error", wx.OK | wx.ICON_ERROR)

    def _apply_search_results(self, results: list[dict], query: str) -> None:
        self._btn_search.Enable()
        for i, result in enumerate(results):
            idx = self._results_list.InsertItem(i, result.get('title', 'Unknown')[:100])
            self._results_list.SetItem(idx, 1, self._format_duration(result.get('duration', 0)))
            self._results_list.SetItem(idx, 2, result.get('channel', 'Unknown'))
            self._results_list.SetItemData(idx, i)  # Store index for retrieval
        self._search_results = results
        self._set_status(f"Status: {len(results)} result(s) for '{query}'")
    
    def _format_duration(self, seconds: int) -> str:
        """Format duration in seconds to MM:SS or HH:MM:SS."""
        if not seconds:
            return "Unknown"
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        return f"{minutes}:{secs:02d}"
    
    def _get_selected_video(self) -> dict | None:
        """Get the selected video data."""
        idx = self._results_list.GetFirstSelected()
        if idx < 0:
            return None
        # Retrieve the stored result using the index saved in item data
        result_index = self._results_list.GetItemData(idx)
        if isinstance(result_index, int) and 0 <= result_index < len(self._search_results):
            return self._search_results[result_index]
        # Fallback – return minimal info
        title = self._results_list.GetItemText(idx)
        return {'title': title, 'url': ''}

    def _on_play_url(self, event: wx.CommandEvent) -> None:
        """Play a YouTube URL."""
        dlg = wx.TextEntryDialog(self, "Enter YouTube URL:", "Play YouTube Video")
        if dlg.ShowModal() == wx.ID_OK:
            url = dlg.GetValue().strip()
            if url:
                self._engine.play(url, title=url, is_video=True)
        dlg.Destroy()

    def _on_play(self, event: wx.CommandEvent) -> None:
        """Play the selected video.

        Resolving the real stream URL (a yt-dlp process that has to
        contact YouTube) used to run right on the UI thread -- same
        class of freeze as the search button (see _on_search), just
        shorter since it's one video instead of twenty results.
        """
        video = self._get_selected_video()
        if not video:
            wx.MessageBox("Please select a video first.", "No Selection", wx.OK | wx.ICON_WARNING)
            return
        video_url = video.get('url') or video.get('webpage_url') or ""
        title = video.get('title', 'YouTube Video')
        self._set_status(f"Status: Resolving stream for '{title}'...")
        self._btn_play.Disable()

        def worker():
            from radiomaster.services.youtube_dl import YouTubeService
            service = YouTubeService()
            stream_url = service.get_stream_url(video_url)
            wx.CallAfter(self._apply_play_result, stream_url, title)

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _apply_play_result(self, stream_url: str | None, title: str) -> None:
        self._btn_play.Enable()
        if not stream_url:
            wx.MessageBox("Unable to resolve a playable stream for the selected video.",
                         "Error", wx.OK | wx.ICON_ERROR)
            return
        self._engine.play(stream_url, title=title, is_video=True)
        self._set_status(f"Status: Playing '{title}'")

    def _on_load_playlist(self, event: wx.CommandEvent) -> None:
        """Load a YouTube playlist and show its entries, off the UI
        thread (same reasoning as _on_search -- yt-dlp has to actually
        fetch the whole playlist listing before returning anything)."""
        dlg = wx.TextEntryDialog(self, "Enter playlist URL:", "Load Playlist")
        if dlg.ShowModal() == wx.ID_OK:
            url = dlg.GetValue().strip()
            if url:
                self._set_status(f"Status: Loading playlist...")
                self._btn_playlist.Disable()

                def worker():
                    from radiomaster.services.youtube_dl import YouTubeService
                    service = YouTubeService()
                    entries = service.get_playlist_entries(url)
                    wx.CallAfter(self._apply_playlist_entries, entries)

                import threading
                threading.Thread(target=worker, daemon=True).start()
        dlg.Destroy()

    def _apply_playlist_entries(self, entries: list[dict]) -> None:
        self._btn_playlist.Enable()
        if not entries:
            wx.MessageBox("No entries found in playlist.", "Playlist Empty", wx.OK | wx.ICON_WARNING)
            return
        self._results_list.DeleteAllItems()
        self._search_results = []
        for i, entry in enumerate(entries):
            idx = self._results_list.InsertItem(i, entry.get('title', 'Unknown')[:100])
            self._results_list.SetItem(idx, 1, self._format_duration(entry.get('duration', 0)))
            self._results_list.SetItem(idx, 2, entry.get('channel', entry.get('uploader', 'Unknown')))
            self._results_list.SetItemData(idx, i)
            self._search_results.append(entry)
        self._set_status(f"Status: Loaded {len(entries)} item(s) from playlist")

    def _on_download(self, event: wx.CommandEvent) -> None:
        """Download the selected video."""
        video = self._get_selected_video()
        if not video:
            wx.MessageBox("Please select a video first.", "No Selection", wx.OK | wx.ICON_WARNING)
            return

        from radiomaster.database.repository import DownloadRepository
        from radiomaster.utils.config import ConfigManager

        config = ConfigManager.get_instance()
        repo = DownloadRepository(self._db)

        # Resolve URL for download
        from radiomaster.services.youtube_dl import YouTubeService
        service = YouTubeService()
        video_url = video.get('url') or video.get('webpage_url') or ""
        if not video_url:
            wx.MessageBox("Unable to determine video URL for download.", "Error", wx.OK | wx.ICON_ERROR)
            return

        # Add to download queue with selected quality via DownloadManager
        quality = self._quality_choice.GetStringSelection()
        download_id = repo.add(video_url, title=video.get('title', 'YouTube Video'), format=quality)
        app = wx.GetApp()
        if hasattr(app, 'download_manager') and hasattr(app.download_manager, 'add_download'):
            from radiomaster.utils.paths import get_paths
            # Was always get_paths()["downloads"] regardless of what the
            # user set in Settings > Downloads > Download Location --
            # ignoring their choice entirely rather than just using it as
            # the default when nothing's been set.
            output_dir = config.get("downloads.download_path", default=str(get_paths()["downloads"]))
            app.download_manager.add_download(
                download_id, video_url, output_dir=output_dir,
                title=video.get('title', 'YouTube Video'),
                format=quality,
            )
        wx.MessageBox(f"Video download added to queue: {video.get('title', '')} ({quality})", "Download Added", wx.OK | wx.ICON_INFORMATION)

    def _on_download_audio(self, event: wx.CommandEvent) -> None:
        """Download audio only."""
        video = self._get_selected_video()
        if not video:
            wx.MessageBox("Please select a video first.", "No Selection", wx.OK | wx.ICON_WARNING)
            return

        from radiomaster.database.repository import DownloadRepository
        from radiomaster.utils.config import ConfigManager

        config = ConfigManager.get_instance()
        repo = DownloadRepository(self._db)

        from radiomaster.services.youtube_dl import YouTubeService
        service = YouTubeService()
        video_url = video.get('url') or video.get('webpage_url') or ""
        if not video_url:
            wx.MessageBox("Unable to determine video URL for audio download.", "Error", wx.OK | wx.ICON_ERROR)
            return

        # Record audio‑only download request with selected audio format via DownloadManager
        audio_fmt = self._audio_format_choice.GetStringSelection()
        # Settings > Downloads > Audio Quality was saved but never reached
        # yt-dlp -- every audio download hardcoded "--audio-quality 0"
        # (best VBR) regardless. yt-dlp's --audio-quality accepts "0" for
        # best VBR or an explicit bitrate like "192K".
        quality_setting = config.get("downloads.audio_quality", default="192k")
        audio_quality = "0" if quality_setting.lower() == "best" else quality_setting.upper()
        download_id = repo.add(video_url, title=video.get('title', 'YouTube Audio'), format=audio_fmt, quality=quality_setting)
        app = wx.GetApp()
        if hasattr(app, 'download_manager') and hasattr(app.download_manager, 'add_download'):
            from radiomaster.utils.paths import get_paths
            output_dir = config.get("downloads.download_path", default=str(get_paths()["downloads"]))
            app.download_manager.add_download(
                download_id, video_url, output_dir=output_dir,
                title=video.get('title', 'YouTube Audio'),
                format=audio_fmt, extract_audio=True, audio_quality=audio_quality,
            )
        wx.MessageBox(f"Audio download added to queue: {video.get('title', '')} ({audio_fmt})", "Download Added", wx.OK | wx.ICON_INFORMATION)
