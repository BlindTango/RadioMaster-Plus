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
        # Which kind of entry _search_results currently holds -- "video",
        # "channel", or "playlist". Drives both how the results list's
        # columns are labeled/filled and what Enter/double-click does
        # (play a video vs. drill into a channel's videos vs. load a
        # playlist's entries) -- and guards Download/Download Audio/Play
        # from being handed a channel or playlist URL by mistake (yt-dlp
        # would happily try to download an entire channel's uploads).
        self._result_type = "video"
        self._channel_data: list[dict] = []
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
        self._engine.on_stream_rejected(self._on_stream_rejected)
        self._setup_ui()
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)

    def _on_destroy(self, event: wx.WindowDestroyEvent) -> None:
        """Clean up any temp playback file when the panel is destroyed."""
        if event.GetEventObject() is self:
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
        """Resolve a playable stream for *url* and start playback.

        Runs on a worker thread. First tries to resolve a single muxed
        stream URL (the fast path -- ffplay streams it directly). Modern
        YouTube no longer serves a single muxed stream for most videos
        (it splits video-only and audio-only adaptive streams), so when
        that returns nothing, falls back to downloading the video to a
        temp file via yt-dlp (which merges the two) and plays the local
        file instead. The temp file is tracked in _temp_playback_file so
        it can be cleaned up later.

        *stream*, when given, is an already-resolved get_stream_info()
        result (e.g. from _on_play_url, which needs it for the title/
        duration) -- avoids a second redundant yt-dlp call."""
        from radiomaster.services.youtube_dl import YouTubeService
        service = YouTubeService()
        if stream is None:
            stream = service.get_stream_info(url)
        stream_url = (stream or {}).get('url')
        headers = (stream or {}).get('http_headers')
        if stream_url:
            wx.CallAfter(self._apply_play_result, stream_url, title, duration, seq, headers)
            return
        # No single muxed stream -- download to a temp file and play that.
        self._set_status(f"Status: Downloading '{title}' for playback...")
        tmp_path = service.download_to_temp(url)
        wx.CallAfter(self._apply_play_result, tmp_path, title, duration, seq, None,
                     is_temp_file=True)

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
        self._btn_playlist.Bind(wx.EVT_BUTTON, self._on_load_playlist)
        self._btn_download.Bind(wx.EVT_BUTTON, self._on_download)
        self._btn_download_audio.Bind(wx.EVT_BUTTON, self._on_download_audio)
        self._btn_subscribe.Bind(wx.EVT_BUTTON, self._on_subscribe)
        self._btn_unsubscribe.Bind(wx.EVT_BUTTON, self._on_unsubscribe)
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
        self._channels_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_channel_activated)

        self._load_channels()

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

        self._results_list.DeleteAllItems()
        self._search_results = []
        self._btn_search.Disable()
        self._set_status(f"Searching YouTube for '{query}'...")

        def worker():
            from radiomaster.services.youtube_dl import YouTubeService
            try:
                service = YouTubeService()
                results = service.search(query, max_results=20, search_type=search_type)
            except Exception as e:
                wx.CallAfter(self._on_search_failed, str(e))
                return
            wx.CallAfter(self._apply_search_results, results, query, search_type)

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

    def _on_search_failed(self, message: str) -> None:
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
                               search_type: str = "video") -> None:
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

    def _on_result_activated(self, event: wx.CommandEvent) -> None:
        """Enter/double-click on a results-list row: plays a video result
        directly (unchanged), but drills into a channel's videos or a
        playlist's entries instead of trying to play a channel/playlist
        URL as if it were a stream."""
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
        self._load_channel_videos(channel_url, title)

    def _open_selected_playlist(self) -> None:
        playlist = self._get_selected_video()
        if not playlist:
            return
        playlist_url = playlist.get('url') or playlist.get('webpage_url') or ""
        if not playlist_url:
            wx.MessageBox("Could not determine this playlist's URL.", "Error", wx.OK | wx.ICON_ERROR)
            return
        self._set_status(f"Status: Loading playlist '{playlist.get('title', '')}'...")

        def worker():
            from radiomaster.services.youtube_dl import YouTubeService
            service = YouTubeService()
            entries = service.get_playlist_entries(playlist_url)
            wx.CallAfter(self._apply_playlist_entries, entries)

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _load_channel_videos(self, channel_url: str, title: str) -> None:
        self._set_status(f"Status: Loading videos for '{title}'...")

        def worker():
            from radiomaster.services.youtube_dl import YouTubeService
            service = YouTubeService()
            entries = service.get_channel_videos(channel_url)
            wx.CallAfter(self._apply_search_results, entries, title, "video")

        import threading
        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------
    # Channel subscriptions -- mirrors PodcastPanel's Subscribe/
    # Unsubscribe pattern. Any result (video, channel, or playlist) can
    # be subscribed from, not only a Channels-type search result: every
    # yt-dlp entry already carries its channel_id/channel_url/channel
    # regardless of which of the three it itself is.
    # ------------------------------------------------------------------
    def _load_channels(self) -> None:
        from radiomaster.database.repository import YouTubeChannelRepository
        self._channels_list.DeleteAllItems()
        self._channel_data = YouTubeChannelRepository(self._db).get_all()
        for i, channel in enumerate(self._channel_data):
            self._channels_list.InsertItem(i, channel.get('title', 'Unknown'))

    def _on_channel_activated(self, event: wx.CommandEvent) -> None:
        idx = self._channels_list.GetFirstSelected()
        if idx == wx.NOT_FOUND or idx >= len(self._channel_data):
            return
        channel = self._channel_data[idx]
        url = channel.get('url', '')
        if not url:
            return
        self._load_channel_videos(url, channel.get('title', 'Channel'))

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
                self._set_status(f"Status: Resolving stream for '{url}'...")
                self._play_request_seq += 1
                seq = self._play_request_seq
                self._current_source_url = url
                self._stream_rejected_retried = False

                def worker():
                    from radiomaster.services.youtube_dl import YouTubeService
                    service = YouTubeService()
                    stream = service.get_stream_info(url)
                    title = (stream or {}).get('title') or url
                    duration = (stream or {}).get('duration', 0.0)
                    self._current_source_title = title
                    self._current_source_duration = duration
                    self._resolve_and_play(url, title, duration, seq, stream)

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
        self._set_status(f"Status: Resolving stream for '{title}'...")
        self._play_request_seq += 1
        seq = self._play_request_seq
        self._current_source_url = video_url
        self._current_source_title = title
        self._current_source_duration = duration
        self._stream_rejected_retried = False

        def worker():
            self._resolve_and_play(video_url, title, duration, seq)

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _apply_play_result(self, stream_url: str | None, title: str,
                            duration: float = 0.0, seq: int = 0,
                            http_headers: dict | None = None,
                            is_temp_file: bool = False) -> None:
        if seq and seq != self._play_request_seq:
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
            wx.MessageBox("Unable to resolve a playable stream for the selected video.",
                         "Error", wx.OK | wx.ICON_ERROR)
            return
        # If we're switching to a new source, drop any previous temp file.
        if not is_temp_file:
            self._cleanup_temp_file()
        else:
            self._temp_playback_file = stream_url
        self._engine.play(stream_url, title=title, is_video=True, duration=duration,
                          http_headers=http_headers)
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
