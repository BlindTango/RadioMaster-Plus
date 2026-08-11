"""Podcast tab panel with subscription management and episode list.

Laid out the same way as the Radio tab (RadioPanel): a search row (label +
textbox + button) at the top -- always visible, not buried in a column or
gated behind picking a category first -- followed by a categorized browser
below it. Uses three linked lists:
    1. Categories (Subscriptions, Custom, Directory)
    2. Podcasts (feeds in the selected category, or live search results
       when the Directory category is showing what was just searched)
    3. Episodes (episodes of the selected podcast)

All three are wx.ListCtrl (report view), the same native control RadioPanel
and DownloadsPanel already use -- not wx.ListBox. A plain wx.ListBox's
per-item text isn't reliably exposed to screen readers on Windows (NVDA
read every row as a bare "list item" with no name); ListCtrl in report
view is the control this codebase already establishes for anything that
needs to actually be readable.

Searching queries every configured podcast directory (see
services/podcast_directory.py's search_all()) and shows the results in the
Podcasts list; picking one there is just browsing until Subscribe (button,
context menu, or double-click/Enter) actually adds it -- mirroring
Radio's search-then-activate-to-play, except a podcast has to be
subscribed before its episodes can be browsed/played at all.
"""

import logging
import wx
from typing import Any, Optional
from radiomaster.database.connection import DatabaseManager
from radiomaster.engine.playback_engine import PlaybackEngine
from radiomaster.utils.wx_safe import call_after_safe
from radiomaster.utils.accessibility import set_accessible_name, context_menu_pos

logger = logging.getLogger("radiomaster")


class PodcastPanel(wx.Panel):
    """Panel for managing and playing podcasts."""

    def __init__(self, parent: wx.Window, db: DatabaseManager, engine: PlaybackEngine) -> None:
        super().__init__(parent)
        self._db = db
        self._engine = engine
        self._current_episode_id: int | None = None
        self._resume_position: float = 0.0
        # Which episode row is actually playing (vs merely selected) and
        # its URL -- see try_auto_advance().
        self._current_playing_index: int | None = None
        self._last_played_url: str = ""
        # True while the Podcasts list (column 2) is showing live directory
        # search results rather than subscribed podcasts from the local DB
        # -- selecting a row in that state needs Subscribe, not a direct
        # episode load (search results have no local podcast id yet).
        self._viewing_search_results = False
        # Title of whichever podcast's episodes are actually loaded into
        # _episode_list right now -- set only by _load_episodes_for_index(),
        # never re-derived from _podcast_list's own selection at download
        # time. Podcast-list selection can drift away from the episode
        # list it originally populated (arrow-key browsing the list,
        # focus moving around) without ever re-firing a select event, so
        # re-reading GetFirstSelected() in _on_download() could silently
        # attribute an episode to a completely different podcast than the
        # one its own episode list belongs to -- confirmed live: episodes
        # from one show ended up filed under a different show's folder.
        self._current_podcast_title = "Unknown Podcast"
        self._search_seq = 0
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
        """Create the podcast panel layout: a Radio-tab-style search row on
        top, then three linked ListCtrls below it."""
        outer = wx.BoxSizer(wx.VERTICAL)

        # --- Search row (matches RadioPanel's search_row exactly: label +
        # textbox + button, always visible) ---
        search_label = wx.StaticText(self, label="&Search:")
        self.search_ctrl = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.search_ctrl.SetHint("Search by podcast name or topic")
        # Tabbing/clicking into the box selects whatever's already there
        # (e.g. the last search term) so typing immediately replaces it,
        # instead of having to manually clear it first for a new search.
        self.search_ctrl.Bind(wx.EVT_SET_FOCUS, self._on_search_focus)
        self.search_btn = wx.Button(self, label="&Search")

        search_row = wx.BoxSizer(wx.HORIZONTAL)
        search_row.Add(search_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        search_row.Add(self.search_ctrl, 1, wx.EXPAND | wx.RIGHT, 4)
        search_row.Add(self.search_btn, 0)
        outer.Add(search_row, 0, wx.EXPAND | wx.ALL, 6)

        main_sizer = wx.BoxSizer(wx.HORIZONTAL)

        # --- Column 1: Category list ---
        col1 = wx.Panel(self)
        col1_sizer = wx.BoxSizer(wx.VERTICAL)
        col1_sizer.Add(wx.StaticText(col1, label="Category"), 0, wx.ALL, 4)
        self._category_list = wx.ListCtrl(col1, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self._category_list.InsertColumn(0, "Category", width=180)
        set_accessible_name(self._category_list, "Podcast Category")
        for cat in ["Subscriptions", "Custom Feeds", "Directory"]:
            self._category_list.InsertItem(self._category_list.GetItemCount(), cat)
        col1_sizer.Add(self._category_list, 1, wx.EXPAND | wx.ALL, 4)
        col1.SetSizer(col1_sizer)
        main_sizer.Add(col1, 1, wx.EXPAND | wx.RIGHT, 4)

        # --- Column 2: Podcast list ---
        col2 = wx.Panel(self)
        col2_sizer = wx.BoxSizer(wx.VERTICAL)
        col2_sizer.Add(wx.StaticText(col2, label="Podcasts"), 0, wx.ALL, 4)
        self._podcast_list = wx.ListCtrl(col2, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self._podcast_list.InsertColumn(0, "Title", width=200)
        self._podcast_list.InsertColumn(1, "Author", width=140)
        self._podcast_list.InsertColumn(2, "Directory", width=120)
        set_accessible_name(self._podcast_list, "Podcasts")
        col2_sizer.Add(self._podcast_list, 1, wx.EXPAND | wx.ALL, 4)
        sub_btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self._btn_subscribe = wx.Button(col2, label="Su&bscribe")
        set_accessible_name(self._btn_subscribe, "Subscribe to selected podcast")
        sub_btn_sizer.Add(self._btn_subscribe, 1, wx.RIGHT, 2)
        self._btn_unsubscribe = wx.Button(col2, label="&Unsubscribe")
        set_accessible_name(self._btn_unsubscribe, "Unsubscribe from selected podcast")
        sub_btn_sizer.Add(self._btn_unsubscribe, 1, wx.LEFT, 2)
        col2_sizer.Add(sub_btn_sizer, 0, wx.EXPAND | wx.ALL, 4)
        col2.SetSizer(col2_sizer)
        main_sizer.Add(col2, 1, wx.EXPAND | wx.RIGHT, 4)

        # --- Column 3: Episode list ---
        col3 = wx.Panel(self)
        col3_sizer = wx.BoxSizer(wx.VERTICAL)
        col3_sizer.Add(wx.StaticText(col3, label="Episodes"), 0, wx.ALL, 4)
        self._episode_list = wx.ListCtrl(col3, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self._episode_list.InsertColumn(0, "Episode", width=260)
        self._episode_list.InsertColumn(1, "Published", width=140)
        self._episode_list.InsertColumn(2, "Duration", width=80)
        set_accessible_name(self._episode_list, "Episodes")
        col3_sizer.Add(self._episode_list, 1, wx.EXPAND | wx.ALL, 4)

        # No inline Play button here -- matches RadioPanel, which has none
        # either: Enter/double-click on the list starts playback (already
        # bound below), and the shared transport bar (NowPlayingBar) is
        # what actually controls play/pause/stop of whatever's playing.
        # A second, separate "Play" button next to that was confusing
        # (two different-looking play controls that don't do the same
        # thing) rather than actually useful.
        self._btn_download = wx.Button(col3, label="Download Episode")
        set_accessible_name(self._btn_download, "Download Episode")
        col3_sizer.Add(self._btn_download, 0, wx.EXPAND | wx.ALL, 4)

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

        col3.SetSizer(col3_sizer)
        main_sizer.Add(col3, 2, wx.EXPAND)

        outer.Add(main_sizer, 1, wx.EXPAND)
        self.SetSizer(outer)

        # Bind events
        self.search_btn.Bind(wx.EVT_BUTTON, self._on_directory_search)
        self.search_ctrl.Bind(wx.EVT_TEXT_ENTER, self._on_directory_search)
        self._category_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_category_select)
        self._podcast_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_podcast_select)
        self._podcast_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_podcast_activated)
        self._btn_subscribe.Bind(wx.EVT_BUTTON, self._on_subscribe)
        self._btn_unsubscribe.Bind(wx.EVT_BUTTON, self._on_unsubscribe)
        self._episode_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_play)
        self._episode_list.Bind(wx.EVT_CONTEXT_MENU, self._on_episode_context_menu)
        self._btn_download.Bind(wx.EVT_BUTTON, self._on_download)
        self._btn_add_feed.Bind(wx.EVT_BUTTON, self._on_add_feed)
        self._btn_sync_gpodder.Bind(wx.EVT_BUTTON, self._on_sync_gpodder)
        self._btn_import_opml.Bind(wx.EVT_BUTTON, self._on_import_opml)
        self._btn_export_opml.Bind(wx.EVT_BUTTON, self._on_export_opml)

    # ------------------------------------------------------------------
    # Small ListCtrl helpers (InsertItem/SetItem is a lot of boilerplate
    # for a 1-3 column row -- these keep the call sites below readable).
    # ------------------------------------------------------------------
    @staticmethod
    def _append_row(list_ctrl: wx.ListCtrl, *columns: str) -> int:
        idx = list_ctrl.InsertItem(list_ctrl.GetItemCount(), columns[0])
        for col, text in enumerate(columns[1:], start=1):
            list_ctrl.SetItem(idx, col, text)
        return idx

    @staticmethod
    def _find_row(list_ctrl: wx.ListCtrl, text: str) -> int:
        return list_ctrl.FindItem(-1, text)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------
    def _on_category_select(self, event: wx.CommandEvent) -> None:
        """Populate the podcast list when a category is selected."""
        from radiomaster.database.repository import PodcastRepository
        repo = PodcastRepository(self._db)
        self._podcast_list.DeleteAllItems()
        self._episode_list.DeleteAllItems()
        self._podcast_data: list[dict[str, Any]] = []
        self._viewing_search_results = False

        cat = self._selected_category()
        if cat == "Subscriptions":
            for p in repo.get_all():
                self._append_row(self._podcast_list, p.get("title", "Unknown"), p.get("author", ""))
                self._podcast_data.append(p)
        elif cat == "Custom Feeds":
            for p in repo.get_all():
                if p.get("is_custom"):
                    self._append_row(self._podcast_list, p.get("title", "Unknown"), p.get("author", ""))
                    self._podcast_data.append(p)
        elif cat == "Directory":
            self._podcast_list.DeleteAllItems()
            self._podcast_data = []
            self._append_row(self._podcast_list, "(Use Search above to find podcasts to subscribe to)")

    def _selected_category(self) -> str:
        idx = self._category_list.GetFirstSelected()
        return self._category_list.GetItemText(idx) if idx != wx.NOT_FOUND else ""

    def _set_status(self, text: str) -> None:
        top = wx.GetTopLevelParent(self)
        if hasattr(top, "_status_bar"):
            top._status_bar.set_status(text)

    def _on_search_focus(self, event: wx.FocusEvent) -> None:
        # CallAfter -- selecting immediately on the focus event itself gets
        # overridden back to no-selection/caret-at-end by the native
        # control's own default focus handling on MSW if done inline here.
        wx.CallAfter(self.search_ctrl.SelectAll)
        event.Skip()

    def _on_directory_search(self, event: wx.Event) -> None:
        """Search every configured podcast directory (see
        services/podcast_directory.search_all() -- iTunes always, Podcast
        Index once an API key is set in Settings > Podcasts) and show the
        merged results in the Podcasts list, same shape as RadioPanel's
        _on_search: local-first-then-live pattern isn't applicable here
        (there's no single local catalog to search), so this always goes
        straight to the live directories, off the UI thread."""
        query = self.search_ctrl.GetValue().strip()
        if not query:
            return
        # Leaves the just-searched term selected so typing right away
        # (without first clearing it) starts the next search fresh.
        self.search_ctrl.SelectAll()
        self._set_status(f"Status: Searching podcast directories for '{query}'...")
        self._search_seq += 1
        seq = self._search_seq

        def worker():
            from radiomaster.services.podcast_directory import PodcastAPIError, search_all
            try:
                results = search_all(query)
            except PodcastAPIError as exc:
                if seq != self._search_seq:
                    return
                # Previously any failure (network down, bad proxy, DNS,
                # SSL, a firewall blocking itunes.apple.com) was swallowed
                # and just showed "0 results" -- indistinguishable from a
                # real search that genuinely found nothing, and impossible
                # to diagnose. Show the actual reason instead.
                call_after_safe(self, self._set_status, f"Status: Podcast search failed -- {exc}")
                return
            if seq != self._search_seq:
                return  # a newer search superseded this one; discard stale results
            call_after_safe(self, self._apply_search_results, results, query)

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _apply_search_results(self, results: list[dict[str, Any]], query: str) -> None:
        # Switching category to "Directory" doesn't fire EVT_LIST_ITEM_SELECTED
        # (wx doesn't raise it for a programmatic Select()), so the results
        # are populated directly here rather than relying on
        # _on_category_select to do it.
        idx = self._find_row(self._category_list, "Directory")
        if idx != wx.NOT_FOUND:
            self._category_list.Select(idx)
        self._episode_list.DeleteAllItems()
        self._podcast_list.DeleteAllItems()
        self._podcast_data = results
        self._viewing_search_results = True
        if not results:
            self._append_row(self._podcast_list, "(No results -- try a different search term)")
        for r in results:
            self._append_row(
                self._podcast_list, r.get("title", "Unknown"), r.get("author", ""), r.get("directory", ""),
            )
        if self._podcast_list.GetItemCount():
            # A previous, longer list (e.g. "Subscriptions" after scrolling
            # down) can leave the native control's scroll position not
            # reset by DeleteAllItems() -- the new items genuinely exist
            # (GetItemCount() is correct) but can render scrolled out of
            # view, looking exactly like "found 25 but nothing shows".
            # Force it back to the top and repaint explicitly.
            self._podcast_list.EnsureVisible(0)
            self._podcast_list.Refresh()
            self._podcast_list.Update()
        self._set_status(f"Status: {len(results)} result(s) for '{query}'")

    def _on_podcast_activated(self, event: wx.CommandEvent) -> None:
        """Double-click/Enter in the Podcasts list: subscribes when browsing
        live search results (mirrors RadioPanel activating a station to
        play it -- one action commits to using what's selected); a no-op
        for already-subscribed podcasts, which single-click already loads."""
        if self._viewing_search_results:
            self._on_subscribe(event)

    def _on_subscribe(self, event: wx.Event) -> None:
        """Subscribes to the selected directory search result: adds it to
        the local podcast DB (idempotent -- feed_url is UNIQUE, so
        re-subscribing to something already subscribed just updates its
        metadata) and fetches its episode list, then switches to All
        Podcasts and selects it so the episodes are immediately browsable."""
        if not self._viewing_search_results:
            wx.MessageBox(
                "Search for a podcast above, select a result, then Subscribe.",
                "Nothing To Subscribe", wx.OK | wx.ICON_INFORMATION,
            )
            return
        idx = self._podcast_list.GetFirstSelected()
        if idx == wx.NOT_FOUND or idx >= len(self._podcast_data):
            wx.MessageBox("Select a podcast from the search results first.", "No Selection",
                          wx.OK | wx.ICON_INFORMATION)
            return
        result = self._podcast_data[idx]
        feed_url = result.get("feed_url", "")
        if not feed_url:
            wx.MessageBox("This search result has no feed URL.", "Cannot Subscribe",
                          wx.OK | wx.ICON_WARNING)
            return

        self._set_status(f"Status: Subscribing to '{result.get('title', feed_url)}'...")
        self._btn_subscribe.Disable()

        def worker():
            from radiomaster.database.repository import PodcastRepository
            from radiomaster.services.podcast_manager import PodcastManager
            repo = PodcastRepository(self._db)
            podcast_id = repo.add(
                feed_url, title=result.get("title", ""), description=result.get("description", ""),
                author=result.get("author", ""), artwork_url=result.get("artwork_url", ""),
                is_custom=False,
            )
            episode_count = 0
            try:
                feed_data = PodcastManager.parse_feed(feed_url)
                episodes = feed_data.get("episodes", []) if feed_data else []
                for ep in episodes:
                    self._db.execute(
                        """INSERT OR IGNORE INTO episodes
                        (podcast_id, guid, title, description, duration, published_date, audio_url)
                        VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (podcast_id, ep.get("guid", ""), ep.get("title", ""),
                         ep.get("description", ""), ep.get("duration", 0),
                         ep.get("published_date", ""), ep.get("audio_url", "")),
                    )
                self._db.commit()
                episode_count = len(episodes)
            except Exception as e:
                call_after_safe(self, self._set_status, f"Status: Subscribed, but episodes could not be loaded ({e})")
            call_after_safe(self, self._finish_subscribe, result.get("title", feed_url), episode_count)

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _finish_subscribe(self, title: str, episode_count: int) -> None:
        self._btn_subscribe.Enable()
        # "Subscriptions" -- switching category re-populates column 2 from
        # the DB, which now includes the podcast just subscribed to.
        idx = self._find_row(self._category_list, "Subscriptions")
        if idx != wx.NOT_FOUND:
            self._category_list.Select(idx)
        self._viewing_search_results = False
        from radiomaster.database.repository import PodcastRepository
        repo = PodcastRepository(self._db)
        self._podcast_list.DeleteAllItems()
        self._podcast_data = []
        for p in repo.get_all():
            self._append_row(self._podcast_list, p.get("title", "Unknown"), p.get("author", ""))
            self._podcast_data.append(p)
        # Select the podcast just subscribed to and load its episodes,
        # same as clicking it manually would.
        for i, p in enumerate(self._podcast_data):
            if p.get("title") == title:
                self._podcast_list.Select(i)
                self._podcast_list.EnsureVisible(i)
                self._load_episodes_for_index(i)
                break
        self._set_status(f"Status: Subscribed to '{title}' ({episode_count} episode(s))")

    def _on_unsubscribe(self, event: wx.Event) -> None:
        """Removes the selected subscribed podcast (and its episodes, via
        ON DELETE CASCADE) from the local database. Only meaningful for an
        already-subscribed podcast, not a bare directory search result --
        those aren't in the database yet, so there's nothing to remove."""
        if self._viewing_search_results:
            wx.MessageBox(
                "This is a search result, not a subscription yet -- there's nothing to unsubscribe from.",
                "Not Subscribed", wx.OK | wx.ICON_INFORMATION,
            )
            return
        idx = self._podcast_list.GetFirstSelected()
        if idx == wx.NOT_FOUND or idx >= len(self._podcast_data):
            wx.MessageBox("Select a podcast to unsubscribe from first.", "No Selection",
                          wx.OK | wx.ICON_INFORMATION)
            return
        podcast = self._podcast_data[idx]
        title = podcast.get("title", "this podcast")
        podcast_id = podcast.get("id")
        if not podcast_id:
            return
        if wx.MessageBox(
            f"Unsubscribe from '{title}'? This removes it and its downloaded episode list.",
            "Unsubscribe", wx.YES_NO | wx.ICON_QUESTION,
        ) != wx.YES:
            return

        from radiomaster.database.repository import PodcastRepository
        PodcastRepository(self._db).remove(podcast_id)
        if self._current_episode_id is not None and any(
            ep.get("id") == self._current_episode_id for ep in getattr(self, "_episode_data", [])
        ):
            self._current_episode_id = None
        self._episode_list.DeleteAllItems()
        self._episode_data = []
        self._on_category_select(None)  # re-populate column 2 without the removed podcast
        self._set_status(f"Status: Unsubscribed from '{title}'")

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
        """Download the selected episode for offline playback (Download
        Episode button and the episode context menu's Download item)."""
        idx = self._episode_list.GetFirstSelected()
        if idx < 0 or not hasattr(self, '_episode_data') or idx >= len(self._episode_data):
            wx.MessageBox("Please select an episode first.", "No Selection", wx.OK | wx.ICON_WARNING)
            return
        self._download_episode_at(idx, show_confirmation=True)

    def _on_download_all(self, event: wx.CommandEvent | None = None) -> None:
        """Queue every episode currently listed for the loaded podcast --
        one confirmation up front, one summary at the end, instead of a
        "Download Added" message box per episode which would be
        unusable for a feed with dozens of episodes."""
        episodes = getattr(self, "_episode_data", [])
        if not episodes:
            wx.MessageBox("No episodes to download.", "Download All", wx.OK | wx.ICON_INFORMATION)
            return
        if wx.MessageBox(
            f"Download all {len(episodes)} episode(s) of '{self._current_podcast_title}'?",
            "Download All", wx.YES_NO | wx.ICON_QUESTION,
        ) != wx.YES:
            return
        queued = sum(
            1 for i in range(len(episodes)) if self._download_episode_at(i, show_confirmation=False)
        )
        wx.MessageBox(
            f"Added {queued} of {len(episodes)} episode(s) to the download queue.",
            "Download All", wx.OK | wx.ICON_INFORMATION,
        )

    def _download_episode_at(self, idx: int, show_confirmation: bool) -> bool:
        """Queues the episode at ``idx`` for download. Returns whether it
        was actually queued (False for an episode with no audio URL --
        Download All keeps going past those instead of aborting the
        whole batch).

        Lands in its own <Podcast Download Location>/<Feed Name>/ folder
        (not the shared Downloads folder YouTube uses) alongside a plain
        -text show-notes file sharing the exact same base filename --
        see _write_show_notes() and DownloadManager.add_download()'s
        filename_base parameter for why that pairing is guaranteed."""
        ep = self._episode_data[idx]
        url = ep.get("audio_url", "")
        if not url:
            if show_confirmation:
                wx.MessageBox("This episode has no audio URL.", "Cannot Download", wx.OK | wx.ICON_WARNING)
            return False
        from radiomaster.database.repository import DownloadRepository
        from radiomaster.utils.helpers import sanitize_filename
        from radiomaster.utils.paths import get_podcasts_dir
        import os

        title = ep.get("title", "Podcast Episode")
        podcast_title = self._current_podcast_title

        feed_dir = os.path.join(get_podcasts_dir(), sanitize_filename(podcast_title))
        filename_base = sanitize_filename(title)[:150]  # avoid MAX_PATH issues on very long titles

        repo = DownloadRepository(self._db)
        download_id = repo.add(url, title=title, source_type="podcast", format="mp3",
                                output_dir=feed_dir, extract_audio=True, filename_base=filename_base)
        # Inserting the DB row alone was the whole bug: nothing ever
        # actually told DownloadManager to fetch the file, so the row sat
        # at its insert-time "queued" status forever and never moved to
        # History no matter how long you waited -- same wiring YouTube
        # downloads already use.
        app = wx.GetApp()
        if hasattr(app, "download_manager") and hasattr(app.download_manager, "add_download"):
            app.download_manager.add_download(
                download_id, url, output_dir=feed_dir, title=title,
                extract_audio=True, format="mp3", filename_base=filename_base,
            )
        self._write_show_notes(feed_dir, filename_base, podcast_title, ep)
        if show_confirmation:
            wx.MessageBox(f"Download added to queue: {title}", "Download Added",
                         wx.OK | wx.ICON_INFORMATION)
        return True

    def _on_episode_context_menu(self, event: wx.ContextMenuEvent) -> None:
        """Right-click (or Shift+F10/Menu key) on an episode -- follows
        the same Play/Pause/Stop template as RadioPanel's station context
        menu (see radio_panel.py's _on_station_context_menu, written as
        "the template other panels' context menus will follow"), plus
        Download/Download All for offline playback."""
        idx = self._episode_list.GetFirstSelected()
        if idx == wx.NOT_FOUND or not hasattr(self, "_episode_data") or idx >= len(self._episode_data):
            event.Skip()
            return
        ep = self._episode_data[idx]
        url = ep.get("audio_url", "")

        menu = wx.Menu()

        same_episode = bool(url) and self._engine.current_url == url
        if same_episode and self._engine.state == "paused":
            play_item = menu.Append(wx.ID_ANY, "&Resume")
            self.Bind(wx.EVT_MENU, lambda e: self._engine.resume(), play_item)
        elif same_episode and self._engine.state in ("playing", "buffering"):
            play_item = menu.Append(wx.ID_ANY, "&Pause")
            self.Bind(wx.EVT_MENU, lambda e: self._engine.pause(), play_item)
        else:
            play_item = menu.Append(wx.ID_ANY, "&Play")
            play_item.Enable(bool(url))
            self.Bind(wx.EVT_MENU, lambda e, i=idx: self._play_episode_at(i, offer_resume=True), play_item)

        stop_item = menu.Append(wx.ID_ANY, "&Stop")
        stop_item.Enable(same_episode and self._engine.state != "stopped")
        self.Bind(wx.EVT_MENU, lambda e: self._engine.stop(), stop_item)

        menu.AppendSeparator()

        download_item = menu.Append(wx.ID_ANY, "&Download")
        download_item.Enable(bool(url))
        self.Bind(wx.EVT_MENU, lambda e, i=idx: self._download_episode_at(i, show_confirmation=True), download_item)

        download_all_item = menu.Append(wx.ID_ANY, "Download &All")
        self.Bind(wx.EVT_MENU, lambda e: self._on_download_all(), download_all_item)

        self._episode_list.PopupMenu(menu, context_menu_pos(self._episode_list, event))
        menu.Destroy()

    @staticmethod
    def _write_show_notes(feed_dir: str, filename_base: str, podcast_title: str,
                           ep: dict[str, Any]) -> None:
        """Write a plain-text show-notes file next to the episode's audio
        download, sharing its exact base filename (see add_download's
        filename_base) so anyone browsing the feed folder can tell which
        notes belong to which episode at a glance -- a screen reader user
        included, since a folder full of same-named .mp3/.txt pairs reads
        unambiguously where two differently-named files wouldn't.

        content_encoded (RSS <content:encoded>, when a feed provides it)
        is normally the fuller of the two -- description is often just a
        one-line teaser duplicated from it -- so prefer it, falling back
        to description only when a feed doesn't supply the richer field.
        Both are arbitrary feed-supplied HTML, so run through BeautifulSoup
        to get plain, readable text instead of dumping raw markup into a
        .txt file.
        """
        import os
        raw_notes = ep.get("content_encoded") or ep.get("description") or ""
        notes_text = ""
        if raw_notes.strip():
            try:
                from bs4 import BeautifulSoup
                notes_text = BeautifulSoup(raw_notes, "html.parser").get_text("\n", strip=True)
            except Exception:
                notes_text = raw_notes
        if not notes_text.strip():
            notes_text = "(This episode has no show notes.)"

        try:
            os.makedirs(feed_dir, exist_ok=True)
            notes_path = os.path.join(feed_dir, f"{filename_base}.txt")
            with open(notes_path, "w", encoding="utf-8") as f:
                f.write(f"{ep.get('title', 'Podcast Episode')}\n")
                f.write(f"{podcast_title}\n")
                published = ep.get("published_date", "")
                if published:
                    f.write(f"Published: {published}\n")
                f.write("-" * 40 + "\n\n")
                f.write(notes_text)
                f.write("\n")
        except OSError as e:
            logger.warning("Could not write show notes for %r: %s", ep.get("title"), e)

    def _on_podcast_select(self, event: wx.CommandEvent) -> None:
        """Populate the episode list when a podcast is selected."""
        self._episode_list.DeleteAllItems()
        self._episode_data: list[dict[str, Any]] = []

        idx = self._podcast_list.GetFirstSelected()
        if idx < 0 or not hasattr(self, '_podcast_data') or idx >= len(self._podcast_data):
            return

        if self._viewing_search_results:
            # Not subscribed yet -- there's no local episode list for a
            # bare directory search result (its "id", if any, is the
            # directory's own id -- e.g. an iTunes collectionId -- not a
            # local podcasts.id, so looking up episodes by it would silently
            # return the wrong thing or nothing rather than being a no-op).
            self._set_status("Status: Select Subscribe to add this podcast and load its episodes.")
            return

        self._load_episodes_for_index(idx)

    def _load_episodes_for_index(self, idx: int) -> None:
        from radiomaster.database.repository import PodcastRepository
        from radiomaster.utils.config import ConfigManager
        repo = PodcastRepository(self._db)
        self._episode_list.DeleteAllItems()
        self._episode_data = []
        podcast = self._podcast_data[idx]
        self._current_podcast_title = podcast.get("title") or "Unknown Podcast"
        podcast_id = podcast.get("id")
        if podcast_id:
            ascending = ConfigManager.get_instance().get("podcasts.episode_order", default="newest") == "oldest"
            for ep in repo.get_episodes(podcast_id, ascending=ascending):
                self._append_row(
                    self._episode_list, ep.get("title", "Unknown"),
                    ep.get("published_date", ""), str(ep.get("duration", "") or ""),
                )
                self._episode_data.append(ep)

    def refresh_episode_order(self) -> None:
        """Re-applies Settings > Podcasts > Episode order to whatever
        episode list is currently on screen, immediately -- called from
        MainWindow._apply_settings_changes() (Settings > OK/Apply), so
        changing the order takes effect right away instead of only the
        next time a podcast happens to get (re)selected.

        Directory search results aren't episodes, so there's nothing to
        reorder if that's what's showing; and if no podcast is selected
        at all, there's no episode list on screen to refresh either.
        """
        if self._viewing_search_results:
            return
        idx = self._podcast_list.GetFirstSelected()
        if idx == wx.NOT_FOUND or not hasattr(self, "_podcast_data") or idx >= len(self._podcast_data):
            return

        # The episode list is about to be torn down and rebuilt in the new
        # order -- row *indices* are meaningless across that, so remember
        # which episode (by database id, not position) was playing/
        # selected and re-find it afterward. Without this, a reorder
        # mid-playback would leave _current_playing_index pointing at the
        # wrong row, and try_auto_advance() would move to the wrong "next"
        # episode.
        playing_id = None
        if self._current_playing_index is not None and self._current_playing_index < len(self._episode_data):
            playing_id = self._episode_data[self._current_playing_index].get("id")
        selected_row = self._episode_list.GetFirstSelected()
        selected_id = None
        if selected_row != wx.NOT_FOUND and selected_row < len(self._episode_data):
            selected_id = self._episode_data[selected_row].get("id")

        self._load_episodes_for_index(idx)

        if playing_id is not None:
            for i, ep in enumerate(self._episode_data):
                if ep.get("id") == playing_id:
                    self._current_playing_index = i
                    break
        if selected_id is not None:
            for i, ep in enumerate(self._episode_data):
                if ep.get("id") == selected_id:
                    self._episode_list.Select(i)
                    self._episode_list.EnsureVisible(i)
                    break

    def _on_play(self, event: wx.Event) -> None:
        """Play the selected episode, resuming from saved position if any."""
        idx = self._episode_list.GetFirstSelected()
        if idx < 0 or not hasattr(self, '_episode_data') or idx >= len(self._episode_data):
            return
        self._play_episode_at(idx, offer_resume=True)

    def _play_episode_at(self, idx: int, offer_resume: bool) -> None:
        ep = self._episode_data[idx]
        url = ep.get("audio_url", "")
        if not url:
            return

        # Save progress on whatever was playing before switching episodes.
        self._save_position()

        self._current_episode_id = ep.get("id")
        # Which row is actually PLAYING (vs merely selected/browsed) and
        # what it's playing, so try_auto_advance() below can tell "the
        # engine just finished MY episode" apart from some other panel's
        # (radio, media player, ...) track ending -- on_track_finished is
        # a single shared signal, not scoped to whichever tab is active.
        self._current_playing_index = idx
        self._last_played_url = url
        resume_position = ep.get("play_position") or 0.0

        if offer_resume and resume_position > 0:
            if wx.MessageBox(
                f"Resume from your last position in this episode?",
                "Resume Playback", wx.YES_NO | wx.ICON_QUESTION,
            ) != wx.YES:
                resume_position = 0.0
        elif not offer_resume:
            resume_position = 0.0

        # Duration matters beyond just display: the engine reads
        # duration == 0.0 as "this is an unbounded live stream" and, with
        # Settings > Radio > Auto-reconnect on (the default), reconnects
        # on ANY natural end instead of treating it as finished -- for a
        # podcast episode (always a finite file) that meant every episode
        # silently restarted itself from the beginning forever instead of
        # stopping or advancing. Passing the episode's real duration (from
        # itunes:duration in the feed) is what tells the engine this one
        # actually ends.
        self._engine.play(url, title=ep.get("title", ""), duration=float(ep.get("duration") or 0.0))

        if resume_position > 0:
            import threading
            threading.Timer(1.0, lambda: self._engine.seek(resume_position)).start()

        if self._current_episode_id is not None:
            from radiomaster.database.repository import EpisodeRepository
            EpisodeRepository(self._db).mark_played(self._current_episode_id, True)

    def try_auto_advance(self) -> bool:
        """Called when the engine reports a track finished naturally (see
        MainWindow's on_track_finished wiring, which tries MediaPlayerPanel
        first and falls through to this). Mirrors MediaPlayerPanel's own
        try_auto_advance -- same "is this actually my track, and is there
        a next one" guards, gated additionally on Settings > Podcasts >
        Auto-advance, which is off by default (unattended auto-play isn't
        everyone's preference, unlike a manually-built media playlist)."""
        if self._current_playing_index is None or not hasattr(self, "_episode_data"):
            return False
        if self._current_playing_index >= len(self._episode_data):
            return False
        if self._engine.current_url != self._last_played_url:
            return False  # a stray natural-end notification for something else entirely
        from radiomaster.utils.config import ConfigManager
        if not ConfigManager.get_instance().get("podcasts.auto_advance", default=False):
            return False
        next_index = self._current_playing_index + 1
        if next_index >= len(self._episode_data):
            # No next episode -- let it stay stopped instead of looping
            # the last one (the actual bug report): _current_playing_index
            # is left alone here on purpose, so a stray duplicate
            # notification can't advance past the list's end either.
            return False
        self._episode_list.Select(next_index)
        self._episode_list.EnsureVisible(next_index)
        self._play_episode_at(next_index, offer_resume=False)
        return True

    # ------------------------------------------------------------------
    # Transport bar Previous/Next/First/Last -- MainWindow routes these
    # here when the Podcasts tab is active (see _next_track/_prev_track/
    # _first_track/_last_track), same pattern as RadioPanel's history_*.
    # Navigation is relative to whichever episode is actually PLAYING
    # (falling back to whatever's merely selected if nothing's playing
    # yet), and always in the episode list's current on-screen order --
    # which already reflects Settings > Podcasts > Episode order.
    # ------------------------------------------------------------------
    def _episode_data_safe(self) -> list[dict[str, Any]]:
        # _episode_data doesn't exist at all until a podcast has been
        # selected at least once (see _on_podcast_select/_on_unsubscribe)
        # -- matches the getattr guard the rest of this file already uses.
        return getattr(self, "_episode_data", [])

    def _episode_nav_base(self) -> Optional[int]:
        if self._current_playing_index is not None:
            return self._current_playing_index
        idx = self._episode_list.GetFirstSelected()
        return idx if idx != wx.NOT_FOUND else None

    def _go_to_episode(self, idx: int) -> None:
        self._episode_list.Select(idx)
        self._episode_list.EnsureVisible(idx)
        self._play_episode_at(idx, offer_resume=False)

    def episode_has_previous(self) -> bool:
        base = self._episode_nav_base()
        return bool(self._episode_data_safe()) and base is not None and base > 0

    def episode_has_next(self) -> bool:
        base = self._episode_nav_base()
        episodes = self._episode_data_safe()
        return bool(episodes) and base is not None and base < len(episodes) - 1

    def episode_previous(self) -> None:
        base = self._episode_nav_base()
        if base is not None and base > 0:
            self._go_to_episode(base - 1)

    def episode_next(self) -> None:
        base = self._episode_nav_base()
        episodes = self._episode_data_safe()
        if base is not None and episodes and base < len(episodes) - 1:
            self._go_to_episode(base + 1)

    def episode_first(self) -> None:
        if self._episode_data_safe():
            self._go_to_episode(0)

    def episode_last(self) -> None:
        episodes = self._episode_data_safe()
        if episodes:
            self._go_to_episode(len(episodes) - 1)

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
