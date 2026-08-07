"""Podcast tab panel with subscription management and episode list.

Uses three linked listboxes:
    1. Categories (All, Custom, Directory)
    2. Podcasts (feeds in the selected category)
    3. Episodes (episodes of the selected podcast)
"""

import wx
from typing import Any
from radiomaster.database.connection import DatabaseManager
from radiomaster.engine.playback_engine import PlaybackEngine
from radiomaster.utils.accessibility import set_accessible_name, set_search_ctrl_accessible_name


class PodcastPanel(wx.Panel):
    """Panel for managing and playing podcasts."""

    def __init__(self, parent: wx.Window, db: DatabaseManager, engine: PlaybackEngine) -> None:
        super().__init__(parent)
        self._db = db
        self._engine = engine
        self._current_episode_id: int | None = None
        self._resume_position: float = 0.0
        self._setup_ui()

        # Periodically persist play progress for the currently-playing
        # episode, mirroring AudiobookPanel's resume-from-last-position.
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
        if self._current_episode_id is not None and self._engine.state in ("playing", "paused"):
            from radiomaster.database.repository import EpisodeRepository
            EpisodeRepository(self._db).update_position(
                self._current_episode_id, self._engine.position
            )

    def _setup_ui(self) -> None:
        """Create the podcast panel layout with three listboxes."""
        main_sizer = wx.BoxSizer(wx.HORIZONTAL)

        # --- Column 1: Category listbox ---
        col1 = wx.Panel(self)
        col1_sizer = wx.BoxSizer(wx.VERTICAL)
        col1_sizer.Add(wx.StaticText(col1, label="Category"), 0, wx.ALL, 4)
        self._category_list = wx.ListBox(col1, style=wx.LB_SINGLE)
        set_accessible_name(self._category_list, "Podcast Category")
        for cat in ["All Podcasts", "Custom Feeds", "Directory"]:
            self._category_list.Append(cat)
        col1_sizer.Add(self._category_list, 1, wx.EXPAND | wx.ALL, 4)
        col1.SetSizer(col1_sizer)
        main_sizer.Add(col1, 1, wx.EXPAND | wx.RIGHT, 4)

        # --- Column 2: Podcast listbox ---
        col2 = wx.Panel(self)
        col2_sizer = wx.BoxSizer(wx.VERTICAL)
        col2_sizer.Add(wx.StaticText(col2, label="Podcasts"), 0, wx.ALL, 4)
        self._podcast_list = wx.ListBox(col2, style=wx.LB_SINGLE)
        set_accessible_name(self._podcast_list, "Podcasts")
        col2_sizer.Add(self._podcast_list, 1, wx.EXPAND | wx.ALL, 4)
        col2.SetSizer(col2_sizer)
        main_sizer.Add(col2, 1, wx.EXPAND | wx.RIGHT, 4)

        # --- Column 3: Episode listbox ---
        col3 = wx.Panel(self)
        col3_sizer = wx.BoxSizer(wx.VERTICAL)
        col3_sizer.Add(wx.StaticText(col3, label="Episodes"), 0, wx.ALL, 4)
        self._episode_list = wx.ListBox(col3, style=wx.LB_SINGLE)
        set_accessible_name(self._episode_list, "Episodes")
        col3_sizer.Add(self._episode_list, 1, wx.EXPAND | wx.ALL, 4)

        # Buttons
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self._btn_play = wx.Button(col3, label="Play Episode")
        set_accessible_name(self._btn_play, "Play Episode")
        btn_sizer.Add(self._btn_play, 1, wx.RIGHT, 2)
        self._btn_download = wx.Button(col3, label="Download Episode")
        set_accessible_name(self._btn_download, "Download Episode")
        btn_sizer.Add(self._btn_download, 1, wx.LEFT, 2)
        col3_sizer.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 4)

        btn2_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self._btn_add_feed = wx.Button(col3, label="Add RSS Feed...")
        set_accessible_name(self._btn_add_feed, "Add RSS Feed")
        btn2_sizer.Add(self._btn_add_feed, 1, wx.RIGHT, 2)
        self._btn_sync_gpodder = wx.Button(col3, label="Sync gpodder.net")
        set_accessible_name(self._btn_sync_gpodder, "Sync gpodder.net")
        btn2_sizer.Add(self._btn_sync_gpodder, 1, wx.LEFT, 2)
        col3_sizer.Add(btn2_sizer, 0, wx.EXPAND | wx.ALL, 4)

        opml_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self._btn_import_opml = wx.Button(col3, label="Import OPML...")
        set_accessible_name(self._btn_import_opml, "Import OPML")
        opml_sizer.Add(self._btn_import_opml, 1, wx.RIGHT, 2)
        self._btn_export_opml = wx.Button(col3, label="Export OPML...")
        set_accessible_name(self._btn_export_opml, "Export OPML")
        opml_sizer.Add(self._btn_export_opml, 1, wx.LEFT, 2)
        col3_sizer.Add(opml_sizer, 0, wx.EXPAND | wx.ALL, 4)

        # Directory search bar (hidden by default, shown when Directory is selected)
        dir_sizer = wx.BoxSizer(wx.HORIZONTAL)
        dir_sizer.Add(wx.StaticText(col3, label="Search Directory:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self._dir_search = wx.SearchCtrl(col3, style=wx.TE_PROCESS_ENTER)
        set_search_ctrl_accessible_name(self._dir_search, "Search Podcast Directory")
        self._dir_search.ShowSearchButton(True)
        dir_sizer.Add(self._dir_search, 1, wx.EXPAND)
        col3_sizer.Add(dir_sizer, 0, wx.EXPAND | wx.ALL, 4)

        col3.SetSizer(col3_sizer)
        main_sizer.Add(col3, 2, wx.EXPAND)

        self.SetSizer(main_sizer)

        # Bind events
        self._category_list.Bind(wx.EVT_LISTBOX, self._on_category_select)
        self._podcast_list.Bind(wx.EVT_LISTBOX, self._on_podcast_select)
        self._episode_list.Bind(wx.EVT_LISTBOX_DCLICK, self._on_play)
        self._btn_play.Bind(wx.EVT_BUTTON, self._on_play)
        self._btn_download.Bind(wx.EVT_BUTTON, self._on_download)
        self._btn_add_feed.Bind(wx.EVT_BUTTON, self._on_add_feed)
        self._btn_sync_gpodder.Bind(wx.EVT_BUTTON, self._on_sync_gpodder)
        self._btn_import_opml.Bind(wx.EVT_BUTTON, self._on_import_opml)
        self._btn_export_opml.Bind(wx.EVT_BUTTON, self._on_export_opml)
        self._dir_search.Bind(wx.EVT_SEARCHCTRL_SEARCH_BTN, self._on_directory_search)
        self._dir_search.Bind(wx.EVT_TEXT_ENTER, self._on_directory_search)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------
    def _on_category_select(self, event: wx.CommandEvent) -> None:
        """Populate the podcast list when a category is selected."""
        from radiomaster.database.repository import PodcastRepository
        repo = PodcastRepository(self._db)
        self._podcast_list.Clear()
        self._episode_list.Clear()
        self._podcast_data: list[dict[str, Any]] = []

        cat = self._category_list.GetStringSelection()
        if cat == "All Podcasts":
            for p in repo.get_all():
                self._podcast_list.Append(p.get("title", "Unknown"))
                self._podcast_data.append(p)
        elif cat == "Custom Feeds":
            for p in repo.get_all():
                if p.get("is_custom"):
                    self._podcast_list.Append(p.get("title", "Unknown"))
                    self._podcast_data.append(p)
        elif cat == "Directory":
            self._podcast_list.Clear()
            self._podcast_data = []
            self._podcast_list.Append("(Search iTunes/Apple Podcasts directory)")

    def _on_directory_search(self, event: wx.Event) -> None:
        """Search the iTunes/Apple Podcasts directory."""
        query = self._dir_search.GetValue().strip()
        if not query:
            return
        from radiomaster.services.podcast_directory import PodcastDirectory
        results = PodcastDirectory.search(query)
        self._podcast_list.Clear()
        self._podcast_data = []
        for r in results:
            display = f"{r.get('title', 'Unknown')}  [{r.get('author', '')}]"
            self._podcast_list.Append(display)
            self._podcast_data.append(r)

    def _on_sync_gpodder(self, event: wx.CommandEvent) -> None:
        """Sync subscriptions with gpodder.net."""
        from radiomaster.utils.config import ConfigManager
        config = ConfigManager.get_instance()
        username = config.get("podcasts.gpodder_username", default="")
        if not username:
            wx.MessageBox("Please configure your gpodder.net username in Settings first.",
                         "gpodder.net Sync", wx.OK | wx.ICON_WARNING)
            return
        from radiomaster.services.gpodder_sync import GpodderSync
        from radiomaster.database.repository import PodcastRepository
        import threading
        self._btn_sync_gpodder.Disable()
        self._btn_sync_gpodder.SetLabel("Syncing...")
        def _do_sync():
            try:
                sync = GpodderSync(username)
                repo = PodcastRepository(self._db)
                subs = sync.get_subscriptions()
                count = 0
                for s in subs:
                    existing = repo.get_by_feed_url(s.get("url", ""))
                    if not existing:
                        repo.add(s.get("url", ""), title=s.get("title", ""), is_custom=True)
                        count += 1
                wx.CallAfter(wx.MessageBox, f"Synced {count} new subscriptions from gpodder.net.",
                            "Sync Complete", wx.OK | wx.ICON_INFORMATION)
            except Exception as e:
                wx.CallAfter(wx.MessageBox, f"gpodder.net sync failed: {e}",
                            "Sync Error", wx.OK | wx.ICON_ERROR)
            finally:
                wx.CallAfter(self._btn_sync_gpodder.Enable)
                wx.CallAfter(self._btn_sync_gpodder.SetLabel, "Sync gpodder.net")
        threading.Thread(target=_do_sync, daemon=True).start()

    def _on_download(self, event: wx.CommandEvent) -> None:
        """Download the selected episode for offline playback."""
        idx = self._episode_list.GetSelection()
        if idx < 0 or not hasattr(self, '_episode_data') or idx >= len(self._episode_data):
            wx.MessageBox("Please select an episode first.", "No Selection", wx.OK | wx.ICON_WARNING)
            return
        ep = self._episode_data[idx]
        url = ep.get("audio_url", "")
        if not url:
            wx.MessageBox("This episode has no audio URL.", "Cannot Download", wx.OK | wx.ICON_WARNING)
            return
        from radiomaster.database.repository import DownloadRepository
        repo = DownloadRepository(self._db)
        repo.add(url, title=ep.get("title", "Podcast Episode"), source_type="podcast")
        wx.MessageBox(f"Download added to queue: {ep.get('title', '')}", "Download Added",
                     wx.OK | wx.ICON_INFORMATION)

    def _on_podcast_select(self, event: wx.CommandEvent) -> None:
        """Populate the episode list when a podcast is selected."""
        from radiomaster.database.repository import PodcastRepository
        repo = PodcastRepository(self._db)
        self._episode_list.Clear()
        self._episode_data: list[dict[str, Any]] = []

        idx = self._podcast_list.GetSelection()
        if idx < 0 or not hasattr(self, '_podcast_data') or idx >= len(self._podcast_data):
            return

        podcast = self._podcast_data[idx]
        podcast_id = podcast.get("id")
        if podcast_id:
            for ep in repo.get_episodes(podcast_id):
                display = f"{ep.get('title', 'Unknown')}  [{ep.get('published_date', '')}]"
                self._episode_list.Append(display)
                self._episode_data.append(ep)

    def _on_play(self, event: wx.Event) -> None:
        """Play the selected episode, resuming from saved position if any."""
        idx = self._episode_list.GetSelection()
        if idx < 0 or not hasattr(self, '_episode_data') or idx >= len(self._episode_data):
            return
        ep = self._episode_data[idx]
        url = ep.get("audio_url", "")
        if not url:
            return

        # Save progress on whatever was playing before switching episodes.
        self._save_position()

        self._current_episode_id = ep.get("id")
        resume_position = ep.get("play_position") or 0.0

        if resume_position > 0:
            if wx.MessageBox(
                f"Resume from your last position in this episode?",
                "Resume Playback", wx.YES_NO | wx.ICON_QUESTION,
            ) != wx.YES:
                resume_position = 0.0

        self._engine.play(url, title=ep.get("title", ""))

        if resume_position > 0:
            import threading
            threading.Timer(1.0, lambda: self._engine.seek(resume_position)).start()

        if self._current_episode_id is not None:
            from radiomaster.database.repository import EpisodeRepository
            EpisodeRepository(self._db).mark_played(self._current_episode_id, True)

    def _on_add_feed(self, event: wx.CommandEvent) -> None:
        """Add a podcast RSS feed and parse it immediately."""
        dlg = wx.TextEntryDialog(self, "Enter RSS feed URL:", "Add Podcast Feed")
        if dlg.ShowModal() == wx.ID_OK:
            url = dlg.GetValue().strip()
            if url:
                from radiomaster.database.repository import PodcastRepository
                from radiomaster.services.podcast_manager import PodcastManager
                import threading

                repo = PodcastRepository(self._db)
                repo.add(url, is_custom=True)

                # Parse feed in background thread
                def _parse():
                    try:
                        # parse_feed() returns {"title":..., "episodes":[...], ...} or
                        # None on failure -- it does NOT return the episode list directly.
                        feed_data = PodcastManager.parse_feed(url)
                        episodes = feed_data.get("episodes", []) if feed_data else []
                        if episodes:
                            for ep in episodes:
                                self._db.execute(
                                    """INSERT OR IGNORE INTO episodes
                                    (podcast_id, guid, title, description, duration, published_date, audio_url)
                                    VALUES ((SELECT id FROM podcasts WHERE feed_url = ?), ?, ?, ?, ?, ?, ?)""",
                                    (url, ep.get("guid", ""), ep.get("title", ""),
                                     ep.get("description", ""), ep.get("duration", 0),
                                     ep.get("published_date", ""), ep.get("audio_url", "")),
                                )
                            self._db.commit()
                            wx.CallAfter(wx.MessageBox,
                                f"Feed parsed: {len(episodes)} episodes found.",
                                "Feed Added", wx.OK | wx.ICON_INFORMATION)
                        elif feed_data is None:
                            wx.CallAfter(wx.MessageBox,
                                "Feed URL saved but the feed could not be parsed.",
                                "Feed Added", wx.OK | wx.ICON_WARNING)
                        else:
                            wx.CallAfter(wx.MessageBox,
                                "Feed URL saved but no episodes found.",
                                "Feed Added", wx.OK | wx.ICON_INFORMATION)
                    except Exception as e:
                        wx.CallAfter(wx.MessageBox,
                            f"Feed saved but parsing failed: {e}",
                            "Parse Warning", wx.OK | wx.ICON_WARNING)

                threading.Thread(target=_parse, daemon=True).start()
        dlg.Destroy()

    def _on_import_opml(self, event: wx.CommandEvent) -> None:
        """Import OPML file with podcast subscriptions."""
        dlg = wx.FileDialog(self, "Import OPML", wildcard="OPML files (*.opml;*.xml)|*.opml;*.xml",
                            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        if dlg.ShowModal() == wx.ID_OK:
            opml_path = dlg.GetPath()
            try:
                import xml.etree.ElementTree as ET
                from radiomaster.database.repository import PodcastRepository

                repo = PodcastRepository(self._db)
                tree = ET.parse(opml_path)
                root = tree.getroot()

                imported_count = 0
                failed_count = 0

                for outline in root.iter('outline'):
                    xml_url = outline.get('xmlUrl')
                    if xml_url:
                        try:
                            existing = repo.get_by_feed_url(xml_url)
                            if not existing:
                                title = outline.get('text', outline.get('title', 'Unknown'))
                                repo.add(xml_url, title=title, is_custom=True)
                                imported_count += 1
                        except Exception:
                            failed_count += 1

                wx.MessageBox(
                    f"OPML import complete!\n\nImported: {imported_count} feeds\nFailed: {failed_count} feeds",
                    "Import Complete",
                    wx.OK | wx.ICON_INFORMATION
                )
            except Exception as e:
                wx.MessageBox(f"Error importing OPML: {str(e)}", "Import Error", wx.OK | wx.ICON_ERROR)
        dlg.Destroy()

    def _on_export_opml(self, event: wx.CommandEvent) -> None:
        """Export podcast subscriptions to OPML file."""
        dlg = wx.FileDialog(self, "Export OPML", wildcard="OPML files (*.opml)|*.opml",
                            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
        if dlg.ShowModal() == wx.ID_OK:
            opml_path = dlg.GetPath()
            try:
                import xml.etree.ElementTree as ET
                from radiomaster.database.repository import PodcastRepository

                repo = PodcastRepository(self._db)
                podcasts = repo.get_all()

                opml = ET.Element('opml', version='2.0')
                head = ET.SubElement(opml, 'head')
                title = ET.SubElement(head, 'title')
                title.text = 'RadioMaster+ Podcast Subscriptions'

                body = ET.SubElement(opml, 'body')

                exported_count = 0
                for podcast in podcasts:
                    outline = ET.SubElement(body, 'outline')
                    outline.set('text', podcast.get('title', 'Unknown'))
                    outline.set('title', podcast.get('title', 'Unknown'))
                    outline.set('xmlUrl', podcast.get('feed_url', ''))
                    outline.set('type', 'rss')
                    if podcast.get('website_url'):
                        outline.set('htmlUrl', podcast.get('website_url'))
                    if podcast.get('author'):
                        outline.set('owner', podcast.get('author'))
                    exported_count += 1

                tree = ET.ElementTree(opml)
                ET.indent(tree, space="  ")
                tree.write(opml_path, encoding='utf-8', xml_declaration=True)

                wx.MessageBox(
                    f"OPML export complete!\n\nExported: {exported_count} feeds\nSaved to: {opml_path}",
                    "Export Complete",
                    wx.OK | wx.ICON_INFORMATION
                )
            except Exception as e:
                wx.MessageBox(f"Error exporting OPML: {str(e)}", "Export Error", wx.OK | wx.ICON_ERROR)
        dlg.Destroy()
