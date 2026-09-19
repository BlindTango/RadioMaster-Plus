"""Downloads tab panel showing active downloads and history."""

import os
import errno
import sqlite3
import wx
from typing import Any, Callable, Optional
from radiomaster.database.connection import DatabaseManager
from radiomaster.engine.playback_engine import PlaybackEngine
from radiomaster.utils.accessibility import context_menu_pos, set_accessible_name
from radiomaster.utils.paths import resolve_stored_path


class DownloadsPanel(wx.Panel):
    """Panel for managing downloads."""

    def __init__(self, parent: wx.Window, db: DatabaseManager, engine: PlaybackEngine) -> None:
        super().__init__(parent)
        self._db = db
        self._engine = engine
        # Row dicts parallel to _active_list's items (same order), so
        # selecting a row can look up its real "downloads" table id and
        # source_type without needing a second DB round-trip.
        self._active_rows: list[dict[str, Any]] = []
        self._history_rows: list[dict[str, Any]] = []
        # Which History row is actually PLAYING (by database id, not row
        # position -- a row's position shifts as new downloads complete
        # and get prepended, see _load_data), for Previous/Next/First/
        # Last on the transport bar (see history_previous() etc.).
        self._playing_history_id: Optional[int] = None
        # Set by MainWindow to RadioPanel.stop_recording_by_download_id --
        # only source_type="radio_recording" rows can be stopped from
        # here (a real youtube/podcast download has no such handle).
        self.on_stop_recording: Optional[Callable[[int], bool]] = None
        # Set by MainWindow to RadioPanel.is_recording_active -- a
        # side-effect-free check Remove uses to tell a genuinely still-
        # recording row (which needs Stop Recording's graceful finalize,
        # not Remove) apart from a STALE radio_recording row with nothing
        # actually running for it anymore (e.g. left behind by a crash,
        # or an older version's tracking) -- which previously could never
        # be removed at all, Remove refused every radio_recording row
        # unconditionally.
        self.on_check_recording_active: Optional[Callable[[int], bool]] = None
        self._setup_ui()
        self._load_data()

        # Progress/status only ever changed on disk (DownloadManager
        # callbacks writing to the DB) -- without polling, this panel
        # showed whatever status a download had at the moment it was
        # first viewed, forever, until Refresh was clicked by hand.
        self._refresh_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, lambda e: self._load_data(), self._refresh_timer)
        self._refresh_timer.Start(3000)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)

    def _on_destroy(self, event: wx.WindowDestroyEvent) -> None:
        if event.GetEventObject() is self:
            self._refresh_timer.Stop()
        event.Skip()

    @staticmethod
    def _history_limit() -> int:
        """How many Download History rows to show, from Settings >
        Downloads (downloads.history_limit). -1 means unlimited (all
        completed/failed rows); the default is 50."""
        from radiomaster.utils.config import ConfigManager
        try:
            value = int(ConfigManager.get_instance().get(
                "downloads.history_limit", default=50))
        except (TypeError, ValueError):
            return 50
        if value < 0:
            return -1  # SQLite: LIMIT -1 = no limit
        return max(1, value)

    def _setup_ui(self) -> None:
        """Create the downloads panel layout."""
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # Active downloads
        main_sizer.Add(wx.StaticText(self, label="Active Downloads"), 0, wx.ALL, 4)

        # LC_SINGLE_SEL -- without it, GetFirstSelected() (used everywhere
        # in this panel: Stop Recording, Remove, Play, Previous/Next/
        # First/Last) can return a stale earlier selection left behind by
        # Select() calls that only ever ADD to a multi-selection instead
        # of replacing it, rather than whatever row was actually most
        # recently acted on. Matches PodcastPanel's lists, which already
        # use LC_SINGLE_SEL for the same reason.
        self._active_list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        set_accessible_name(self._active_list, "Active Downloads")
        self._active_list.AppendColumn("Title", width=250)
        self._active_list.AppendColumn("Progress", width=100)
        self._active_list.AppendColumn("Status", width=100)
        self._active_list.Bind(wx.EVT_KEY_DOWN, self._on_active_list_key)
        self._active_list.Bind(wx.EVT_CONTEXT_MENU, self._on_active_context_menu)
        main_sizer.Add(self._active_list, 1, wx.EXPAND | wx.ALL, 4)

        # History
        main_sizer.Add(wx.StaticText(self, label="Download History"), 0, wx.ALL, 4)

        self._history_list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        set_accessible_name(self._history_list, "Download History")
        self._history_list.AppendColumn("Title", width=250)
        self._history_list.AppendColumn("Date", width=150)
        self._history_list.AppendColumn("Status", width=100)
        self._history_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_history_activated)
        self._history_list.Bind(wx.EVT_KEY_DOWN, self._on_history_list_key)
        self._history_list.Bind(wx.EVT_CONTEXT_MENU, self._on_history_context_menu)
        main_sizer.Add(self._history_list, 1, wx.EXPAND | wx.ALL, 4)

        self.SetSizer(main_sizer)

    def _load_data(self) -> None:
        """Load download data from the repository.

        The 3-second auto-refresh timer used to blow away and rebuild
        BOTH lists from scratch (DeleteAllItems + reinsert everything)
        on every single tick, whether anything had actually changed or
        not -- almost always just a progress percentage ticking up.
        Restoring the selected row by id afterward (added previously)
        stopped the *button clicks* from failing, but the list itself
        still visibly tore down and rebuilt every 3 seconds, which is
        exactly what made it "constantly refreshing" and hard to work
        with for a screen reader user: rebuilding the whole list churns
        the accessibility tree even when the row you're on didn't move.
        It could also actually pick the wrong row if the active set
        reordered while re-selecting only by id and you acted on the
        list a beat later, which is exactly the "stop recording B, but
        Remove says recording A is still active" symptom.

        Now: if the exact same set of active download ids is present in
        the same order as last time, only that row's Progress/Status
        cells are updated in place via SetItem -- no delete/reinsert at
        all, so the list, focus, and selection are completely
        undisturbed. A full rebuild only happens when a row genuinely
        starts, finishes, or is removed -- an actual list change, not a
        cosmetic one.
        """
        from radiomaster.database.repository import DownloadRepository
        repo = DownloadRepository(self._db)

        new_rows = repo.get_queued()
        same_rows = (
            len(new_rows) == len(self._active_rows)
            and all(a["id"] == b["id"] for a, b in zip(new_rows, self._active_rows))
        )
        self._active_rows = new_rows
        if same_rows:
            for i, d in enumerate(new_rows):
                self._active_list.SetItem(i, 1, f"{d.get('progress', 0):.0f}%")
                self._active_list.SetItem(i, 2, d.get("status", "queued"))
        else:
            selected_idx = self._active_list.GetFirstSelected()
            selected_id = (
                self._active_list.GetItemData(selected_idx) if selected_idx != wx.NOT_FOUND else None
            )
            self._active_list.DeleteAllItems()
            for i, d in enumerate(new_rows):
                idx = self._active_list.InsertItem(i, d.get("title", "Unknown"))
                self._active_list.SetItemData(idx, d["id"])
                self._active_list.SetItem(idx, 1, f"{d.get('progress', 0):.0f}%")
                self._active_list.SetItem(idx, 2, d.get("status", "queued"))
            if selected_id is not None:
                for i, d in enumerate(new_rows):
                    if d["id"] == selected_id:
                        self._active_list.Select(i)
                        break

        # History (completed/failed downloads) -- refreshed the same
        # cautious way, though it changes far less often than progress.
        # The row cap is configurable (Settings > Downloads > Download
        # History entries, default 50) -- a hardcoded 50 hid older
        # entries with no way to see them.
        history_limit = self._history_limit()
        new_history = self._db.fetchall(
            "SELECT * FROM downloads WHERE status IN ('completed', 'failed') "
            "ORDER BY id DESC LIMIT ?",
            (history_limit,),
        )
        history_same = (
            self._history_list.GetItemCount() == len(new_history)
            and all(
                self._history_list.GetItemData(i) == d["id"]
                and self._history_list.GetItemText(i, 2) == d.get("status", "")
                for i, d in enumerate(new_history)
            )
        )
        self._history_rows = new_history
        if not history_same:
            selected_idx = self._history_list.GetFirstSelected()
            selected_id = (self._history_list.GetItemData(selected_idx)
                           if selected_idx != wx.NOT_FOUND else None)
            self._history_list.DeleteAllItems()
            for i, d in enumerate(new_history):
                idx = self._history_list.InsertItem(i, d.get("title", "Unknown"))
                self._history_list.SetItemData(idx, d["id"])
                self._history_list.SetItem(idx, 1, d.get("created_at", ""))
                self._history_list.SetItem(idx, 2, d.get("status", ""))
                if d["id"] == selected_id:
                    self._history_list.Select(idx)

    def _on_stop_recording(self, event: wx.CommandEvent,
                           *, row: dict[str, Any] | None = None) -> None:
        if row is None:
            idx = self._active_list.GetFirstSelected()
            if idx == wx.NOT_FOUND or idx >= len(self._active_rows):
                wx.MessageBox("Select an active recording first.", "No Selection",
                              wx.OK | wx.ICON_INFORMATION)
                return
            row = self._active_rows[idx]
        if row.get("source_type") != "radio_recording":
            wx.MessageBox("Only manual radio recordings (not other downloads) can be "
                          "stopped from here.", "Not a Recording", wx.OK | wx.ICON_INFORMATION)
            return
        if self.on_stop_recording and self.on_stop_recording(row["id"]):
            self._load_data()
        else:
            wx.MessageBox("That recording is no longer active.", "Already Stopped",
                          wx.OK | wx.ICON_INFORMATION)
            self._load_data()

    def _on_active_list_key(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_DELETE:
            self._on_remove(event)
        else:
            event.Skip()

    def _on_history_list_key(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_DELETE:
            self._on_remove_history(event)
        else:
            event.Skip()

    def _on_remove(self, event: wx.Event, *, row: dict[str, Any] | None = None) -> None:
        if row is None:
            idx = self._active_list.GetFirstSelected()
            if idx == wx.NOT_FOUND or idx >= len(self._active_rows):
                wx.MessageBox("Select a download first.", "No Selection",
                              wx.OK | wx.ICON_INFORMATION)
                return
            row = self._active_rows[idx]
        if row.get("source_type") == "radio_recording":
            # Only block Remove for a recording that's genuinely still
            # running -- that needs Stop Recording's graceful finalize
            # instead, so the file already written gets closed out
            # properly. A STALE radio_recording row (nothing is actually
            # recording for it anymore -- left behind by a crash, or an
            # older version's tracking) used to be refused here
            # unconditionally, with no other way to ever remove it either
            # (Stop Recording just says "no longer active" and leaves the
            # row exactly as stuck as before).
            is_active = (
                self.on_check_recording_active(row["id"])
                if self.on_check_recording_active else True
            )
            if is_active:
                wx.MessageBox("This is an active recording -- use Stop Recording instead "
                              "of Remove so the file it's already written gets finalized "
                              "properly.", "Active Recording", wx.OK | wx.ICON_INFORMATION)
                return
        if wx.MessageBox(
            f"Remove '{row.get('title', 'this download')}' from the queue? "
            "If it's genuinely in progress, this only removes the row -- it doesn't "
            "cancel the actual download running in the background.",
            "Remove Download", wx.YES_NO | wx.ICON_QUESTION,
        ) != wx.YES:
            return
        from radiomaster.database.repository import DownloadRepository
        DownloadRepository(self._db).delete(row["id"])
        self._load_data()

    def _on_remove_all_active(self, event: wx.Event) -> None:
        """Remove active entries, preserving recordings that still need stopping."""
        from radiomaster.database.repository import DownloadRepository
        rows = DownloadRepository(self._db).get_queued()
        removable = [row for row in rows if (
            row.get("source_type") != "radio_recording"
            or (self.on_check_recording_active
                and not self.on_check_recording_active(row["id"]))
        )]
        if not removable:
            message = ("Only running recordings remain. Use Stop Recording before removing them."
                       if rows else "Active Downloads is already empty.")
            wx.MessageBox(message, "Nothing to Remove", wx.OK | wx.ICON_INFORMATION, self)
            return
        message = (
            f"Remove all {len(removable)} removable entries from Active Downloads? "
            "This only removes the entries; downloads already queued or running will continue "
            "in the background. Downloaded files will not be deleted."
        )
        if len(removable) != len(rows):
            message += " Running recordings will remain in the list."
        if wx.MessageBox(message, "Remove All Active Downloads",
                         wx.YES_NO | wx.ICON_QUESTION, self) != wx.YES:
            return
        # Delete only the confirmed snapshot, and leave entries that finished
        # while the confirmation was open in History.
        ids = tuple(row["id"] for row in removable)
        placeholders = ",".join("?" for _ in ids)
        if self._delete_history_entries(
            f"DELETE FROM downloads WHERE id IN ({placeholders}) "
            "AND status IN ('queued', 'downloading')", ids, area="active downloads",
        ):
            self._load_data()

    def _on_remove_history(self, event: wx.Event, *, row: dict[str, Any] | None = None) -> None:
        if row is None:
            idx = self._history_list.GetFirstSelected()
            if idx == wx.NOT_FOUND or idx >= len(self._history_rows):
                wx.MessageBox("Select a download from History first.", "No Selection",
                              wx.OK | wx.ICON_INFORMATION, self)
                return
            row = self._history_rows[idx]
        if wx.MessageBox(
            f"Remove '{row.get('title', 'this download')}' from History? "
            "This only removes the entry -- it doesn't delete the downloaded file itself.",
            "Remove From History", wx.YES_NO | wx.ICON_QUESTION, self,
        ) != wx.YES:
            return
        if not self._delete_history_entries(
            "DELETE FROM downloads WHERE id = ? AND status IN ('completed', 'failed')",
            (row["id"],),
        ):
            return
        if row["id"] == self._playing_history_id:
            self._playing_history_id = None
        self._load_data()

    def _on_remove_all_history(self, event: wx.Event) -> None:
        """History context menu > Remove All -- clears every completed/
        failed entry at once. Same semantics as the single-row Remove:
        only the database entries go away, the files on disk are left
        untouched, and anything still queued/downloading stays in the
        Active list (this deliberately never touches those rows)."""
        count = self._db.fetchone(
            "SELECT COUNT(*) AS count FROM downloads WHERE status IN ('completed', 'failed')"
        )["count"]
        if not count:
            wx.MessageBox("Download History is already empty.", "Nothing to Remove",
                          wx.OK | wx.ICON_INFORMATION, self)
            return
        if wx.MessageBox(
            f"Remove all {count} entries from Download History? "
            "This only removes the entries -- it doesn't delete the downloaded "
            "files themselves.",
            "Remove All From History", wx.YES_NO | wx.ICON_QUESTION, self,
        ) != wx.YES:
            return
        if not self._delete_history_entries(
            "DELETE FROM downloads WHERE status IN ('completed', 'failed')"
        ):
            return
        self._playing_history_id = None
        self._load_data()

    def _delete_history_entries(self, sql: str, params: tuple[Any, ...] = (),
                                *, area: str = "download history") -> bool:
        """Commit removal before changing the UI; report storage failures."""
        try:
            self._db.execute(sql, params)
            self._db.commit()
        except (sqlite3.Error, OSError) as error:
            # A failed commit can leave a pending deletion on this connection.
            # Roll it back so a later refresh/write cannot hide or delete rows.
            rollback_failed = False
            try:
                self._db.conn.rollback()
            except (sqlite3.Error, OSError):
                rollback_failed = True
            code = getattr(error, "sqlite_errorcode", 0) or 0
            full = (
                (code & 0xFF) == sqlite3.SQLITE_FULL
                or getattr(error, "errno", None) == errno.ENOSPC
                or getattr(error, "winerror", None) in (39, 112)
                or "database or disk is full" in str(error).lower()
                or "no space left on device" in str(error).lower()
            )
            if full:
                message = (
                    f"Could not update {area} because the drive containing "
                    "RadioMaster+ data is full. Free some space on that drive and try again. "
                    "Even removing entries requires some free space."
                )
                title = "Drive Full"
            else:
                message = f"Could not update {area}. Please try again.\n\nDetails: {error}"
                title = f"Could Not Update {area.title()}"
            if rollback_failed:
                message += "\n\nRestart RadioMaster+ before trying again."
            wx.MessageBox(message, title, wx.OK | wx.ICON_ERROR, self)
            return False
        return True

    # ------------------------------------------------------------------
    # Context menus -- EVT_CONTEXT_MENU covers right-click, the
    # Menu/Applications key, AND Shift+F10 in one binding (see
    # context_menu_pos's own docstring), so no separate keyboard handling
    # is needed. Download actions are available from these context menus.
    # ------------------------------------------------------------------
    def _on_active_context_menu(self, event: wx.ContextMenuEvent) -> None:
        idx = self._active_list.GetFirstSelected()
        row = self._active_rows[idx] if 0 <= idx < len(self._active_rows) else {}
        is_recording = row.get("source_type") == "radio_recording"

        menu = wx.Menu()
        actions = {}
        stop_item = menu.Append(wx.ID_ANY, "Stop &Recording")
        stop_item.Enable(bool(
            is_recording and row.get("status") == "downloading"
            and self.on_stop_recording and self.on_check_recording_active
            and self.on_check_recording_active(row["id"])
        ))
        actions[stop_item.GetId()] = lambda: self._on_stop_recording(event, row=row)
        if not is_recording:
            restart_item = menu.Append(wx.ID_ANY, "&Restart")
            restart_item.Enable(bool(row))
            actions[restart_item.GetId()] = lambda: self._restart_download(row)
        restart_all_item = menu.Append(wx.ID_ANY, "Restart A&ll")
        restart_all_item.Enable(bool(self._db.fetchone(
            "SELECT id FROM downloads WHERE status IN ('queued', 'downloading') "
            "AND COALESCE(source_type, '') != 'radio_recording' LIMIT 1"
        )))
        actions[restart_all_item.GetId()] = lambda: self._on_restart_all_active(event)
        menu.AppendSeparator()
        remove_item = menu.Append(wx.ID_ANY, "Re&move")
        remove_item.Enable(bool(row))
        actions[remove_item.GetId()] = lambda: self._on_remove(event, row=row)
        remove_all_item = menu.Append(wx.ID_ANY, "Remove &All")
        remove_all_item.Enable(bool(self._db.fetchone(
            "SELECT id FROM downloads WHERE status IN ('queued', 'downloading') LIMIT 1"
        )))
        actions[remove_all_item.GetId()] = lambda: self._on_remove_all_active(event)
        try:
            selected = self._active_list.GetPopupMenuSelectionFromUser(
                menu, context_menu_pos(self._active_list, event))
        finally:
            menu.Destroy()
        if selected in actions:
            actions[selected]()

    def _on_history_context_menu(self, event: wx.ContextMenuEvent) -> None:
        idx = self._history_list.GetFirstSelected()
        row = self._history_rows[idx] if 0 <= idx < len(self._history_rows) else {}

        menu = wx.Menu()
        actions = {}
        play_item = menu.Append(wx.ID_ANY, "&Play")
        play_item.Enable(row.get("status") == "completed")
        actions[play_item.GetId()] = lambda: self._play_history_row(next(
            (i for i, current in enumerate(self._history_rows) if current["id"] == row.get("id")),
            -1,
        ))
        if row.get("status") == "failed":
            retry_item = menu.Append(wx.ID_ANY, "&Retry")
            actions[retry_item.GetId()] = lambda: self._retry_download(row)
        retry_all_item = menu.Append(wx.ID_ANY, "Retry all &failed downloads")
        retry_all_item.Enable(bool(self._db.fetchone(
            "SELECT id FROM downloads WHERE status = 'failed' LIMIT 1"
        )))
        actions[retry_all_item.GetId()] = lambda: self._on_retry_all_failed(event)
        menu.AppendSeparator()
        remove_item = menu.Append(wx.ID_ANY, "R&emove")
        remove_item.Enable(bool(row))
        actions[remove_item.GetId()] = lambda: self._on_remove_history(event, row=row)
        remove_all_item = menu.Append(wx.ID_ANY, "Remove &All")
        actions[remove_all_item.GetId()] = lambda: self._on_remove_all_history(event)
        menu.AppendSeparator()
        refresh_item = menu.Append(wx.ID_ANY, "Re&fresh")
        actions[refresh_item.GetId()] = self._load_data

        # Dispatch after the native popup closes, so confirmation dialogs have
        # normal focus and no persistent panel bindings outlive their menu IDs.
        # Capture the row above: a timer refresh can change the list meanwhile.
        try:
            selected = self._history_list.GetPopupMenuSelectionFromUser(
                menu, context_menu_pos(self._history_list, event))
        finally:
            menu.Destroy()
        if selected in actions:
            actions[selected]()

    # ------------------------------------------------------------------
    # Retry / Restart -- both resubmit the same row to DownloadManager
    # using output_dir/extract_audio/filename_base persisted alongside
    # it (see DownloadRepository.add()/migration 22); the only
    # difference is Restart also has to stop whatever's still actually
    # running for a stalled download first.
    # ------------------------------------------------------------------
    def _resubmit(self, row: dict[str, Any], *, refresh: bool = True,
                  restart: bool = False) -> bool:
        app = wx.GetApp()
        if not (hasattr(app, "download_manager") and hasattr(app.download_manager, "add_download")):
            return False
        from radiomaster.services.download_manager import AUDIO_FORMATS, normalize_audio_format
        from radiomaster.utils.paths import get_downloads_dir, get_podcasts_dir

        output_dir = resolve_stored_path(row.get("output_dir") or "")
        download_format = row.get("format") or ""
        extract_audio = bool(row.get("extract_audio"))
        if not output_dir:
            # Rows created before migration 22 have no destination or audio
            # flag. Passing their empty folder to the worker fails immediately
            # in makedirs(), sending the retry straight back to History.
            output_dir = (get_podcasts_dir() if row.get("source_type") == "podcast"
                          else get_downloads_dir())
            extract_audio = extract_audio or download_format.lower() in (*AUDIO_FORMATS, "ogg")
        download_format = (normalize_audio_format(download_format) if extract_audio
                           else (download_format or "best"))
        def prepare() -> bool:
            return DownloadsPanel._delete_history_entries(
                self, "UPDATE downloads SET status = 'queued', progress = 0, error = NULL WHERE id = ?",
                (row["id"],), area="downloads",
            )
        if restart:
            if not app.download_manager.prepare_restart(row["id"], prepare):
                return False
        elif not prepare():
            return False
        quality = row.get("quality") or ""
        audio_quality = "0" if quality.lower() == "best" else (quality.upper() if quality else "0")
        app.download_manager.add_download(
            row["id"], row["url"],
            output_dir=output_dir,
            title=row.get("title", ""),
            format=download_format,
            extract_audio=extract_audio,
            audio_quality=audio_quality,
            filename_base=row.get("filename_base") or "",
        )
        if restart:
            app.download_manager.start()
        if refresh:
            self._load_data()
        return True

    def _on_retry_all_failed(self, event: wx.Event) -> None:
        """Retry a snapshot of all failures, including history outside the display limit."""
        rows = self._db.fetchall(
            "SELECT * FROM downloads WHERE status = 'failed' ORDER BY id"
        )
        for row in rows:
            if self._resubmit(row, refresh=False) is False:
                break
        self._load_data()

    def _retry_download(self, row: dict[str, Any]) -> None:
        """History > Retry -- nothing is running for a 'failed' row, so
        this is just resetting the DB row and resubmitting it."""
        self._resubmit(row)

    def _restart_download(self, row: dict[str, Any]) -> None:
        """Active > Restart -- for a download that's stalled (or you
        just want to redo). Stops whatever's still actually running for
        it first (best-effort; see DownloadManager.cancel()), then
        resubmits a fresh attempt under the same row."""
        if wx.MessageBox(
            f"Restart '{row.get('title', 'this download')}'? "
            "If it's still downloading, the current attempt will be stopped and a new one started.",
            "Restart Download", wx.YES_NO | wx.ICON_QUESTION,
        ) != wx.YES:
            return
        self._resubmit(row, restart=True)

    def _on_restart_all_active(self, event: wx.Event) -> None:
        """Restart every active download, excluding live radio recordings."""
        rows = self._db.fetchall(
            "SELECT * FROM downloads WHERE status IN ('queued', 'downloading') "
            "AND COALESCE(source_type, '') != 'radio_recording' ORDER BY id"
        )
        if not rows:
            wx.MessageBox("There are no active downloads to restart.", "Nothing to Restart",
                          wx.OK | wx.ICON_INFORMATION, self)
            return
        if wx.MessageBox(
            f"Restart all {len(rows)} active downloads? Current attempts will be stopped "
            "and new attempts started using your simultaneous-download limit. "
            "Paused downloads will resume. Radio recordings will continue unchanged.",
            "Restart All Downloads", wx.YES_NO | wx.ICON_QUESTION, self,
        ) != wx.YES:
            return
        for row in rows:
            if self._resubmit(row, restart=True, refresh=False) is False:
                break
        self._load_data()

    # ------------------------------------------------------------------
    # Playback -- a completed download's file (podcast episode, YouTube
    # download, or a finished radio recording) can be played directly
    # from here, with Previous/Next/First/Last on the transport bar
    # walking through History in its current on-screen order, the same
    # pattern PodcastPanel uses for episodes and RadioPanel for station
    # history. Tracked by database id (not row position), since History
    # is newest-first -- a new completed download shifts every existing
    # row's position down by one.
    # ------------------------------------------------------------------
    def _play_history_row(self, idx: int) -> bool:
        if idx < 0 or idx >= len(self._history_rows):
            return False
        row = self._history_rows[idx]
        path = resolve_stored_path(row.get("file_path") or "")
        if not path or not os.path.isfile(path):
            wx.MessageBox(
                "This download's file could not be found on disk -- it may have been "
                "moved, deleted, or (for an older download) never had its file path "
                "recorded at all.",
                "File Not Found", wx.OK | wx.ICON_WARNING,
            )
            return False
        self._playing_history_id = row["id"]
        self._history_list.Select(idx)
        self._history_list.EnsureVisible(idx)
        self._engine.play(path, title=row.get("title", ""))
        return True

    def _on_history_activated(self, event: wx.ListEvent) -> None:
        self._play_history_row(event.GetIndex())

    def _play_selected_history(self) -> None:
        idx = self._history_list.GetFirstSelected()
        if idx == wx.NOT_FOUND:
            wx.MessageBox("Select a download from History first.", "No Selection",
                          wx.OK | wx.ICON_INFORMATION)
            return
        self._play_history_row(idx)

    def play_selected(self) -> bool:
        """Called by MainWindow's transport Play button when the engine is
        stopped and the Downloads tab is active -- plays whatever's
        selected in History instead of the button silently doing nothing
        (or resuming something unrelated from before). Returns False
        (without complaining) when nothing's selected, so the caller can
        fall back to its own default stopped-state behavior."""
        idx = self._history_list.GetFirstSelected()
        if idx == wx.NOT_FOUND:
            return False
        return self._play_history_row(idx)

    def _history_nav_base(self) -> Optional[int]:
        """Navigation reference point for Previous/Next: whichever row is
        actually playing, falling back to whatever's merely selected if
        nothing's playing yet -- same pattern as PodcastPanel's episode
        navigation."""
        if self._playing_history_id is not None:
            for i, row in enumerate(self._history_rows):
                if row["id"] == self._playing_history_id:
                    return i
        idx = self._history_list.GetFirstSelected()
        return idx if idx != wx.NOT_FOUND else None

    def history_has_previous(self) -> bool:
        base = self._history_nav_base()
        return bool(self._history_rows) and base is not None and base > 0

    def history_has_next(self) -> bool:
        base = self._history_nav_base()
        return bool(self._history_rows) and base is not None and base < len(self._history_rows) - 1

    def history_previous(self) -> None:
        base = self._history_nav_base()
        if base is not None and base > 0:
            self._play_history_row(base - 1)

    def history_next(self) -> None:
        base = self._history_nav_base()
        if base is not None and self._history_rows and base < len(self._history_rows) - 1:
            self._play_history_row(base + 1)

    def history_first(self) -> None:
        if self._history_rows:
            self._play_history_row(0)

    def history_last(self) -> None:
        if self._history_rows:
            self._play_history_row(len(self._history_rows) - 1)
