"""YouTube tab panel with search, playback, and downloads."""

import threading

import wx

from radiomaster.database.connection import DatabaseManager
from radiomaster.engine.playback_engine import PlaybackEngine
from radiomaster.utils.accessibility import set_accessible_name, set_search_ctrl_accessible_name
from radiomaster.utils.wx_safe import call_after_safe


class YouTubePanel(wx.Panel):
    """Panel for searching and playing YouTube content."""

    def __init__(self, parent: wx.Window, db: DatabaseManager, engine: PlaybackEngine) -> None:
        super().__init__(parent)
        self._db = db
        self._engine = engine
        # Store the latest search results so we can retrieve URLs later
        self._search_results: list[dict] = []
        # Which kind of entry _search_results currently holds -- "video",
        # "channel", or "playlist". Drives both how the results list's
        # columns are labeled/filled and what Enter/double-click does
        # (play a video vs. drill into a channel's videos vs. load a
        # playlist's entries) -- and guards Download/Download Audio/Play
        # from being handed a channel or playlist URL by mistake (yt-dlp
        # would happily try to download an entire channel's uploads).
        self._result_type = "video"
        self._channel_data: list[dict] = []
        self._browse_request_seq = 0
        self._channel_context = None
        self._channel_loading = False
        self._channel_focus_results = False
        self._channel_page_size = 100
        self._channel_selection_timer = None
        # Enter and double-click both fire EVT_LIST_ITEM_ACTIVATED for
        # what a user experiences as one action, but a fast double-click
        # can still land two separate activations (or Enter + a
        # double-click close together) before the first stream URL has
        # even finished resolving -- each starts its own background
        # yt-dlp resolution. Without tracking which one is the latest,
        # whichever resolution happened to finish LAST would win no
        # matter which the user actually meant, including an older,
        # already-superseded request replacing a video that had already
        # started playing correctly -- exactly the "opened two windows /
        # a video that isn't playing" symptom. Every worker checks this
        # against the request it was given before actually calling
        # engine.play(); a stale one is silently dropped.
        self._play_request_seq = 0
        self._playback_generation_at_request = None
        # The *source* (page) URL/title/duration behind whatever's
        # currently playing -- separate from the engine's own
        # _current_url, which by the time playback starts is already the
        # resolved (and, if rejected, now useless) googlevideo.com
        # stream URL. A stream-rejection retry needs the original page
        # URL to re-resolve from; nothing else in the panel keeps it
        # around once _apply_play_result hands the resolved URL off.
        self._current_source_url = ""
        self._current_source_title = ""
        self._current_source_duration = 0.0
        self._stream_rejected_retried = False
        # A temp file downloaded as a fallback when a video has no single
        # muxed stream URL (modern YouTube splits video/audio). Kept so it
        # can be deleted once playback moves on or the panel is destroyed.
        self._temp_playback_file: str | None = None
        self.on_content_changed = None
        self._video_info_seq = 0
        self._engine.on_stream_rejected(self._on_stream_rejected)
        self._setup_ui()
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)

    def _on_destroy(self, event: wx.WindowDestroyEvent) -> None:
        """Clean up any temp playback file when the panel is destroyed."""
        if event.GetEventObject() is self:
            self._browse_request_seq += 1
            if self._channel_selection_timer is not None:
                self._channel_selection_timer.cancel()
            self._cleanup_temp_file()
        event.Skip()

    def _cleanup_temp_file(self) -> None:
        """Delete the temp playback file, if any."""
        if self._temp_playback_file:
            try:
                import os
                os.remove(self._temp_playback_file)
            except OSError:
                pass
            self._temp_playback_file = None

    def _resolve_and_play(self, url: str, title: str, duration: float, seq: int,
                          stream: dict | None = None) -> None:
        """Resolve one stream without waiting for a whole video download."""
        from radiomaster.services.youtube_dl import YouTubeService
        error = ""
        if stream is None:
            try:
                service = YouTubeService()
                stream = service.get_stream_info(url)
                if not stream:
                    error = service.last_stream_error
            except Exception as exc:
                error = str(exc)
        if seq != self._play_request_seq:
            return
        if stream:
            title = stream.get("title") or title
            duration = float(stream.get("duration") or duration)
        stream_url = (stream or {}).get('url')
        headers = (stream or {}).get('http_headers')
        options = {"video_info": stream}
        if error:
            options['error'] = error
        wx.CallAfter(self._apply_play_result, stream_url, title, duration, seq, headers, **options)

    def _setup_ui(self) -> None:
        """Create the YouTube panel layout."""
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # Search bar
        search_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self._search_ctrl = wx.SearchCtrl(self, style=wx.TE_PROCESS_ENTER, size=(400, -1))
        set_search_ctrl_accessible_name(self._search_ctrl, "Search YouTube")
        self._search_ctrl.ShowSearchButton(True)
        search_sizer.Add(self._search_ctrl, 0, wx.ALL, 4)

        search_sizer.Add(wx.StaticText(self, label="&Type:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)
        self._search_type_choice = wx.Choice(self, choices=["Videos", "Channels", "Playlists"])
        self._search_type_choice.SetSelection(0)
        set_accessible_name(self._search_type_choice, "Search Type")
        search_sizer.Add(self._search_type_choice, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)

        self._btn_search = wx.Button(self, label="Search")
        set_accessible_name(self._btn_search, "Search YouTube")
        search_sizer.Add(self._btn_search, 0, wx.ALL, 4)

        self._btn_play_url = wx.Button(self, label="Play URL...")
        set_accessible_name(self._btn_play_url, "Play YouTube URL")
        search_sizer.Add(self._btn_play_url, 0, wx.ALL, 4)

        main_sizer.Add(search_sizer, 0, wx.EXPAND)

        # --- Content row: subscribed channels (left) + results (right) --
        # mirrors PodcastPanel's Podcasts/Episodes column pair: a
        # subscribed channel is browsed by opening it (Enter/double-
        # click/View Videos), the same way a subscribed podcast's
        # episode list is loaded.
        content_sizer = wx.BoxSizer(wx.HORIZONTAL)

        col_channels = wx.Panel(self)
        col_channels_sizer = wx.BoxSizer(wx.VERTICAL)
        col_channels_sizer.Add(wx.StaticText(col_channels, label="My Channels"), 0, wx.ALL, 4)
        self._channels_list = wx.ListCtrl(col_channels, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self._channels_list.AppendColumn("Title", width=180)
        set_accessible_name(self._channels_list, "My Channels")
        col_channels_sizer.Add(self._channels_list, 1, wx.EXPAND | wx.ALL, 4)
        self._btn_view_videos = wx.Button(col_channels, label="&View Videos")
        set_accessible_name(self._btn_view_videos, "View videos from selected subscribed channel")
        self._btn_view_videos.Disable()
        col_channels_sizer.Add(self._btn_view_videos, 0, wx.EXPAND | wx.ALL, 4)
        self._btn_unsubscribe = wx.Button(col_channels, label="&Unsubscribe")
        set_accessible_name(self._btn_unsubscribe, "Unsubscribe from selected channel")
        col_channels_sizer.Add(self._btn_unsubscribe, 0, wx.EXPAND | wx.ALL, 4)
        col_channels.SetSizer(col_channels_sizer)
        content_sizer.Add(col_channels, 1, wx.EXPAND | wx.RIGHT, 4)

        col_results = wx.Panel(self)
        col_results_sizer = wx.BoxSizer(wx.VERTICAL)
        col_results_sizer.Add(wx.StaticText(col_results, label="Results"), 0, wx.ALL, 4)
        self._results_list = wx.ListCtrl(col_results, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        set_accessible_name(self._results_list, "YouTube Results")
        self._results_list.AppendColumn("Title", width=350)
        self._results_list.AppendColumn("Duration", width=70)
        self._results_list.AppendColumn("Channel", width=150)
        col_results_sizer.Add(self._results_list, 1, wx.EXPAND | wx.ALL, 4)
        self._btn_more_videos = wx.Button(col_results, label="Load &More Videos")
        set_accessible_name(self._btn_more_videos, "Load more videos from this channel")
        self._btn_more_videos.Disable()
        col_results_sizer.Add(self._btn_more_videos, 0, wx.EXPAND | wx.ALL, 4)
        self._btn_subscribe = wx.Button(col_results, label="Su&bscribe to Channel")
        set_accessible_name(self._btn_subscribe, "Subscribe to selected item's channel")
        col_results_sizer.Add(self._btn_subscribe, 0, wx.EXPAND | wx.ALL, 4)
        col_results.SetSizer(col_results_sizer)
        content_sizer.Add(col_results, 3, wx.EXPAND)

        main_sizer.Add(content_sizer, 1, wx.EXPAND)

        # Controls -- no inline Play button here: matches RadioPanel and
        # PodcastPanel, neither of which has one either. Enter/double-
        # click on the list (bound below) plus the shared transport
        # bar's own Play button are what actually start playback; a
        # second, separate "Play Video" button next to those was two
        # different-looking play controls that don't do quite the same
        # thing, not actually useful.
        ctrl_sizer = wx.BoxSizer(wx.HORIZONTAL)
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
        from radiomaster.services.download_manager import AUDIO_FORMATS, normalize_audio_format
        audio_format_choices = list(AUDIO_FORMATS)
        self._audio_format_choices = audio_format_choices
        self._audio_format_choice = wx.Choice(self, choices=audio_format_choices)
        # Settings > Downloads > Audio Format previously only seeded the
        # download's DB row label -- the panel's own dropdown (what
        # actually drives yt-dlp) always started back at "mp3" regardless.
        from radiomaster.utils.config import ConfigManager
        default_format = normalize_audio_format(
            ConfigManager.get_instance().get("downloads.audio_format", default="mp3")
        )
        self._audio_format_choice.SetSelection(
            audio_format_choices.index(default_format) if default_format in audio_format_choices else 0
        )
        set_accessible_name(self._audio_format_choice, "Audio Format")
        qual_sizer.Add(self._audio_format_choice, 0, wx.LEFT, 4)
        main_sizer.Add(qual_sizer, 0, wx.ALL, 4)

        self.SetSizer(main_sizer)

        self._btn_search.Bind(wx.EVT_BUTTON, self._on_search)
        self._btn_play_url.Bind(wx.EVT_BUTTON, self._on_play_url)
        self._btn_playlist.Bind(wx.EVT_BUTTON, self._on_load_playlist)
        self._btn_download.Bind(wx.EVT_BUTTON, self._on_download)
        self._btn_download_audio.Bind(wx.EVT_BUTTON, self._on_download_audio)
        self._btn_subscribe.Bind(wx.EVT_BUTTON, self._on_subscribe)
        self._btn_unsubscribe.Bind(wx.EVT_BUTTON, self._on_unsubscribe)
        self._btn_view_videos.Bind(wx.EVT_BUTTON, self._on_view_videos)
        self._btn_more_videos.Bind(wx.EVT_BUTTON, self._on_more_videos)
        self._search_ctrl.Bind(wx.EVT_SEARCHCTRL_SEARCH_BTN, self._on_search)
        self._search_ctrl.Bind(wx.EVT_TEXT_ENTER, self._on_search)
        # Enter/double-click plays the selected result directly -- every
        # other list in the app already works this way (Radio stations,
        # Podcast episodes, Downloads History); this list never had it,
        # so "Play Video" was the only way in, unlike everywhere else.
        # For a channel/playlist result, activating drills into it (its
        # videos, or its entries) instead of trying to play it directly --
        # see _on_result_activated.
        self._results_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_result_activated)
        self._results_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_result_selected)
        # EVT_CONTEXT_MENU also fires for the Applications key and Shift+F10.
        self._results_list.Bind(wx.EVT_CONTEXT_MENU, self._on_results_context_menu)
        self._channels_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_channel_activated)
        self._channels_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_channel_selected)
        self._channels_list.Bind(wx.EVT_LIST_ITEM_DESELECTED, self._on_channel_deselected)

        self._load_channels()

    def refresh_download_settings(self) -> None:
        """Apply Downloads settings to controls that persist for the session."""
        from radiomaster.utils.config import ConfigManager
        from radiomaster.services.download_manager import normalize_audio_format
        audio_format = normalize_audio_format(
            ConfigManager.get_instance().get("downloads.audio_format", default="mp3")
        )
        selection = (
            self._audio_format_choices.index(audio_format)
            if audio_format in self._audio_format_choices
            else 0
        )
        self._audio_format_choice.SetSelection(selection)

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
        search_type = self._selected_search_type()
        request_seq = self._begin_browse()

        self._results_list.DeleteAllItems()
        self._search_results = []
        self._btn_search.Disable()
        self._set_status(f"Searching YouTube for '{query}'...")

        def worker():
            from radiomaster.services.youtube_dl import YouTubeService
            try:
                service = YouTubeService()
                results = service.search(query, max_results=100, search_type=search_type)
            except Exception as e:
                call_after_safe(self, self._on_search_failed, str(e), request_seq)
                return
            call_after_safe(self, self._apply_search_results, results, query, search_type, request_seq)

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _selected_search_type(self) -> str:
        return {0: "video", 1: "channel", 2: "playlist"}.get(
            self._search_type_choice.GetSelection(), "video"
        )

    def _set_status(self, text: str) -> None:
        top = wx.GetTopLevelParent(self)
        if hasattr(top, "_status_bar"):
            top._status_bar.set_status(text)

    def _on_search_failed(self, message: str, request_seq: int | None = None) -> None:
        if request_seq is not None and request_seq != self._browse_request_seq:
            return
        self._btn_search.Enable()
        wx.MessageBox(f"Search failed: {message}", "Search Error", wx.OK | wx.ICON_ERROR)

    def _set_results_columns_for_type(self, search_type: str) -> None:
        """Relabels the results list's 3 columns for what search_type
        actually fills them with -- NVDA reads column headers, so a
        subscriber count sitting under a header that still says
        "Duration" would be actively misleading, not just cosmetic."""
        headers = {
            "video": ("Title", "Duration", "Channel"),
            "channel": ("Channel", "Subscribers", "Status"),
            "playlist": ("Title", "Videos", "Channel"),
        }.get(search_type, ("Title", "Duration", "Channel"))
        for col, text in enumerate(headers):
            item = self._results_list.GetColumn(col)
            item.SetText(text)
            self._results_list.SetColumn(col, item)

    def _apply_search_results(self, results: list[dict], query: str,
                               search_type: str = "video", request_seq: int | None = None) -> None:
        if request_seq is not None and request_seq != self._browse_request_seq:
            return
        self._btn_search.Enable()
        self._result_type = search_type
        self._set_results_columns_for_type(search_type)
        self._results_list.DeleteAllItems()
        from radiomaster.database.repository import YouTubeChannelRepository
        channel_repo = YouTubeChannelRepository(self._db)
        for i, result in enumerate(results):
            idx = self._results_list.InsertItem(i, result.get('title', 'Unknown')[:100])
            if search_type == "channel":
                self._results_list.SetItem(idx, 1, self._format_count(result.get('channel_follower_count')))
                channel_id = result.get('channel_id') or result.get('id') or ''
                self._results_list.SetItem(idx, 2, "Subscribed" if channel_repo.is_subscribed(channel_id) else "")
            elif search_type == "playlist":
                count = result.get('playlist_count')
                self._results_list.SetItem(idx, 1, str(count) if count else "")
                self._results_list.SetItem(idx, 2, result.get('channel', result.get('uploader', 'Unknown')))
            else:
                self._results_list.SetItem(idx, 1, self._format_duration(result.get('duration', 0)))
                self._results_list.SetItem(idx, 2, result.get('channel', result.get('uploader', 'Unknown')))
            self._results_list.SetItemData(idx, i)  # Store index for retrieval
        self._search_results = results
        self._set_status(f"Status: {len(results)} result(s) for '{query}'")

    @staticmethod
    def _format_count(count: int | None) -> str:
        """Formats a subscriber count the way YouTube itself abbreviates
        it (1.2M, 340K) -- a raw 7+ digit number is a lot to have read
        out by a screen reader for what's meant to be a rough sense of
        channel size, not an exact figure."""
        if not count:
            return "Unknown"
        if count >= 1_000_000:
            return f"{count / 1_000_000:.1f}M subscribers"
        if count >= 1_000:
            return f"{count / 1_000:.1f}K subscribers"
        return f"{count} subscribers"

    def _format_duration(self, seconds: int | float | None) -> str:
        """Format duration in seconds to MM:SS or HH:MM:SS."""
        try:
            seconds = int(seconds or 0)
        except (TypeError, ValueError, OverflowError):
            return "Unknown"
        if seconds <= 0:
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

    @staticmethod
    def _video_info_text(video: dict) -> str:
        """Format yt-dlp metadata as screen-reader-friendly plain text."""
        title = video.get("title") or "YouTube Video"
        channel = video.get("channel") or video.get("uploader") or ""
        duration = int(video.get("duration") or 0)
        parts = [title]
        if channel:
            parts.append(f"Channel: {channel}")
        if duration:
            hours, remainder = divmod(duration, 3600)
            minutes, seconds = divmod(remainder, 60)
            formatted = (f"{hours}:{minutes:02d}:{seconds:02d}" if hours
                         else f"{minutes}:{seconds:02d}")
            parts.append(f"Duration: {formatted}")
        if video.get("upload_date"):
            parts.append(f"Uploaded: {video['upload_date']}")
        if video.get("view_count") is not None:
            parts.append(f"Views: {video['view_count']:,}")
        description = (video.get("description") or "").strip()
        parts.extend(["", description or "No video description is available."])
        return "\n".join(parts)

    def _publish_video_info(self, video: dict, seq: int | None = None) -> None:
        if seq is not None and seq != self._video_info_seq:
            return
        if self.on_content_changed:
            self.on_content_changed(self._video_info_text(video))

    def _on_result_selected(self, event: wx.ListEvent) -> None:
        self._publish_video_info(self._get_selected_video() or {})
        event.Skip()

    def show_selected_info(self) -> None:
        """Restore selected video information when returning to this tab."""
        video = self._get_selected_video()
        if video:
            self._publish_video_info(video)

    def _load_full_video_info(self, service, url: str, fallback: dict, seq: int) -> dict:
        """Fetch the description for playback without touching wx off-thread."""
        info = service.get_info(url) or fallback
        wx.CallAfter(self._publish_video_info, info, seq)
        return info

    def navigate(self, kind: str) -> str | None:
        """Move through the video results and play that video. Returns the
        message to announce, or None when the list holds no videos (empty,
        or channels/playlists, which are opened rather than played)."""
        count = self._results_list.GetItemCount()
        if count == 0 or self._result_type in ("channel", "playlist"):
            return None
        cur = self._results_list.GetFirstSelected()
        target = {"first": 0, "last": count - 1,
                  "next": cur + 1 if cur >= 0 else 0,
                  "prev": cur - 1 if cur >= 0 else count - 1}[kind]
        if not 0 <= target < count:
            return "Last result" if kind == "next" else "First result"
        for i in range(count):
            self._results_list.Select(i, i == target)
        self._results_list.Focus(target)
        self._on_play(None)
        return f"Result {target + 1} of {count}: {self._results_list.GetItemText(target)}"

    def _on_result_activated(self, event: wx.CommandEvent) -> None:
        """Enter/double-click on a results-list row: plays a video result
        directly (unchanged), but drills into a channel's videos or a
        playlist's entries instead of trying to play a channel/playlist
        URL as if it were a stream.

        The activated row may only be *focused*, not *selected* -- e.g.
        when navigating with arrow keys and pressing Enter, or when a
        double-click lands on a row that was never clicked to select it.
        GetFirstSelected() then returns -1 (or a stale earlier row), so
        the handlers below would act on nothing or on the wrong video.
        Select the activated row first so they operate on the row the
        user actually activated."""
        idx = event.GetIndex()
        if idx != wx.NOT_FOUND:
            self._results_list.Select(idx)
        if self._result_type == "channel":
            self._open_selected_channel()
        elif self._result_type == "playlist":
            self._open_selected_playlist()
        else:
            self._on_play(event)

    def _open_selected_channel(self) -> None:
        channel = self._get_selected_video()
        if not channel:
            return
        channel_url = channel.get('channel_url') or channel.get('url') or ""
        title = channel.get('title') or channel.get('channel') or "Channel"
        if not channel_url:
            wx.MessageBox("Could not determine this channel's URL.", "Error", wx.OK | wx.ICON_ERROR)
            return
        self._load_channel_videos(channel_url, title,
                                  channel_id=channel.get('channel_id') or channel.get('id') or '',
                                  focus_results=True)

    def _open_selected_playlist(self) -> None:
        playlist = self._get_selected_video()
        if not playlist:
            return
        playlist_url = playlist.get('url') or playlist.get('webpage_url') or ""
        if not playlist_url:
            wx.MessageBox("Could not determine this playlist's URL.", "Error", wx.OK | wx.ICON_ERROR)
            return
        request_seq = self._begin_browse()
        self._set_status(f"Status: Loading playlist '{playlist.get('title', '')}'...")

        def worker():
            from radiomaster.services.youtube_dl import YouTubeService
            service = YouTubeService()
            entries = service.get_playlist_entries(playlist_url)
            call_after_safe(self, self._apply_playlist_entries, entries, request_seq)

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _begin_browse(self) -> int:
        if self._channel_selection_timer is not None:
            self._channel_selection_timer.cancel()
            self._channel_selection_timer = None
        self._browse_request_seq += 1
        self._channel_context = None
        self._channel_loading = False
        self._channel_focus_results = False
        self._btn_more_videos.Disable()
        self._btn_search.Enable()
        self._btn_playlist.Enable()
        return self._browse_request_seq

    def _load_channel_videos(self, channel_url: str, title: str, *, channel_id: str = "",
                             focus_results: bool = False, refresh: bool = False) -> None:
        key = (channel_url, channel_id)
        if self._channel_context and self._channel_context["key"] == key and not refresh:
            self._channel_focus_results |= focus_results
            if self._channel_loading:
                return
            if self._search_results or self._channel_context["next_start"] > 1:
                if focus_results:
                    if (self._search_results
                            and self._results_list.GetFirstSelected() == wx.NOT_FOUND):
                        self._results_list.Select(0)
                        self._results_list.Focus(0)
                        self._results_list.EnsureVisible(0)
                    self._results_list.SetFocus()
                return
        if self._channel_loading and self._channel_context["key"] == key:
            self._channel_focus_results |= focus_results
            return
        self._begin_browse()
        self._channel_context = {"key": key, "url": channel_url, "title": title,
                                 "id": channel_id, "next_start": 1}
        self._channel_focus_results = focus_results
        self._search_results = []
        self._results_list.DeleteAllItems()
        self._result_type = "video"
        self._set_results_columns_for_type("video")
        self._fetch_channel_page()

    def _fetch_channel_page(self) -> None:
        if self._channel_loading or not self._channel_context:
            return
        context = dict(self._channel_context)
        request_seq = self._browse_request_seq
        self._channel_loading = True
        self._btn_more_videos.Disable()
        self._set_status(f"Status: Loading videos for '{context['title']}'...")

        def worker():
            from radiomaster.services.youtube_dl import YouTubeService
            try:
                entries = YouTubeService().get_channel_videos(
                    context['url'], self._channel_page_size,
                    start=context['next_start'], channel_id=context['id'])
            except Exception as exc:
                call_after_safe(self, self._channel_page_failed, request_seq, str(exc))
                return
            call_after_safe(self, self._apply_channel_page,
                            request_seq, context['next_start'], entries)

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _apply_channel_page(self, request_seq: int, start: int, entries: list[dict]) -> None:
        if request_seq != self._browse_request_seq or not self._channel_context:
            return
        self._channel_loading = False
        first_new_row = len(self._search_results)
        existing = {item.get('id') or item.get('url') for item in self._search_results}
        for entry in entries:
            identity = entry.get('id') or entry.get('url')
            if identity and identity in existing:
                continue
            existing.add(identity)
            index = len(self._search_results)
            row = self._results_list.InsertItem(index, (entry.get('title') or 'Unknown')[:100])
            self._results_list.SetItem(row, 1, self._format_duration(entry.get('duration') or 0))
            self._results_list.SetItem(row, 2, entry.get('channel') or entry.get('uploader')
                                      or self._channel_context['title'])
            self._results_list.SetItemData(row, index)
            self._search_results.append(entry)
        complete = getattr(entries, 'complete', True)
        self._channel_context['next_start'] = start + self._channel_page_size if complete else start
        more = not complete or len(entries) >= self._channel_page_size or any(
            isinstance(entry.get('playlist_index'), int)
            and entry['playlist_index'] >= start + self._channel_page_size - 1
            for entry in entries)
        self._btn_more_videos.Enable(more)
        count = len(self._search_results)
        title = self._channel_context['title']
        if count:
            if not complete:
                suffix = ' This page was interrupted. Use Load More Videos to retry it.'
            else:
                suffix = (' Use Load More Videos for older uploads.'
                          if more else ' End of channel videos.')
            self._set_status(f"Status: Showing {count} video(s) from '{title}'.{suffix}")
        else:
            self._set_status(
                f"Status: No public videos found for '{title}'. Use View Videos to retry.")
        if self._channel_focus_results and count:
            row = min(first_new_row, count - 1)
            selected = self._results_list.GetFirstSelected()
            if selected != wx.NOT_FOUND:
                self._results_list.Select(selected, False)
            self._results_list.Select(row)
            self._results_list.Focus(row)
            self._results_list.EnsureVisible(row)
            self._results_list.SetFocus()
        self._channel_focus_results = False

    def _channel_page_failed(self, request_seq: int, message: str) -> None:
        if request_seq != self._browse_request_seq or not self._channel_context:
            return
        self._channel_loading = False
        self._btn_more_videos.Enable(bool(self._search_results))
        self._set_status(
            f"Status: Could not load videos for '{self._channel_context['title']}': {message}")

    def _on_more_videos(self, event) -> None:
        self._channel_focus_results = True
        self._fetch_channel_page()

    # ------------------------------------------------------------------
    # Results-list context menu
    # ------------------------------------------------------------------
    def _current_channel(self) -> dict | None:
        """The channel the results belong to: the one being browsed, else
        the channel of the selected result."""
        if self._channel_context:
            ctx = self._channel_context
            return {"url": ctx["url"], "title": ctx["title"], "id": ctx["id"]}
        item = self._get_selected_video()
        if not item:
            return None
        if self._result_type == "channel":
            url = item.get("channel_url") or item.get("url") or ""
            title = item.get("title") or item.get("channel") or "Channel"
            cid = item.get("channel_id") or item.get("id") or ""
        else:
            url = item.get("channel_url") or ""
            title = item.get("channel") or item.get("uploader") or "Channel"
            cid = item.get("channel_id") or ""
        return {"url": url, "title": title, "id": cid} if url or cid else None

    def _on_results_context_menu(self, event) -> None:
        position = event.GetPosition()
        if position != wx.DefaultPosition:
            # Right-click: act on the row under the pointer.
            row, _flags = self._results_list.HitTest(self._results_list.ScreenToClient(position))
            if row != wx.NOT_FOUND:
                for i in range(self._results_list.GetItemCount()):
                    self._results_list.Select(i, i == row)
                self._results_list.Focus(row)
        has_item = self._results_list.GetFirstSelected() != wx.NOT_FOUND
        is_video = self._result_type == "video"
        channel = self._current_channel()
        menu = wx.Menu()

        def add(label: str, handler, enabled: bool = True) -> None:
            item = menu.Append(wx.ID_ANY, label)
            item.Enable(enabled)
            menu.Bind(wx.EVT_MENU, handler, item)

        add("&Play", self._on_play, has_item)
        menu.AppendSeparator()
        add("Download &Video", self._on_download, has_item and is_video)
        add("Download &Audio Only", self._on_download_audio, has_item and is_video)
        menu.AppendSeparator()
        add("Download &All Videos from Channel...", self._on_download_channel, channel is not None)
        add("Load &More Videos", self._on_more_videos, self._btn_more_videos.IsEnabled())
        add("&Subscribe to Channel", self._on_subscribe, has_item)
        self._results_list.PopupMenu(menu)
        menu.Destroy()

    def _on_download_channel(self, event) -> None:
        channel = self._current_channel()
        if not channel:
            wx.MessageBox("Select a video or channel first.", "No Selection",
                          wx.OK | wx.ICON_WARNING)
            return
        self._set_status(f"Status: Listing every video from '{channel['title']}'...")

        def worker():
            from radiomaster.services.youtube_dl import YouTubeService
            service = YouTubeService()
            videos: list[dict] = []
            seen: set = set()
            start = 1
            try:
                for _ in range(200):
                    batch = service.get_channel_videos(
                        channel["url"], self._channel_page_size, start=start,
                        channel_id=channel["id"])
                    fresh = [e for e in batch
                             if (e.get("id") or e.get("url")) not in seen]
                    for entry in fresh:
                        seen.add(entry.get("id") or entry.get("url"))
                    videos.extend(fresh)
                    if not fresh or len(batch) < self._channel_page_size:
                        break
                    start += self._channel_page_size
            except Exception as exc:
                call_after_safe(self, self._bulk_failed, str(exc))
                return
            call_after_safe(self, self._confirm_channel_download, channel["title"], videos)

        threading.Thread(target=worker, daemon=True).start()

    def _bulk_failed(self, message: str) -> None:
        self._set_status(f"Status: Could not list the channel's videos: {message}")

    @staticmethod
    def _entry_url(entry: dict) -> str:
        url = entry.get("url") or entry.get("webpage_url") or ""
        if url and not url.startswith("http") and entry.get("id"):
            url = ""
        return url or (f"https://www.youtube.com/watch?v={entry['id']}" if entry.get("id") else "")

    def _confirm_channel_download(self, channel_title: str, videos: list[dict]) -> None:
        if not videos:
            self._set_status(f"Status: No videos found for '{channel_title}'.")
            wx.MessageBox("No videos were found for this channel.", "Nothing to Download",
                          wx.OK | wx.ICON_INFORMATION)
            return
        self._set_status(f"Status: Found {len(videos)} video(s) from '{channel_title}'.")
        answer = wx.MessageBox(
            f"Download all {len(videos)} videos from '{channel_title}'?\n\n"
            "Yes: download as video.\nNo: download audio only.\nCancel: do nothing.",
            "Download Channel", wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION)
        if answer == wx.CANCEL:
            self._set_status("Status: Channel download cancelled.")
            return
        count = self._queue_downloads(videos, audio=(answer == wx.NO))
        self._set_status(f"Status: Queued {count} download(s) from '{channel_title}'.")
        wx.MessageBox(f"Added {count} download(s) to the queue.", "Download Added",
                      wx.OK | wx.ICON_INFORMATION)

    def _queue_downloads(self, videos: list[dict], *, audio: bool) -> int:
        from radiomaster.database.repository import DownloadRepository
        from radiomaster.utils.config import ConfigManager
        from radiomaster.utils.paths import get_downloads_dir
        repo = DownloadRepository(self._db)
        output_dir = get_downloads_dir()
        app = wx.GetApp()
        manager = getattr(app, "download_manager", None)
        if audio:
            fmt = self._audio_format_choice.GetStringSelection()
            setting = ConfigManager.get_instance().get("downloads.audio_quality", default="192k")
            audio_quality = "0" if setting.lower() == "best" else setting.upper()
        else:
            fmt = self._quality_choice.GetStringSelection()
        count = 0
        for entry in videos:
            url = self._entry_url(entry)
            if not url:
                continue
            title = entry.get("title") or "YouTube Video"
            if audio:
                download_id = repo.add(url, title=title, format=fmt, quality=setting,
                                       output_dir=output_dir, extract_audio=True)
                extra = {"extract_audio": True, "audio_quality": audio_quality}
            else:
                download_id = repo.add(url, title=title, format=fmt, output_dir=output_dir)
                extra = {}
            if manager is not None and hasattr(manager, "add_download"):
                manager.add_download(download_id, url, output_dir=output_dir,
                                     title=title, format=fmt, **extra)
            count += 1
        return count

    # ------------------------------------------------------------------
    # Channel subscriptions -- mirrors PodcastPanel's Subscribe/
    # Unsubscribe pattern. Any result (video, channel, or playlist) can
    # be subscribed from, not only a Channels-type search result: every
    # yt-dlp entry already carries its channel_id/channel_url/channel
    # regardless of which of the three it itself is.
    # ------------------------------------------------------------------
    def _load_channels(self) -> None:
        from radiomaster.database.repository import YouTubeChannelRepository
        self._begin_browse()
        self._channels_list.DeleteAllItems()
        self._channel_data = YouTubeChannelRepository(self._db).get_all()
        for i, channel in enumerate(self._channel_data):
            self._channels_list.InsertItem(i, channel.get('title', 'Unknown'))
        self._btn_view_videos.Disable()

    def _on_channel_activated(self, event: wx.CommandEvent) -> None:
        index = event.GetIndex()
        if 0 <= index < len(self._channel_data):
            selected = self._channels_list.GetFirstSelected()
            if selected != wx.NOT_FOUND and selected != index:
                self._channels_list.Select(selected, False)
            if selected != index:
                self._channels_list.Select(index)
            if self._channels_list.GetFocusedItem() != index:
                self._channels_list.Focus(index)
            self._open_subscribed_channel(index, focus_results=True)

    def _on_view_videos(self, event) -> None:
        index = self._channels_list.GetFirstSelected()
        if index == wx.NOT_FOUND:
            index = self._channels_list.GetFocusedItem()
        self._open_subscribed_channel(index, focus_results=True, refresh=True)

    def _open_subscribed_channel(self, index: int, *, focus_results: bool = False,
                                 refresh: bool = False) -> None:
        if not 0 <= index < len(self._channel_data):
            return
        self._btn_view_videos.Enable()
        channel = self._channel_data[index]
        url = channel.get('url') or ("https://www.youtube.com/channel/" + channel['channel_id'])
        self._load_channel_videos(url, channel.get('title') or 'Channel',
                                  channel_id=channel.get('channel_id') or '',
                                  focus_results=focus_results, refresh=refresh)

    def _on_channel_deselected(self, event) -> None:
        self._btn_view_videos.Disable()
        event.Skip()

    def _on_channel_selected(self, event: wx.ListEvent) -> None:
        """Load the selected subscribed channel's videos into the results list.

        Mirrors the Podcasts panel, where selecting a subscription loads
        its episodes without requiring Enter or a double-click. Without
        this, arrowing through My Channels showed nothing in the results
        list until the user pressed Enter, which was inconsistent with
        how every other subscription-style list in the app works.
        """
        index = event.GetIndex()
        if 0 <= index < len(self._channel_data):
            channel = self._channel_data[index]
            url = channel.get('url') or ('https://www.youtube.com/channel/' + channel['channel_id'])
            key = (url, channel.get('channel_id') or '')
            self._btn_view_videos.Enable()
            if self._channel_context and self._channel_context['key'] == key:
                event.Skip()
                return
            # Arrow navigation should not launch an extractor for every row
            # passed on the way to the channel the user actually wants.
            request_seq = self._begin_browse()
            self._btn_view_videos.Enable()
            self._search_results = []
            self._results_list.DeleteAllItems()
            self._set_status(f"Status: Loading videos for '{channel['title']}'...")
            self._channel_selection_timer = threading.Timer(
                0.25, call_after_safe, args=(self, self._open_debounced_channel, request_seq, index))
            self._channel_selection_timer.daemon = True
            self._channel_selection_timer.start()
        event.Skip()

    def _open_debounced_channel(self, request_seq: int, index: int) -> None:
        if request_seq == self._browse_request_seq:
            self._channel_selection_timer = None
            self._open_subscribed_channel(index)

    def _on_subscribe(self, event: wx.CommandEvent) -> None:
        item = self._get_selected_video()
        if not item:
            wx.MessageBox("Select a video, channel, or playlist first.", "No Selection",
                         wx.OK | wx.ICON_WARNING)
            return
        channel_id = item.get('channel_id') or (item.get('id') if self._result_type == "channel" else None)
        channel_url = item.get('channel_url') or item.get('uploader_url') or ""
        channel_title = item.get('channel') or item.get('uploader') or (
            item.get('title') if self._result_type == "channel" else "Unknown Channel"
        )
        if not channel_id or not channel_url:
            wx.MessageBox("Could not determine the channel for this item.", "Subscribe",
                         wx.OK | wx.ICON_WARNING)
            return
        from radiomaster.database.repository import YouTubeChannelRepository
        YouTubeChannelRepository(self._db).add(channel_id, channel_title, channel_url)
        self._load_channels()
        wx.MessageBox(f"Subscribed to '{channel_title}'.", "Subscribed", wx.OK | wx.ICON_INFORMATION)

    def _on_unsubscribe(self, event: wx.CommandEvent) -> None:
        idx = self._channels_list.GetFirstSelected()
        if idx == wx.NOT_FOUND or idx >= len(self._channel_data):
            wx.MessageBox("Select a subscribed channel first.", "No Selection", wx.OK | wx.ICON_WARNING)
            return
        channel = self._channel_data[idx]
        if wx.MessageBox(
            f"Unsubscribe from '{channel.get('title', 'this channel')}'?",
            "Unsubscribe", wx.YES_NO | wx.ICON_QUESTION,
        ) != wx.YES:
            return
        from radiomaster.database.repository import YouTubeChannelRepository
        YouTubeChannelRepository(self._db).remove(channel['channel_id'])
        self._load_channels()

    def _on_play_url(self, event: wx.CommandEvent) -> None:
        """Play a YouTube URL.

        This used to hand the raw pasted URL (a YouTube webpage URL,
        not an actual media stream) straight to the player -- it never
        actually worked for a real youtube.com/watch link at all, only
        for a URL that already happened to be a direct playable stream.
        Now resolved through yt-dlp first, same as picking a search
        result, off the UI thread, with the real duration fetched too
        (see _on_play's comment for why that matters -- without it,
        closing the video window just replays it from the start
        forever)."""
        dlg = wx.TextEntryDialog(self, "Enter YouTube URL:", "Play YouTube Video")
        if dlg.ShowModal() == wx.ID_OK:
            url = dlg.GetValue().strip()
            if url:
                self._engine.stop(wait=False)
                self._playback_generation_at_request = self._engine.playback_generation
                self._set_status(f"Status: Resolving stream for '{url}'...")
                self._play_request_seq += 1
                seq = self._play_request_seq
                self._current_source_url = url
                self._stream_rejected_retried = False

                def worker():
                    self._resolve_and_play(url, url, 0.0, seq)

                import threading
                threading.Thread(target=worker, daemon=True).start()
        dlg.Destroy()

    def _on_play(self, event: wx.CommandEvent) -> None:
        """Play the selected video.

        Resolving the real stream URL (a yt-dlp process that has to
        contact YouTube) used to run right on the UI thread -- same
        class of freeze as the search button (see _on_search), just
        shorter since it's one video instead of twenty results.
        """
        if self._result_type == "channel":
            self._open_selected_channel()
            return
        if self._result_type == "playlist":
            self._open_selected_playlist()
            return
        video = self._get_selected_video()
        if not video:
            wx.MessageBox("Please select a video first.", "No Selection", wx.OK | wx.ICON_WARNING)
            return
        video_url = video.get('url') or video.get('webpage_url') or ""
        title = video.get('title', 'YouTube Video')
        # The engine reads duration == 0.0 as "this is an unbounded live
        # stream" and, with Settings > Radio > Auto-reconnect on (the
        # default), reconnects on ANY natural end instead of treating it
        # as finished -- including the process ending because the video
        # window was simply closed. A regular YouTube video is never
        # actually unbounded; search/playlist results already carry a
        # real duration (in seconds) straight from yt-dlp, so pass it
        # through. Without this, closing the video window just replayed
        # it from the start every time, over and over, with quitting the
        # whole app the only way out -- the exact same bug already fixed
        # for podcast episodes (v1.1.18), just never ported to video.
        duration = float(video.get('duration') or 0.0)
        self._engine.stop(wait=False)
        self._playback_generation_at_request = self._engine.playback_generation
        self._set_status(f"Status: Resolving stream for '{title}'...")
        self._play_request_seq += 1
        seq = self._play_request_seq
        self._current_source_url = video_url
        self._current_source_title = title
        self._current_source_duration = duration
        self._stream_rejected_retried = False
        self._video_info_seq += 1
        self._publish_video_info(video)

        def worker():
            self._resolve_and_play(video_url, title, duration, seq)

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _apply_play_result(self, stream_url: str | None, title: str,
                            duration: float = 0.0, seq: int = 0,
                            http_headers: dict | None = None,
                            is_temp_file: bool = False,
                            video_info: dict | None = None, error: str = "") -> None:
        if ((seq and seq != self._play_request_seq)
                or (self._playback_generation_at_request is not None
                    and self._playback_generation_at_request != self._engine.playback_generation)):
            # A newer play request has started (or finished) since this
            # one was kicked off -- e.g. two quick double-clicks each
            # resolving their own stream in the background. Applying
            # this one now would silently replace whatever the user's
            # most recent action actually started, which is what "two
            # windows"/"a video that isn't playing" looked like: an
            # older, already-superseded resolution winning the race and
            # restarting playback right after the real one had already
            # begun.
            if is_temp_file and stream_url:
                try:
                    import os
                    os.remove(stream_url)
                except OSError:
                    pass
            return
        if not stream_url:
            message = "Unable to resolve a playable stream for the selected video."
            if error:
                message += "\n\n" + error
            self._set_status(f"Status: {error or message}")
            wx.MessageBox(message, "YouTube Playback Error", wx.OK | wx.ICON_ERROR, parent=self)
            return
        if video_info:
            self._publish_video_info(video_info)
        self._current_source_title = title
        self._current_source_duration = duration
        # If we're switching to a new source, drop any previous temp file.
        if not is_temp_file:
            self._cleanup_temp_file()
        else:
            self._temp_playback_file = stream_url
        options = {}
        if (video_info or {}).get("video_inputs"):
            options["video_inputs"] = video_info["video_inputs"]
        self._engine.play(stream_url, title=title, is_video=True, duration=duration,
                          http_headers=http_headers, **options)
        self._playback_generation_at_request = self._engine.playback_generation
        self._set_status(f"Status: Playing '{title}'")

    def _on_stream_rejected(self) -> None:
        """PlaybackEngine detected YouTube rejected (HTTP 403) the
        resolved stream URL for the video currently playing -- see its
        own on_stream_rejected docstring for why that happens and why
        this engine can't just retry itself. Fires from a background
        thread, so marshal back to the UI thread before touching
        anything wx."""
        wx.CallAfter(self._retry_after_stream_rejection)

    def _retry_after_stream_rejection(self) -> None:
        if self._playback_generation_at_request != self._engine.playback_generation:
            return
        if not self._current_source_url or self._stream_rejected_retried:
            if self._stream_rejected_retried:
                wx.MessageBox(
                    "YouTube rejected this video's stream again after retrying once. "
                    "Try again in a moment.", "Playback Error", wx.OK | wx.ICON_ERROR)
            return
        self._stream_rejected_retried = True
        url, title, duration = (
            self._current_source_url, self._current_source_title, self._current_source_duration
        )
        self._set_status(f"Status: Retrying '{title}'...")
        self._play_request_seq += 1
        seq = self._play_request_seq

        def worker():
            self._resolve_and_play(url, title, duration, seq)

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _on_load_playlist(self, event: wx.CommandEvent) -> None:
        """Load a YouTube playlist and show its entries, off the UI
        thread (same reasoning as _on_search -- yt-dlp has to actually
        fetch the whole playlist listing before returning anything)."""
        dlg = wx.TextEntryDialog(self, "Enter playlist URL:", "Load Playlist")
        if dlg.ShowModal() == wx.ID_OK:
            url = dlg.GetValue().strip()
            if url:
                request_seq = self._begin_browse()
                self._set_status(f"Status: Loading playlist...")
                self._btn_playlist.Disable()

                def worker():
                    from radiomaster.services.youtube_dl import YouTubeService
                    service = YouTubeService()
                    entries = service.get_playlist_entries(url)
                    call_after_safe(self, self._apply_playlist_entries, entries, request_seq)

                import threading
                threading.Thread(target=worker, daemon=True).start()
        dlg.Destroy()

    def _apply_playlist_entries(self, entries: list[dict], request_seq: int | None = None) -> None:
        if request_seq is not None and request_seq != self._browse_request_seq:
            return
        self._btn_playlist.Enable()
        if not entries:
            wx.MessageBox("No entries found in playlist.", "Playlist Empty", wx.OK | wx.ICON_WARNING)
            return
        self._result_type = "video"
        self._set_results_columns_for_type("video")
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
        if self._result_type != "video":
            wx.MessageBox(
                "Open this channel or playlist first (Enter/double-click), then select "
                "an actual video to download.", "Cannot Download", wx.OK | wx.ICON_WARNING)
            return
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
        from radiomaster.utils.paths import get_downloads_dir
        # get_downloads_dir(), not a raw config.get() -- self-heals a
        # value saved once while running installed back to the
        # correct portable default instead of writing into a stale
        # Music-folder path forever after. See its own docstring.
        output_dir = get_downloads_dir()
        download_id = repo.add(video_url, title=video.get('title', 'YouTube Video'), format=quality,
                                output_dir=output_dir)
        app = wx.GetApp()
        if hasattr(app, 'download_manager') and hasattr(app.download_manager, 'add_download'):
            app.download_manager.add_download(
                download_id, video_url, output_dir=output_dir,
                title=video.get('title', 'YouTube Video'),
                format=quality,
            )
        wx.MessageBox(f"Video download added to queue: {video.get('title', '')} ({quality})", "Download Added", wx.OK | wx.ICON_INFORMATION)

    def _on_download_audio(self, event: wx.CommandEvent) -> None:
        """Download audio only."""
        if self._result_type != "video":
            wx.MessageBox(
                "Open this channel or playlist first (Enter/double-click), then select "
                "an actual video to download.", "Cannot Download", wx.OK | wx.ICON_WARNING)
            return
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
        from radiomaster.utils.paths import get_downloads_dir
        output_dir = get_downloads_dir()
        download_id = repo.add(video_url, title=video.get('title', 'YouTube Audio'), format=audio_fmt,
                                quality=quality_setting, output_dir=output_dir, extract_audio=True)
        app = wx.GetApp()
        if hasattr(app, 'download_manager') and hasattr(app.download_manager, 'add_download'):
            app.download_manager.add_download(
                download_id, video_url, output_dir=output_dir,
                title=video.get('title', 'YouTube Audio'),
                format=audio_fmt, extract_audio=True, audio_quality=audio_quality,
            )
        wx.MessageBox(f"Audio download added to queue: {video.get('title', '')} ({audio_fmt})", "Download Added", wx.OK | wx.ICON_INFORMATION)
