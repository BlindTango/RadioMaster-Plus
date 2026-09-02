"""Main window for RadioMaster+ with menu bar, listbook, and now playing bar."""

import logging
import os
import wx
from typing import Any

from radiomaster.ui.status_bar import StatusBar
from radiomaster.ui.now_playing_bar import NowPlayingBar
from radiomaster.ui.lyrics_panel import LyricsPanel
from radiomaster.ui.effects_menu import EffectsMenu
from radiomaster.ui.radio_panel import RadioPanel
from radiomaster.ui.podcast_panel import PodcastPanel
from radiomaster.ui.audiobook_panel import AudiobookPanel
from radiomaster.ui.media_player_panel import MediaPlayerPanel
from radiomaster.ui.youtube_panel import YouTubePanel
from radiomaster.ui.downloads_panel import DownloadsPanel
from radiomaster.ui.scheduler_panel import SchedulerPanel
from radiomaster.ui.search_bar import SearchBar
from radiomaster.ui.equalizer_dialog import EqualizerDialog
from radiomaster.ui.tray_icon import TrayIcon
from radiomaster.engine.playback_engine import PlaybackEngine
from radiomaster.utils.config import ConfigManager
from radiomaster.database.connection import DatabaseManager
from radiomaster.services.sleep_timer import SleepTimer
from radiomaster.services.station_api import StationAPI
from radiomaster.services.station_db import StationDB
from radiomaster.services.station_updater import StationUpdater
from radiomaster.utils.accessibility import set_accessible_name
from radiomaster.i18n import _


class MainWindow(wx.Frame):
    """Main application window."""

    def __init__(self, config: ConfigManager, db: DatabaseManager,
                 theme_manager: Any, paths: dict[str, str],
                 scheduler_service: Any = None) -> None:
        self._config = config
        self._db = db
        self._theme_manager = theme_manager
        self._paths = paths
        self._scheduler_service = scheduler_service
        self._engine = PlaybackEngine()
        # Restore saved effect enabled/preset/params state before anything
        # that reads it (the Effects menu, built below, queries the engine
        # directly for its initial checkmarks) -- otherwise every effect
        # would silently reset to "off" on every launch.
        self._engine.restore_effects_state(self._config.get("effects", default={}))
        self._is_muted = False
        self._pre_mute_volume = 0.8
        # System tray (Settings > General > Minimize/Close to tray) --
        # created lazily on first actual hide, not here, so nothing changes
        # for users who leave both settings off. request_exit() is the only
        # path that's allowed to actually close the window instead of
        # hiding it to the tray; _on_close checks it.
        self._tray_icon: TrayIcon | None = None
        self._exiting = False
        self._tray_notice_shown = False
        # engine.position counts seconds since play() was called -- correct
        # as a "seconds into this song" clock for local files/podcasts/etc
        # (play() IS the song starting), but for radio play() only ever
        # happens once, when the station is tuned in; a new song starting
        # mid-stream doesn't reset it. This offset is engine.position at
        # the moment a new song was *detected* (see
        # _on_radio_now_playing_changed), subtracted back out in
        # _on_lyrics_timer so LRC highlighting compares against seconds
        # into the current SONG, not seconds since the station was tuned in.
        self._lyrics_song_start_position = 0.0
        # Playback-related settings (output device, normalization,
        # ReplayGain, auto-reconnect, radio browsing prefs, accessibility)
        # are all applied together at the end of __init__ via
        # _apply_settings_changes(), once the UI it needs to touch exists.
        self._sleep_timer = SleepTimer()
        self._station_api = StationAPI()
        self._station_db = StationDB()
        self._station_updater = StationUpdater(self._station_api, self._station_db)
        from radiomaster.services.station_update_scheduler import StationUpdateScheduler
        self._station_update_scheduler = StationUpdateScheduler(
            self._station_updater, on_result=self._on_station_update_result,
        )
        self._station_update_scheduler.start(
            self._config.get("radio.station_update_frequency", default="weekly")
        )

        # TAB_TRAVERSAL must be part of the constructor's style, not added
        # afterward via SetWindowStyleFlag() -- wx's control-container
        # navigation machinery (what lets Tab escape a nested composite
        # panel like SearchBar/NowPlayingBar up to the Frame and on to the
        # next sibling) is wired up during construction. Retrofitting the
        # bit later leaves the Frame LOOKING tab-traversal-enabled but
        # never escaping nested panels -- Tab just wraps forever inside
        # whichever panel currently has focus.
        super().__init__(None, title=_("RadioMaster+"), size=(1200, 800),
                          style=wx.DEFAULT_FRAME_STYLE | wx.TAB_TRAVERSAL)
        # Without a floor, a sighted user can drag/snap the window down to
        # a size where controls start clipping or overlapping (the
        # transport bar alone -- First/Rewind/.../Last, Vol/Rate/Pan,
        # Record, Mute -- needs ~900px to lay out without crowding).
        # Nothing enforced this before.
        self.SetMinSize((900, 650))

        from radiomaster.utils.paths import get_resource_path
        icon_path = get_resource_path("icon.ico")
        if os.path.exists(icon_path):
            self.SetIcon(wx.Icon(icon_path, wx.BITMAP_TYPE_ICO))

        from radiomaster.utils.global_hotkeys import GlobalHotkeyManager
        self._global_hotkey_manager = GlobalHotkeyManager(self)

        self._setup_menu_bar()
        self._setup_ui()
        self._sync_view_menu_checks()
        self._setup_engine_callbacks()
        self._setup_accelerators()
        self._bind_events()
        # Nothing has played yet, so Fast Forward/Rewind/history nav all
        # start out correctly greyed out rather than looking clickable
        # until the first _on_engine_state/_on_page_changed call.
        self._update_transport_button_states()

        # Recolor whenever the theme changes -- from the menu (_apply_theme)
        # or from the Theme Editor dialog saving/applying a custom theme.
        self._theme_manager.on_theme_changed(lambda theme_key: self._recolor_widgets(self))
        self._recolor_widgets(self)

        # Apply the rest of the saved settings (high contrast, font,
        # ReplayGain, radio browsing preferences...) now that the UI exists
        # to apply them to, instead of only taking effect the first time
        # Settings happens to be opened and saved.
        self._apply_settings_changes()

        # Restore last session's volume/rate/pan. Deliberately separate
        # from _apply_settings_changes() above -- that function also runs
        # every time Settings > OK is pressed, and re-applying rate there
        # would trigger an unwanted ffplay restart (rate changes restart
        # video playback) any time the user saves an unrelated setting
        # while a video happens to be playing. This runs once, at startup.
        self._now_playing.set_volume(self._config.get("playback.volume", default=0.8))
        self._now_playing.set_rate(self._config.get("playback.rate", default=1.0))
        self._now_playing.set_pan(self._config.get("playback.pan", default=0.0))
        self._engine.set_volume(self._config.get("playback.volume", default=0.8))
        self._engine.set_rate(self._config.get("playback.rate", default=1.0))
        self._engine.set_pan(self._config.get("playback.pan", default=0.0))

        self._register_global_hotkeys()

        # Deferred via CallAfter so it runs after the window is fully
        # constructed and shown, the same reason engine.play() itself is
        # always dispatched off the calling thread -- connecting to a
        # stream can stall for a couple of seconds and must not block
        # startup.
        wx.CallAfter(self._radio_panel.play_last_station_if_enabled)

        if self._config.get("updates.check_on_startup", default=True) and self._update_check_due():
            self._check_updates(silent=True)

        # Background auto-update of the bundled yt-dlp.exe (the "YouTube
        # library") -- see _auto_update_ytdlp. Runs off the UI thread and
        # only if the user hasn't turned it off in Settings > Advanced.
        if self._config.get("updates.ytdlp_auto_update", default=True) and self._ytdlp_update_due():
            self._auto_update_ytdlp()

        self.Centre()

    @property
    def engine(self) -> PlaybackEngine:
        """The shared playback engine (app.py stops it on exit)."""
        return self._engine

    def _recolor_widgets(self, window: wx.Window, colors: dict[str, str] | None = None) -> None:
        """Recursively apply colors to window and its descendants.

        With no override, uses the active theme's colors (selecting a theme
        previously only updated a status-bar label and a config key -- no
        control anywhere actually changed color). *colors*, when given, lets
        callers (e.g. the high-contrast setting) force specific colors using
        the same walk instead of duplicating it."""
        if colors is None:
            tm = self._theme_manager
            colors = {
                "bg": tm.get_color("bg_primary"),
                "fg": tm.get_color("text_primary"),
                "control_bg": tm.get_color("control_face"),
                "control_fg": tm.get_color("control_text"),
            }
        bg = colors["bg"]
        fg = colors["fg"]
        control_bg = colors["control_bg"]
        control_fg = colors["control_fg"]
        control_types = (
            wx.Button, wx.ListCtrl, wx.TextCtrl, wx.ComboBox, wx.Choice,
            wx.Slider, wx.CheckBox, wx.RadioButton, wx.SpinCtrl,
        )

        def walk(win: wx.Window) -> None:
            try:
                if isinstance(win, control_types):
                    win.SetBackgroundColour(control_bg)
                    win.SetForegroundColour(control_fg)
                else:
                    win.SetBackgroundColour(bg)
                    win.SetForegroundColour(fg)
            except Exception:
                pass
            for child in win.GetChildren():
                walk(child)
            win.Refresh()

        walk(window)
        window.Layout()

    def _apply_font_recursive(self, window: wx.Window, font: wx.Font) -> None:
        """Apply *font* to window and every descendant."""
        def walk(win: wx.Window) -> None:
            try:
                win.SetFont(font)
            except Exception:
                pass
            for child in win.GetChildren():
                walk(child)
            # A changed font can change a control's natural size. Calling
            # Layout() only on the top-level `window` re-flows just its
            # own immediate sizer -- since search_bar/listbook/etc. are
            # nested one level deeper under content_panel (see _setup_ui),
            # that alone wouldn't reach the sizer that actually holds
            # them. Layout() at every level a sizer exists does.
            if win.GetSizer() is not None:
                win.Layout()

        walk(window)
        window.Refresh()

    def _setup_menu_bar(self) -> None:
        """Create the menu bar."""
        menubar = wx.MenuBar()
        self._menu_ids: dict[str, int] = {}

        # File menu
        file_menu = wx.Menu()
        file_menu.Append(wx.ID_OPEN, "&Open File...\tCtrl+O")
        self._menu_ids["open_url"] = wx.NewIdRef()
        file_menu.Append(self._menu_ids["open_url"], "Open &URL...\tCtrl+U")
        self._menu_ids["open_folder"] = wx.NewIdRef()
        file_menu.Append(self._menu_ids["open_folder"], "Open &Folder...\tCtrl+Shift+O")
        file_menu.AppendSeparator()
        self._menu_ids["import_opml"] = wx.NewIdRef()
        file_menu.Append(self._menu_ids["import_opml"], "Import OPML...")
        self._menu_ids["export_opml"] = wx.NewIdRef()
        file_menu.Append(self._menu_ids["export_opml"], "Export OPML...")
        file_menu.AppendSeparator()
        file_menu.Append(wx.ID_EXIT, "E&xit\tAlt+F4")
        menubar.Append(file_menu, "&File")

        # View menu -- toggle_equalizer/toggle_lyrics/fullscreen are real
        # checkable items synced to actual state via _sync_view_menu_checks()
        # (called once after _setup_ui(), since e.g. _lyrics_panel doesn't
        # exist yet at this point in __init__) and after each toggle action.
        self._view_toggle_items: dict[str, wx.MenuItem] = {}
        view_menu = wx.Menu()
        self._menu_ids["toggle_equalizer"] = wx.NewIdRef()
        self._view_toggle_items["toggle_equalizer"] = view_menu.AppendCheckItem(
            self._menu_ids["toggle_equalizer"], "Toggle &Equalizer\tCtrl+Shift+E")
        self._menu_ids["toggle_lyrics"] = wx.NewIdRef()
        self._view_toggle_items["toggle_lyrics"] = view_menu.AppendCheckItem(
            self._menu_ids["toggle_lyrics"], "Toggle &Lyrics Panel\tCtrl+L")
        view_menu.AppendSeparator()
        self._menu_ids["fullscreen"] = wx.NewIdRef()
        self._view_toggle_items["fullscreen"] = view_menu.AppendCheckItem(
            self._menu_ids["fullscreen"], "&Fullscreen\tF11")

        # Theme submenu
        theme_menu = wx.Menu()
        self._menu_ids["theme_light"] = wx.NewIdRef()
        theme_menu.Append(self._menu_ids["theme_light"], "Default Light")
        self._menu_ids["theme_dark"] = wx.NewIdRef()
        theme_menu.Append(self._menu_ids["theme_dark"], "Default Dark")
        theme_menu.AppendSeparator()
        self._menu_ids["theme_editor"] = wx.NewIdRef()
        theme_menu.Append(self._menu_ids["theme_editor"], "Theme Editor...")
        view_menu.AppendSubMenu(theme_menu, "&Theme")

        # Language submenu
        lang_menu = wx.Menu()
        self._menu_ids["lang_en"] = wx.NewIdRef()
        lang_menu.Append(self._menu_ids["lang_en"], "English")
        view_menu.AppendSubMenu(lang_menu, "&Language")
        menubar.Append(view_menu, "&View")

        # Effects menu (built by EffectsMenu class)
        self._effects_menu = EffectsMenu(
            menubar,
            get_params=lambda eid: self._engine.get_effect_params(eid),
            is_enabled=lambda eid: self._engine._effects.get(eid, {}).get("enabled", False),
            on_toggle=self._on_effect_toggle,
            on_preset=self._on_effect_preset,
            get_preset=lambda eid: self._engine.get_effect_preset(eid),
            apply_live=lambda eid, params: self._engine.apply_effect_params(eid, params),
        )

        # Tools menu
        tools_menu = wx.Menu()
        self._menu_ids["sleep_timer"] = wx.NewIdRef()
        tools_menu.Append(self._menu_ids["sleep_timer"], "&Sleep Timer...\tCtrl+T")
        self._menu_ids["download_manager"] = wx.NewIdRef()
        tools_menu.Append(self._menu_ids["download_manager"], "&Download Manager...\tCtrl+D")
        self._menu_ids["scheduler"] = wx.NewIdRef()
        tools_menu.Append(self._menu_ids["scheduler"], "&Recording Scheduler...\tCtrl+R")
        tools_menu.AppendSeparator()
        self._menu_ids["track_identifier"] = wx.NewIdRef()
        tools_menu.Append(self._menu_ids["track_identifier"], "&Track Identifier...\tCtrl+I")
        self._menu_ids["track_splitter"] = wx.NewIdRef()
        tools_menu.Append(self._menu_ids["track_splitter"], "Split &Track...")
        self._menu_ids["shortcut_editor"] = wx.NewIdRef()
        tools_menu.Append(self._menu_ids["shortcut_editor"], "&Keyboard Shortcuts...\tCtrl+K")
        tools_menu.AppendSeparator()
        tools_menu.Append(wx.ID_PREFERENCES, "&Settings...\tCtrl+,")
        menubar.Append(tools_menu, "&Tools")

        # Help menu
        help_menu = wx.Menu()
        self._menu_ids["user_manual"] = wx.NewIdRef()
        help_menu.Append(self._menu_ids["user_manual"], "&User Manual\tF1")
        self._menu_ids["quick_start"] = wx.NewIdRef()
        help_menu.Append(self._menu_ids["quick_start"], "&Quick Start Guide")
        self._menu_ids["release_notes"] = wx.NewIdRef()
        help_menu.Append(self._menu_ids["release_notes"], "&Release Notes")
        self._menu_ids["update_ytdlp"] = wx.NewIdRef()
        help_menu.Append(self._menu_ids["update_ytdlp"], "Update &YouTube Library...")
        help_menu.AppendSeparator()
        self._menu_ids["check_updates"] = wx.NewIdRef()
        help_menu.Append(self._menu_ids["check_updates"], "Check for &Updates...")
        help_menu.Append(wx.ID_ABOUT, "&About RadioMaster+")
        menubar.Append(help_menu, "&Help")

        self.SetMenuBar(menubar)

    def _setup_ui(self) -> None:
        """Create the main UI layout using wx.Listbook (same as PyClone).
        The listbook is placed FIRST in the tab order so it receives focus
        before the playback controls.

        Everything (except the native status bar, which wx requires to be
        a direct child of the Frame) is parented to one wx.Panel, exactly
        like PyClone's `panel = wx.Panel(self)` -- this isn't cosmetic:
        wx.Frame does not reliably propagate Tab navigation from a nested
        composite panel (SearchBar, NowPlayingBar are each their own
        wx.Panel) up to the next sibling, confirmed empirically with a
        minimal repro, even with TAB_TRAVERSAL set on the Frame itself.
        wx.Panel does implement that propagation correctly. Routing every
        top-level child through one Panel makes Tab flow through the whole
        window (search bar -> listbook tab list -> current page's own
        controls, in order -> transport bar -> lyrics panel, and back)
        with zero custom EVT_NAVIGATION_KEY handling anywhere -- which is
        exactly why PyClone never needed any."""
        self._content_panel = wx.Panel(self)
        frame_sizer = wx.BoxSizer(wx.VERTICAL)
        frame_sizer.Add(self._content_panel, 1, wx.EXPAND)
        self.SetSizer(frame_sizer)

        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # Search bar
        self._search_bar = SearchBar(self._content_panel)
        self._search_bar.on_search(self._on_global_search)
        main_sizer.Add(self._search_bar, 0, wx.EXPAND | wx.ALL, 4)

        # Status bar — created before the listbook so RadioPanel can use it.
        # Must stay parented to the Frame itself (self), not the content
        # panel: wx.Frame.SetStatusBar() requires that.
        self._status_bar = StatusBar(self)
        self.SetStatusBar(self._status_bar)

        # Listbook for tabs — placed first so it gets focus before playback controls
        self._listbook = wx.Listbook(self._content_panel, style=wx.LB_DEFAULT)
        set_accessible_name(self._listbook, "Content Tabs")
        self._listbook.GetListView().SetFocusFromKbd()
        set_accessible_name(self._listbook.GetListView(), "Tab List")

        # Create tab panels
        self._radio_panel = RadioPanel(
            self._listbook,
            station_api=self._station_api,
            station_db=self._station_db,
            station_updater=self._station_updater,
            engine=self._engine,
            set_status=self._status_bar.set_status,
            db=self._db,
        )
        self._radio_panel.on_history_changed = self._update_transport_button_states
        self._radio_panel.on_now_playing_changed = self._on_radio_now_playing_changed
        # Station list context menu's Volume/Pan/Rate submenus (see
        # RadioPanel._on_station_context_menu) delegate here rather than
        # touching self._engine directly, so the transport bar's own
        # sliders and saved config stay in sync with a change made from
        # the context menu, the same as one made from the sliders
        # themselves.
        self._radio_panel.on_volume_step = self._on_volume_step
        self._radio_panel.on_pan_step = self._on_pan_step
        self._radio_panel.on_rate_step = self._on_rate_step
        self._radio_panel.on_mute_toggle = self._on_mute_toggle
        self._podcast_panel = PodcastPanel(self._listbook, self._db, self._engine)
        self._audiobook_panel = AudiobookPanel(self._listbook, self._db, self._engine)
        self._media_panel = MediaPlayerPanel(self._listbook, self._db, self._engine)
        self._youtube_panel = YouTubePanel(self._listbook, self._db, self._engine)
        self._downloads_panel = DownloadsPanel(self._listbook, self._db, self._engine)
        self._downloads_panel.on_stop_recording = self._radio_panel.stop_recording_by_download_id
        self._downloads_panel.on_check_recording_active = self._radio_panel.is_recording_active
        self._scheduler_panel = SchedulerPanel(self._listbook, self._db, self._scheduler_service)

        self._listbook.AddPage(self._radio_panel, "Radio")
        self._listbook.AddPage(self._podcast_panel, "Podcasts")
        self._listbook.AddPage(self._audiobook_panel, "Audiobooks")
        self._listbook.AddPage(self._media_panel, "Media Player")
        self._listbook.AddPage(self._youtube_panel, "YouTube")
        self._listbook.AddPage(self._downloads_panel, "Downloads")
        self._listbook.AddPage(self._scheduler_panel, "Scheduler")

        # wx.Listbook's native list panel on MSW uses a small fixed
        # default width that ignores actual tab-label content entirely --
        # confirmed via testing that neither InvalidateBestSize(),
        # SendSizeEvent(), nor tab insertion order changes it. Without
        # this, "Media Player"/"Downloads"/"Audiobooks" visually clip to
        # "Media ..."/"Downlo..."/"Audiob...". Re-applying the needed
        # width via CallAfter (so it runs after the native layout pass,
        # which otherwise reasserts its own fixed width and wins if set
        # synchronously) is the only way found to make it respect content.
        self._listbook.Bind(wx.EVT_SIZE, lambda e: (wx.CallAfter(self._fix_listbook_tab_width), e.Skip()))
        wx.CallAfter(self._fix_listbook_tab_width)

        main_sizer.Add(self._listbook, 1, wx.EXPAND)

        # Now Playing bar — placed right after the listbook so transport controls
        # are the first thing reachable via Tab after content navigation
        self._now_playing = NowPlayingBar(self._content_panel)
        main_sizer.Add(self._now_playing, 0, wx.EXPAND)
        self._radio_panel.on_recording_changed = self._on_radio_recording_changed
        self._radio_panel.on_format_detected = self._status_bar.set_format

        # Lyrics/Show Notes panel
        self._lyrics_panel = LyricsPanel(self._content_panel)
        main_sizer.Add(self._lyrics_panel, 1, wx.EXPAND | wx.TOP, 2)

        self._content_panel.SetSizer(main_sizer)

        # Bind listbook page change for status announcements
        self._listbook.Bind(wx.EVT_LISTBOOK_PAGE_CHANGED, self._on_page_changed)

        # Wire LyricsPanel to LyricsService with a timer for LRC sync
        self._lyrics_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_lyrics_timer, self._lyrics_timer)
        self._lyrics_timer.Start(500)

        # Set initial focus to the listbook's tab list.
        # wx.Listbook's internal list view needs a moment to initialize.
        wx.CallLater(100, self._listbook.GetListView().SetFocus)
        wx.CallLater(300, self._listbook.GetListView().SetFocus)

        # Tab order: search bar -> listbook -> now playing -> lyrics. This is
        # already the sibling creation order above, so no MoveAfterInTabOrder
        # calls are needed here (they previously scrambled it to
        # listbook -> now playing -> lyrics -> search bar). No custom
        # navigation glue needed either now (see docstring above).

    def _on_lyrics_timer(self, evt: wx.TimerEvent) -> None:
        """Update LRC line highlighting based on current playback position."""
        if self._engine.state != "playing":
            return
        # For local files/podcasts/etc, _lyrics_song_start_position is 0
        # (play() itself is the song starting, so engine.position is
        # already "seconds into this song"). For radio, it's the position
        # recorded when the current song was detected via ICY metadata --
        # subtracting it converts "seconds since the station was tuned
        # in" into "seconds into the current song", which is what the LRC
        # timestamps are actually relative to. Clamped at 0 in case a
        # song-change notification races slightly ahead of position itself.
        pos = max(0.0, self._engine.position - self._lyrics_song_start_position)
        # Find the current LRC line
        if hasattr(self._lyrics_panel, '_lrc_lines') and self._lyrics_panel._lrc_lines:
            current_idx = -1
            for i, (ts, text) in enumerate(self._lyrics_panel._lrc_lines):
                if ts <= pos:
                    current_idx = i
                else:
                    break
            if current_idx >= 0:
                self._lyrics_panel.highlight_sentence(current_idx)

    def _fix_listbook_tab_width(self) -> None:
        """Widen the listbook's tab list to fit its widest label -- see
        the binding site (in _setup_ui) for why this is needed at all."""
        if not self._listbook:
            return
        lv = self._listbook.GetListView()
        dc = wx.ClientDC(lv)
        dc.SetFont(lv.GetFont())
        labels = [self._listbook.GetPageText(i) for i in range(self._listbook.GetPageCount())]
        needed = max((dc.GetTextExtent(t).width for t in labels), default=80) + 40
        current = lv.GetSize()
        if current.width != needed:
            lv.SetSize((needed, current.height))
            lv.SetColumnWidth(0, needed - 20)

    def _on_page_changed(self, evt: wx.CommandEvent) -> None:
        """Announce tab switch in status bar."""
        idx = evt.GetSelection()
        page_text = self._listbook.GetPageText(idx)
        self._status_bar.set_status(f"Switched to {page_text}")
        self._update_transport_button_states()

    def _update_transport_button_states(self) -> None:
        """Grey out transport controls that don't make sense right now:
        Stop has nothing to stop when nothing is playing or paused (e.g.
        at launch, before anything's ever been played -- it was never
        greyed out at all before, so it was always clickable even then).
        Fast Forward/Rewind/the position slider have nothing to seek to on
        a live radio stream (duration is always 0 for one), and
        First/Previous/Next/Last -- station history navigation, on the
        Radio tab -- have nowhere to go past either end of that history."""
        self._now_playing.set_stoppable(self._engine.state != "stopped")
        self._now_playing.set_seekable(self._engine.duration > 0)
        if self._listbook.GetSelection() == 0:
            self._now_playing.set_history_state(
                self._radio_panel.history_has_previous(),
                self._radio_panel.history_has_next(),
            )
        else:
            self._now_playing.set_history_state(True, True)

    def _setup_engine_callbacks(self) -> None:
        """Connect playback engine callbacks to UI."""
        # PlaybackEngine's monitor thread fires these callbacks from a
        # background thread; wx UI calls must be marshalled back to the
        # main thread or the app crashes/hangs during playback.
        self._engine.on_state_change(lambda state: wx.CallAfter(self._on_engine_state, state))
        self._engine.on_position_update(lambda pos, dur: wx.CallAfter(self._on_engine_position, pos, dur))
        self._engine.on_error(lambda message: wx.CallAfter(self._on_engine_error, message))
        self._engine.on_buffering(lambda percent: wx.CallAfter(self._status_bar.set_buffering, percent))
        # on_track_finished is a single shared signal (not per-tab), so
        # each candidate gets a turn to claim it via its own "was this
        # actually my track" guard -- MediaPlayerPanel first (existing
        # behavior, unchanged), then PodcastPanel if Media declined.
        self._engine.on_track_finished(lambda: wx.CallAfter(self._on_track_finished))
        self._engine.on_effects_changed(self._on_effects_state_changed)

        self._now_playing.on_play(lambda: self._on_transport_play_pause())
        self._now_playing.on_stop(lambda: self._radio_panel._on_stop() if self._listbook.GetSelection() == 0 else self._engine.stop())
        self._now_playing.on_record(lambda: self._radio_panel._on_record() if self._listbook.GetSelection() == 0 else None)
        self._now_playing.on_mute(lambda: self._on_mute_toggle())
        self._now_playing.on_next(lambda: self._next_track())
        self._now_playing.on_prev(lambda: self._prev_track())
        self._now_playing.on_first(lambda: self._first_track())
        self._now_playing.on_last(lambda: self._last_track())
        self._now_playing.on_seek(lambda pos: self._engine.seek(pos))
        self._now_playing.on_volume(self._on_volume_change)
        self._now_playing.on_rate(self._on_rate_change)
        self._now_playing.on_pan(self._on_pan_change)
        self._now_playing.on_ffwd(lambda: self._fast_forward())
        self._now_playing.on_rewind(lambda: self._rewind())

    def _setup_accelerators(self) -> None:
        """Build every live accelerator from the editor's command catalogue."""
        from radiomaster.ui.shortcut_editor import load_shortcuts, shortcut_to_accel

        shortcuts = load_shortcuts(self._config)
        self._active_shortcuts = shortcuts

        def toggle_effect(effect_id: str) -> None:
            enabled = not self._engine._effects.get(effect_id, {}).get("enabled", False)
            self._on_effect_toggle(effect_id, enabled)
            self._effects_menu.set_enabled(effect_id, enabled)

        handlers = {
            "play_pause": self._on_play_pause_accel, "stop": self._on_stop_accel,
            "volume_up": lambda: self._on_volume_step(0.05), "volume_down": lambda: self._on_volume_step(-0.05),
            "mute": self._on_mute_toggle, "seek_forward": self._fast_forward, "seek_backward": self._rewind,
            "rate_up": lambda: self._on_rate_step(0.1), "rate_down": lambda: self._on_rate_step(-0.1),
            "speed_up": lambda: self._on_rate_step(0.1),
            "speed_down": lambda: self._on_rate_step(-0.1),
            "pan_left": lambda: self._on_pan_step(-0.1), "pan_right": lambda: self._on_pan_step(0.1),
            "first_track": self._first_track, "previous_track": self._prev_track,
            "next_track": self._next_track, "last_track": self._last_track,
            "record": self._radio_panel._on_record, "search": self._on_search_focus,
            "open_file": self._on_open_file, "open_url": self._on_open_url, "open_folder": self._on_open_folder,
            "import_opml": self._on_import_opml, "export_opml": self._on_export_opml, "exit": self.request_exit,
            "toggle_equalizer": self._show_equalizer, "toggle_lyrics": self._toggle_lyrics,
            "toggle_fullscreen": self._toggle_fullscreen, "theme_light": lambda: self._apply_theme("default"),
            "theme_dark": lambda: self._apply_theme("dark"), "theme_editor": self._show_theme_editor,
            "language_english": lambda: self._set_language("en"), "sleep_timer": self._show_sleep_timer,
            "download_manager": lambda: self._switch_tab(5), "recording_scheduler": lambda: self._switch_tab(6),
            "track_identifier": self._show_track_identifier, "track_splitter": self._show_track_splitter,
            "keyboard_shortcuts": self._show_shortcut_editor,
            "settings": self._show_settings, "user_manual": self._show_user_manual,
            "quick_start": self._show_quick_start, "release_notes": self._show_release_notes,
            "update_ytdlp": self._update_ytdlp, "check_updates": self._check_updates, "about": self._show_about,
        }
        for index in range(7):
            handlers[f"panel_{('radio', 'podcasts', 'audiobooks', 'media', 'youtube', 'downloads', 'scheduler')[index]}"] = (
                lambda i=index: self._switch_tab(i)
            )
        for effect_id in ("echo", "equalizer", "reverb", "dynamic_range", "pitch_tempo", "chorus",
                          "compressor", "distortion", "flanger", "gargle"):
            handlers[f"effect_{effect_id}"] = lambda eid=effect_id: toggle_effect(eid)
        self._shortcut_handlers = handlers

        entries = []
        # Keep ID refs alive and reuse them when the table is rebuilt after Save.
        if not hasattr(self, "_shortcut_command_ids"):
            self._shortcut_command_ids = {action: wx.NewIdRef() for action in handlers}
            for action, handler in handlers.items():
                self.Bind(wx.EVT_MENU, lambda event, callback=handler: callback(), id=self._shortcut_command_ids[action])
        for action, handler in handlers.items():
            accel = shortcut_to_accel(shortcuts.get(action))
            if accel and not shortcuts[action].get("global") and shortcuts[action].get("key") != "Tab":
                entries.append((*accel, self._shortcut_command_ids[action]))
        self.SetAcceleratorTable(wx.AcceleratorTable(entries))
        if not getattr(self, "_shortcut_char_hook_bound", False):
            self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
            self._shortcut_char_hook_bound = True
        self._register_global_hotkeys()

    def _on_char_hook(self, evt: wx.KeyEvent) -> None:
        from radiomaster.ui.shortcut_editor import shortcut_signature
        modifiers = []
        if evt.ControlDown(): modifiers.append("Ctrl")
        if evt.ShiftDown(): modifiers.append("Shift")
        if evt.AltDown(): modifiers.append("Alt")
        signature = (tuple(sorted(modifiers)), "Tab")
        next_shortcut = self._active_shortcuts.get("next_tab", {})
        previous_shortcut = self._active_shortcuts.get("previous_tab", {})
        next_signature = shortcut_signature(next_shortcut) if not next_shortcut.get("global") else ((), "")
        previous_signature = (
            shortcut_signature(previous_shortcut) if not previous_shortcut.get("global") else ((), "")
        )
        if evt.GetKeyCode() == wx.WXK_TAB and signature in (next_signature, previous_signature):
            count = self._listbook.GetPageCount()
            if count:
                idx = self._listbook.GetSelection()
                if idx == wx.NOT_FOUND:
                    idx = 0
                new_idx = (idx - 1) if signature == previous_signature else (idx + 1)
                new_idx %= count
                self._switch_tab(new_idx)
        else:
            evt.Skip()

    def _on_stop_accel(self) -> None:
        """Handle the global Stop accelerator (default Ctrl+Shift+S)."""
        if self._listbook.GetSelection() == 0:
            self._radio_panel._on_stop()
        else:
            self._engine.stop()

    def _on_transport_play_pause(self) -> None:
        """Play/Pause from the global Now Playing bar button.

        Always decided from the engine's actual current state rather than
        the button's own label -- see NowPlayingBar._on_play_pause. Also
        fixes a gap where, on any tab other than Radio, this previously did
        nothing at all when resuming from pause (only the pause direction
        was wired), leaving the button permanently stuck showing "paused".
        """
        if self._listbook.GetSelection() == 0:
            self._radio_panel._on_play_pause()
            return
        if self._engine.state == "paused":
            self._engine.resume()
        elif self._engine.state in ("playing", "buffering"):
            self._engine.pause()
        elif self._engine.state == "stopped":
            # On the Downloads tab, a selected History row takes priority
            # over resuming whatever was last played from elsewhere --
            # selecting something there and pressing Play is exactly what
            # "get the currently selected history download played by the
            # transport bar" means. play_selected() itself does nothing
            # (returns False) when nothing's selected, so this falls
            # through to the normal resume-current_url behavior below.
            if self._listbook.GetSelection() == self._TAB_DOWNLOADS and self._downloads_panel.play_selected():
                return
            # Pressing Stop clears state back to "stopped" but deliberately
            # leaves current_url/title/duration alone (see
            # PlaybackEngine.stop()) -- exactly so Play here can restart
            # the same episode/track from the beginning, matching what the
            # button visually promises. Previously this state had no
            # branch at all, so Play silently did nothing after Stop.
            if self._engine.current_url:
                self._engine.play(
                    self._engine.current_url, title=self._engine.current_title,
                    artist=self._engine.current_artist, is_video=self._engine.is_video,
                    duration=self._engine.duration,
                )

    def _on_play_pause_accel(self) -> None:
        """Handle Ctrl+P / Space play/pause accelerator -- same logic as
        the transport bar's own Play/Pause button (_on_transport_play_pause),
        which already handles every state correctly; this used to
        duplicate it with its own, different (and broken -- play("") is
        not a real track) stopped-state handling."""
        self._on_transport_play_pause()

    def _on_search_focus(self) -> None:
        """Focus the search bar."""
        self._search_bar.set_query("")

    def _on_close(self, event: wx.CloseEvent) -> None:
        """Stop playback before the frame is destroyed.

        Without this, the engine's monitor thread keeps running after the
        window (and its widgets) are gone, posting wx.CallAfter position
        updates that hit already-deleted controls (RuntimeError) during
        shutdown -- a crash that made cleanup unreliable and left the
        ffplay subprocess orphaned and still playing.

        wait=False: the process is exiting anyway (daemon threads die
        with it regardless), so there's no need to block this handler on
        engine.stop()'s internal joins/waits -- stop_flag is still set
        and the output stream still aborted immediately either way, just
        without the up-to-3s wait for full thread teardown. That wait
        used to make EVT_CLOSE handling slow enough that Inno Setup's
        "close running applications" check (see AppMutex in
        radiomaster.iss) gave up before the process actually exited,
        leaving files locked exactly when the installer tried to
        overwrite them mid-update ("DeleteFile failed; Access is denied").
        """
        # Settings > General > "Close to system tray": hide instead of
        # actually exiting, unless the user picked Exit explicitly (File >
        # Exit, the tray menu's Exit, or Alt+F4 while this is off) --
        # request_exit() is the only thing allowed to set _exiting.
        if self._config.get("general.close_to_tray", default=False) and not self._exiting:
            event.Veto()
            self._hide_to_tray()
            return

        self._radio_panel.shutdown_recordings()
        self._engine.stop(wait=False)
        self._station_update_scheduler.shutdown()
        self._config.save()
        self._global_hotkey_manager.unregister_all()
        if self._tray_icon:
            self._tray_icon.RemoveIcon()
            self._tray_icon.Destroy()
            self._tray_icon = None
        event.Skip()

    def _on_iconize(self, event: wx.IconizeEvent) -> None:
        """Settings > General > "Minimize to system tray"."""
        if event.IsIconized() and self._config.get("general.minimize_to_tray", default=True):
            # wx.CallAfter: hiding a frame from inside its own iconize
            # handler while the OS is mid-animation of the minimize can be
            # ignored on some window managers if done synchronously.
            wx.CallAfter(self._hide_to_tray)
            return
        event.Skip()

    def _hide_to_tray(self) -> None:
        if not self._tray_icon:
            self._tray_icon = TrayIcon(self)
        self.Hide()
        if self._config.get("general.show_notifications", default=True) and not self._tray_notice_shown:
            self._tray_notice_shown = True
            self._tray_icon.ShowBalloon(
                "RadioMaster+ is still running",
                "Playback continues in the background. Use the tray icon to reopen or exit.",
            )

    def restore_from_tray(self) -> None:
        """Bring the window back from the tray (tray double-click / Show)."""
        self.Show()
        if self.IsIconized():
            self.Iconize(False)
        self.Raise()
        if self._tray_icon:
            self._tray_icon.RemoveIcon()
            self._tray_icon.Destroy()
            self._tray_icon = None

    def request_exit(self) -> None:
        """The only path allowed to actually close the window instead of
        hiding it to the tray -- File > Exit, the tray menu's Exit, and
        Alt+F4's accelerator all route here."""
        self._exiting = True
        self.Close()

    def _bind_events(self) -> None:
        """Bind menu and other events."""
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.Bind(wx.EVT_ICONIZE, self._on_iconize)

        # File menu
        self.Bind(wx.EVT_MENU, lambda e: self._on_open_file(), id=wx.ID_OPEN)
        self.Bind(wx.EVT_MENU, lambda e: self._on_open_url(), id=self._menu_ids["open_url"])
        self.Bind(wx.EVT_MENU, lambda e: self._on_open_folder(), id=self._menu_ids["open_folder"])
        self.Bind(wx.EVT_MENU, lambda e: self._on_import_opml(), id=self._menu_ids["import_opml"])
        self.Bind(wx.EVT_MENU, lambda e: self._on_export_opml(), id=self._menu_ids["export_opml"])
        self.Bind(wx.EVT_MENU, lambda e: self.request_exit(), id=wx.ID_EXIT)

        # View menu
        self.Bind(wx.EVT_MENU, lambda e: self._show_equalizer(), id=self._menu_ids["toggle_equalizer"])
        self.Bind(wx.EVT_MENU, lambda e: self._toggle_lyrics(), id=self._menu_ids["toggle_lyrics"])
        self.Bind(wx.EVT_MENU, lambda e: self._toggle_fullscreen(), id=self._menu_ids["fullscreen"])

        # Theme menu
        self.Bind(wx.EVT_MENU, lambda e: self._apply_theme("default"), id=self._menu_ids["theme_light"])
        self.Bind(wx.EVT_MENU, lambda e: self._apply_theme("dark"), id=self._menu_ids["theme_dark"])
        self.Bind(wx.EVT_MENU, lambda e: self._show_theme_editor(), id=self._menu_ids["theme_editor"])

        # Language menu
        self.Bind(wx.EVT_MENU, lambda e: self._set_language("en"), id=self._menu_ids["lang_en"])

        # Tools menu
        self.Bind(wx.EVT_MENU, lambda e: self._show_sleep_timer(), id=self._menu_ids["sleep_timer"])
        self.Bind(wx.EVT_MENU, lambda e: self._switch_tab(5), id=self._menu_ids["download_manager"])
        self.Bind(wx.EVT_MENU, lambda e: self._switch_tab(6), id=self._menu_ids["scheduler"])
        self.Bind(wx.EVT_MENU, lambda e: self._show_track_identifier(), id=self._menu_ids["track_identifier"])
        self.Bind(wx.EVT_MENU, lambda e: self._show_track_splitter(), id=self._menu_ids["track_splitter"])
        self.Bind(wx.EVT_MENU, lambda e: self._show_shortcut_editor(), id=self._menu_ids["shortcut_editor"])
        self.Bind(wx.EVT_MENU, lambda e: self._show_settings(), id=wx.ID_PREFERENCES)

        # Help menu
        self.Bind(wx.EVT_MENU, lambda e: self._show_user_manual(), id=self._menu_ids["user_manual"])
        self.Bind(wx.EVT_MENU, lambda e: self._show_quick_start(), id=self._menu_ids["quick_start"])
        self.Bind(wx.EVT_MENU, lambda e: self._show_release_notes(), id=self._menu_ids["release_notes"])
        self.Bind(wx.EVT_MENU, lambda e: self._update_ytdlp(), id=self._menu_ids["update_ytdlp"])
        self.Bind(wx.EVT_MENU, lambda e: self._check_updates(), id=self._menu_ids["check_updates"])
        self.Bind(wx.EVT_MENU, lambda e: self._show_about(), id=wx.ID_ABOUT)

    def _on_open_file(self) -> None:
        """Open a file dialog for media files."""
        wildcard = (
            "All supported files|*.mp3;*.flac;*.ogg;*.wav;*.aac;*.m4a;*.wma;*.opus;"
            "*.mp4;*.mkv;*.avi;*.webm;*.mov;*.m4b"
            "|Audio files|*.mp3;*.flac;*.ogg;*.wav;*.aac;*.m4a;*.wma;*.opus"
            "|Video files|*.mp4;*.mkv;*.avi;*.webm;*.mov"
            "|All files|*.*"
        )
        dlg = wx.FileDialog(self, "Open media file", wildcard=wildcard,
                            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            self._engine.play(path, title=path.split("\\")[-1].split("/")[-1])
        dlg.Destroy()

    def _show_settings(self) -> None:
        """Show the settings dialog."""
        from radiomaster.ui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(
            self, self._config,
            station_updater=self._station_updater,
            on_station_update=self._radio_panel.refresh_after_station_update,
            theme_manager=self._theme_manager,
            on_apply=self._apply_settings_changes,
        )
        if dlg.ShowModal() == wx.ID_OK:
            # Settings saved, apply changes
            self._apply_settings_changes()
        dlg.Destroy()
    
    def _apply_settings_changes(self) -> None:
        """Apply settings changes after dialog closes."""
        # Reload config
        self._config.load()
        
        # Apply accessibility settings
        # NOTE: ConfigManager.get()'s `default` is keyword-only -- passing it
        # positionally (as this previously did) doesn't set a fallback, it's
        # taken as a second *key* to look up, which crashes with
        # AttributeError the moment the first key is missing (e.g. every
        # first run, before Settings has ever been saved). This crashed
        # _apply_settings_changes() -- and therefore Settings > OK, and now
        # also startup -- unconditionally.
        high_contrast = self._config.get('accessibility.high_contrast', default=False)
        dyslexia_font = self._config.get('accessibility.dyslexia_font', default=False)

        # Language is applied in app.py before the UI is constructed. wx
        # controls do not retranslate their existing native labels, so
        # changing I18nManager here produced a confusing half-translated
        # session. Settings labels this honestly as restart-required.

        # Unlike language, themes can be applied safely to existing
        # controls. GeneralPanel stores an actual ThemeManager key (not a
        # lower-cased display label), so built-in and custom themes both
        # take effect immediately after OK or Apply.
        self._theme_manager.apply_theme(
            self._config.get('general.theme', default='default')
        )
        
        if high_contrast:
            # Pure black/white across every control, not just the frame/
            # listbook/status bar -- reuses the same recursive walk built
            # for theme switching instead of a second hand-rolled pass that
            # only reaches three widgets.
            self._recolor_widgets(self, {
                "bg": "#000000", "fg": "#FFFFFF",
                "control_bg": "#000000", "control_fg": "#FFFFFF",
            })
        else:
            # Revert to whatever the active theme says, the same way
            # picking a theme from the View menu does.
            self._recolor_widgets(self)

        # Apply font size + (optionally) the dyslexia-friendly family, to
        # every control -- SetFont() on just the frame doesn't reach
        # children that already exist when it's called after construction.
        # Note: no OpenDyslexic font file is bundled with the app, so unless
        # the user happens to have it installed separately, wx silently
        # falls back to the system default font family here.
        font_size = self._config.get('general.font_size', default=12)
        face_name = "OpenDyslexic" if dyslexia_font else ""
        font = wx.Font(font_size, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL,
                        wx.FONTWEIGHT_NORMAL, False, face_name)
        self._apply_font_recursive(self, font)

        # Apply sound output device (restarts the current stream if playing)
        self._engine.set_output_device(self._config.get('playback.output_device', default=''))
        self._engine.toggle_effect(
            'normalization', self._config.get('playback.normalize_audio', default=False)
        )
        self._engine.set_replaygain_mode(self._config.get('playback.replaygain', default='none'))
        self._engine.set_auto_reconnect(self._config.get('radio.auto_reconnect', default=True))
        self._engine.set_reconnect_settings(
            self._config.get('radio.reconnect_max_attempts', default=5),
            self._config.get('radio.reconnect_interval', default=2.0),
        )

        # Re-apply network settings (proxy, user agent) -- StationAPI was
        # constructed once at startup, so a change here would otherwise only
        # take effect after restarting the app.
        self._station_api.refresh_network_settings()

        # Re-apply radio browsing preferences (default country, duplicate filtering)
        self._radio_panel._apply_sections()

        # If a podcast's episodes are currently on screen, re-sort them to
        # match Settings > Podcasts > Episode order right away instead of
        # only the next time that podcast happens to get (re)selected.
        self._podcast_panel.refresh_episode_order()

        # Downloads settings are live: resize the worker pool for future
        # jobs and update the persistent YouTube audio-format selector.
        wx.GetApp().download_manager.set_max_concurrent(
            self._config.get('downloads.max_concurrent', default=3)
        )
        self._youtube_panel.refresh_download_settings()

        # Scheduled recordings previously kept the folder captured at
        # startup even though manual recordings used the changed setting.
        from radiomaster.utils.paths import get_recordings_dir
        self._scheduler_service.set_recordings_dir(get_recordings_dir())

        # Re-apply the station-list update schedule -- takes effect
        # immediately rather than only on the next launch.
        self._station_update_scheduler.set_frequency(
            self._config.get('radio.station_update_frequency', default='weekly')
        )

        # Reconcile the Windows Run-key entry with the checkbox -- runs on
        # every launch too (this whole method is called once from
        # __init__), so a stale entry left by an install at a different
        # path gets corrected, not just changes made via Settings > OK.
        from radiomaster.utils.startup_registry import set_run_on_startup
        set_run_on_startup(self._config.get('general.start_on_boot', default=False))

        # Refresh UI
        self.Refresh()

    def _show_about(self) -> None:
        """Show the about dialog."""
        from radiomaster import __app_name__, __version__
        wx.MessageBox(
            f"{__app_name__} v{__version__}\n\n"
            "A unified media player for radio, podcasts, YouTube,\n"
            "audiobooks, and local media.\n\n"
            "Built with Python and wxPython.\n"
            "Accessibility is a first-class citizen.",
            f"About {__app_name__}",
            wx.OK | wx.ICON_INFORMATION,
        )

    def _on_track_finished(self) -> None:
        """A track reached its own natural end (engine.on_track_finished).
        Not scoped to whichever tab is active, so each candidate that
        might own it gets a turn via its own try_auto_advance() -- each
        one's internal guard (does the engine's current URL match what it
        itself last played) is what actually decides whether it was theirs
        to advance, not tab selection."""
        if not self._media_panel.try_auto_advance():
            self._podcast_panel.try_auto_advance()

    def _on_effect_toggle(self, effect_id: str, enabled: bool) -> None:
        """Handle an effect's On/Off menu item."""
        self._engine.toggle_effect(effect_id, enabled)

    def _on_effect_preset(self, effect_id: str, preset_name: str, params: dict) -> None:
        """Handle a preset being selected from an effect's submenu or its
        Preset Manager. EffectsMenu syncs its own On/Off checkmark right
        after calling this, since applying a preset auto-enables."""
        self._engine.apply_preset(effect_id, preset_name, params)

    def _on_effects_state_changed(self, effect_id: str, state: dict) -> None:
        """Persist an effect's enabled/preset/params so it survives a
        restart -- fired by PlaybackEngine on every toggle, preset pick,
        or manual param edit (e.g. the equalizer dialog's band sliders)."""
        self._config.set(f"effects.{effect_id}", value=state)
        self._config.save()

    def _on_station_update_result(self, result) -> None:
        """Fired by StationUpdateScheduler's cron-driven background
        updates (see radio.station_update_frequency in Settings > Radio)
        on its own thread, so UI touches must go through wx.CallAfter.
        The Settings > Radio "Update Now" button is a separate,
        self-contained one-off update -- see settings_dialog.RadioPanel
        -- and doesn't go through this scheduler/callback at all."""
        from radiomaster.utils.wx_safe import call_after_safe
        if result.ok:
            call_after_safe(
                self, self._status_bar.set_status,
                f"Status: Station list updated ({result.changed} changed, {result.unchanged} unchanged)"
            )
            call_after_safe(self, self._radio_panel.refresh_after_station_update)
        else:
            call_after_safe(self, self._status_bar.set_status,
                             f"Status: Station list update failed ({result.error})")

    # Volume/rate/pan are saved to config on every change (not just on
    # exit) so a crash or a kill-by-Task-Manager doesn't lose the last
    # setting -- ConfigManager.set() is an in-memory update, cheap enough
    # to call on every slider tick; the disk write in .save() is not, so
    # that's deferred to actual exit (see _on_close/App.OnExit) rather than
    # done here on every tick.
    def _on_volume_change(self, volume: float) -> None:
        self._engine.set_volume(volume)
        self._config.set("playback.volume", value=volume)

    def _on_rate_change(self, rate: float) -> None:
        self._engine.set_rate(rate)
        self._config.set("playback.rate", value=rate)

    def _on_pan_change(self, pan: float) -> None:
        self._engine.set_pan(pan)
        self._config.set("playback.pan", value=pan)

    def _on_mute_toggle(self) -> None:
        """Toggle mute, remembering the exact volume to restore -- this
        used to hard-code the unmute level to 0.8 regardless of what the
        volume slider was actually set to (e.g. muting at 30% and
        unmuting jumped to 80%, far louder than before), and never
        updated the slider position or the button's "Mute On"/"Mute Off"
        label at all (set_muted() existed but nothing ever called it)."""
        if self._is_muted:
            self._is_muted = False
            self._on_volume_change(self._pre_mute_volume)
            self._now_playing.set_volume(self._pre_mute_volume)
            self._now_playing.set_muted(False)
            self._status_bar.set_status("Unmuted")
        else:
            self._is_muted = True
            self._pre_mute_volume = self._engine._volume
            self._engine.set_volume(0.0)
            self._now_playing.set_volume(0.0)
            self._now_playing.set_muted(True)
            self._status_bar.set_status("Muted")

    def _on_engine_state(self, state: str) -> None:
        """Handle playback engine state changes."""
        self._status_bar.set_status(_(state.capitalize()))
        self._status_bar.set_source(self._engine._current_title if state != "stopped" else "")
        if state == "stopped":
            # Nothing playing -- clear the now-stale time/buffer readouts
            # instead of leaving the last track's numbers stuck on screen.
            self._status_bar.set_time_info(0.0, 0.0)
            self._status_bar.set_buffering(100)
        self._now_playing.set_playing(state == "playing")
        self._update_transport_button_states()
        # Video is rendered by ffplay's own native window (the engine
        # launches ffplay without -nodisp for video), so there is no
        # separate in-app video frame to show -- showing a redundant
        # frame on top of ffplay's window is what produced the "two
        # windows" the user had to Alt+F4 twice to dismiss. ffplay's
        # window is the video window; the transport bar in the main
        # window is the control surface.

        # Save play progress when stopping
        if state == "stopped" and self._engine._current_url:
            self._save_play_progress()

        # Restore play progress when starting
        if state == "playing" and self._engine._current_url:
            self._restore_play_progress()

        # Fetch lyrics when a new track starts playing. play() just reset
        # engine.position to 0, so for a genuinely new track (as opposed
        # to a radio station's song changing mid-stream, which doesn't
        # call play() again -- see _on_radio_now_playing_changed) that's
        # also correctly "seconds into this song" with no offset needed.
        if state == "playing" and self._engine._current_title:
            self._lyrics_song_start_position = 0.0
            self._fetch_lyrics_for_current()

    def _save_play_progress(self) -> None:
        """Save current playback position to the database."""
        from radiomaster.utils.config import ConfigManager
        config = ConfigManager.get_instance()
        if not config.get("playback.remember_position", default=True):
            return
        try:
            self._db.execute(
                "INSERT OR REPLACE INTO play_history (source_type, title, artist, url, position, duration) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    "media",
                    self._engine._current_title,
                    self._engine._current_artist,
                    self._engine._current_url,
                    self._engine.position,
                    self._engine.duration,
                ),
            )
            self._db.commit()
        except Exception:
            pass

    def _restore_play_progress(self) -> None:
        """Restore playback position from the database when resuming a track."""
        from radiomaster.utils.config import ConfigManager
        config = ConfigManager.get_instance()
        if not config.get("playback.remember_position", default=True):
            return
        try:
            result = self._db.fetchone(
                "SELECT position FROM play_history WHERE url = ? ORDER BY played_at DESC LIMIT 1",
                (self._engine._current_url,),
            )
            if result and result["position"] > 5:
                # Seek to saved position after a short delay (engine needs to buffer)
                pos = result["position"]
                wx.CallLater(1000, lambda: self._engine.seek(pos))
        except Exception:
            pass

    def _on_radio_now_playing_changed(self, artist: str, title: str) -> None:
        """ICY metadata gave us the actual song now playing, not just the
        station name -- engine._current_title/_current_artist otherwise
        only ever held the station's own name (set once at play() time)
        and an empty artist, which no lyrics provider can match against
        anything. This is what actually makes lyrics work for radio."""
        self._engine._current_artist = artist
        self._engine._current_title = title
        # A radio station's play() only ever runs once, when it's tuned
        # in -- engine.position keeps counting from then, not from when
        # this new song actually started. Recording position *now* (the
        # moment the song change was detected) as the offset is the best
        # approximation available without server-side exact song-start
        # data -- see _on_lyrics_timer, which subtracts it back out.
        self._lyrics_song_start_position = self._engine.position
        self._fetch_lyrics_for_current()

    def _on_radio_recording_changed(self, is_recording: bool) -> None:
        """Update the transport bar's Record button, and refresh the
        Downloads tab so an active manual recording (source_type=
        "radio_recording" in the downloads table -- see RadioPanel.
        _on_record) actually shows up there instead of only becoming
        visible after the next unrelated Refresh click."""
        self._now_playing.set_recording(is_recording)
        self._downloads_panel._load_data()

    def _fetch_lyrics_for_current(self) -> None:
        """Fetch lyrics for the currently playing track, off the UI thread.

        LyricsService.fetch_lyrics() does blocking network I/O across up
        to 4 providers, each with its own timeout -- running it
        synchronously here (this is called from engine state-change and
        now-playing callbacks, both already marshalled onto the UI thread
        via wx.CallAfter) would freeze the whole app for several seconds
        every time a track or song changes.
        """
        import threading
        from radiomaster.services.lyrics_service import LyricsService
        artist = self._engine._current_artist or ""
        title = self._engine._current_title or ""
        if not title:
            return
        self._lyrics_panel.clear()

        def worker() -> None:
            result = LyricsService.fetch_lyrics(artist, title)
            if not result:
                return
            text = result.get("lyrics", "")
            synced = result.get("lrc", "")
            if synced:
                lines = LyricsService.parse_lrc(synced)
                if lines:
                    wx.CallAfter(
                        self._lyrics_panel.set_lrc_lines,
                        [(l["time"], l["text"]) for l in lines],
                    )
                    return
            if text:
                wx.CallAfter(self._lyrics_panel.set_content, text)

        threading.Thread(target=worker, daemon=True).start()

    def _on_engine_position(self, position: float, duration: float) -> None:
        """Handle playback position updates."""
        self._now_playing.set_time(position, duration)
        # duration > 0 (a finite podcast episode) shows elapsed/total/
        # remaining; duration == 0 (an unbounded radio stream) shows just
        # elapsed -- how long the current connection has been playing.
        self._status_bar.set_time_info(position, duration)
        # A real crossfade must begin before the outgoing track reports
        # natural completion. The media panel guards ownership/current URL,
        # so position updates from podcasts, radio, and video are harmless.
        self._media_panel.try_crossfade_advance(position, duration)

    def _on_engine_error(self, message: str) -> None:
        """Handle playback errors."""
        self._status_bar.set_status(f"Error: {message}")
        wx.MessageBox(message, "Playback Error", wx.OK | wx.ICON_ERROR)

    def _on_global_search(self, query: str, scope: str) -> None:
        """Handle global search across all content types."""
        from radiomaster.database.repository import StationRepository
        if scope == "all" or scope == "radio":
            repo = StationRepository(self._db)
            results = repo.search(query)
            if results:
                self._listbook.SetSelection(0)  # Switch to Radio tab
                self._radio_panel.display_search_results(results)
                self._status_bar.set_status(f"Found {len(results)} stations")
        if scope == "all" or scope == "media":
            from radiomaster.database.repository import MediaRepository
            repo = MediaRepository(self._db)
            results = repo.search(query)
            if results:
                self._listbook.SetSelection(3)  # Switch to Media tab

    def _show_equalizer(self) -> None:
        """Show the equalizer dialog."""
        dlg = EqualizerDialog(self)
        dlg.on_bands_changed(lambda bands: self._engine.apply_effect_params("equalizer", bands))
        if dlg.ShowModal() == wx.ID_OK:
            # Previously only ever turned the equalizer ON (never off) --
            # unchecking "enabled" and clicking OK silently left it exactly
            # as active as before, which would also have made the View
            # menu's new checkmark lie about the actual state.
            self._engine.toggle_effect("equalizer", dlg.is_enabled())
            if dlg.is_enabled():
                bands = dlg.get_band_values()
                self._engine.apply_effect_params("equalizer", bands)
            # Keep the Effects > Equalizer submenu's own On/Off checkbox in
            # sync too -- that's a separate mechanism (EffectsMenu.set_enabled)
            # this dialog doesn't otherwise go through.
            self._effects_menu.set_enabled("equalizer", dlg.is_enabled())
        dlg.Destroy()
        self._view_toggle_items["toggle_equalizer"].Check(
            self._engine._effects.get("equalizer", {}).get("enabled", False)
        )

    def _show_shortcut_editor(self) -> None:
        """Show the keyboard shortcut editor."""
        from radiomaster.ui.shortcut_editor import ShortcutEditor
        dlg = ShortcutEditor(self, self._config)
        if dlg.ShowModal() == wx.ID_OK:
            # Rebuild the live accelerator table so rebound shortcuts take
            # effect immediately instead of requiring a restart.
            self._setup_accelerators()
        dlg.Destroy()

    def _register_global_hotkeys(self) -> None:
        """Register assignments marked Global in the unified shortcut editor."""
        from radiomaster.ui.shortcut_editor import load_shortcuts, shortcut_to_global_spec

        shortcuts = load_shortcuts(self._config)
        hotkeys = {}
        for action, shortcut in shortcuts.items():
            if shortcut.get("global") and (spec := shortcut_to_global_spec(shortcut)):
                hotkeys[action] = [spec]
        handlers = getattr(self, "_shortcut_handlers", {})
        warnings = self._global_hotkey_manager.register_all(hotkeys, handlers)
        if warnings:
            log = logging.getLogger("radiomaster")
            for warning in warnings:
                log.warning(f"Global hotkey: {warning}")

    def _on_volume_step(self, delta: float) -> None:
        """Global-hotkey/context-menu Volume Up/Down -- steps the same
        Volume value/slider the transport bar's own volume slider uses,
        +/-0.05 on its 0.0..1.0 scale (matches the existing hotkey step)."""
        new_volume = max(0.0, min(1.0, self._engine._volume + delta))
        self._on_volume_change(new_volume)
        self._now_playing.set_volume(new_volume)

    def _on_pan_step(self, delta: float) -> None:
        """Global-hotkey Pan Left/Right -- steps the same Pan value/slider
        the transport bar's own pan slider uses, +/-0.1 on its -1.0..1.0
        scale (matches the reference project's keyboard manager, which
        uses +/-5 on an equivalent 0-100 scale)."""
        new_pan = max(-1.0, min(1.0, self._engine.pan + delta))
        self._on_pan_change(new_pan)
        self._now_playing.set_pan(new_pan)

    def _on_rate_step(self, delta: float) -> None:
        """Global-hotkey Playback Rate Up/Down -- steps the same Rate
        value/slider the transport bar's own rate slider uses, +/-0.1 on
        its 0.5x..3.0x scale (matches the reference project's keyboard
        manager exactly -- same scale, same step)."""
        new_rate = max(0.5, min(3.0, self._engine.rate + delta))
        self._on_rate_change(new_rate)
        self._now_playing.set_rate(new_rate)

    def _on_open_recording_folder(self) -> None:
        """Global-hotkey Open Recording Folder -- opens Settings >
        Recordings > Recording Location in Windows Explorer."""
        import os
        from radiomaster.utils.paths import get_recordings_dir
        path = get_recordings_dir()
        try:
            os.makedirs(path, exist_ok=True)
            os.startfile(path)
        except OSError as e:
            self._status_bar.set_status(f"Error: Could not open recordings folder ({e})")

    def _on_open_podcast_folder(self) -> None:
        """Global-hotkey Open Podcast Folder -- opens Settings > Podcasts
        > Podcast Download Location (its own dedicated folder, separate
        from the general Downloads location YouTube downloads use --
        see podcast_panel.py's _on_download for the per-feed subfolder
        layout underneath it)."""
        import os
        from radiomaster.utils.paths import get_podcasts_dir
        path = get_podcasts_dir()
        try:
            os.makedirs(path, exist_ok=True)
            os.startfile(path)
        except OSError as e:
            self._status_bar.set_status(f"Error: Could not open downloads folder ({e})")

    def _on_stop_action(self) -> None:
        """Same routing as the transport bar's Stop button (see
        _setup_engine_callbacks): Stop on the Radio tab only stops
        playback, never an in-progress recording of the same station."""
        if self._listbook.GetSelection() == 0:
            self._radio_panel._on_stop()
        else:
            self._engine.stop()

    def _on_open_url(self) -> None:
        """Open a URL dialog for streaming."""
        dlg = wx.TextEntryDialog(self, "Enter stream URL:", "Open URL")
        if dlg.ShowModal() == wx.ID_OK:
            url = dlg.GetValue().strip()
            if url:
                self._engine.play(url, title=url)
        dlg.Destroy()

    def _on_open_folder(self) -> None:
        """Load a folder's supported files into the Media Player playlist."""
        dlg = wx.DirDialog(self, "Select a folder")
        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            self._switch_tab(3)
            count = self._media_panel.load_folder(path)
            if count:
                self._status_bar.set_status(
                    f"Loaded {count} media {'file' if count == 1 else 'files'} from {path}"
                )
            else:
                self._status_bar.set_status(f"No supported media files found in {path}")
        dlg.Destroy()

    def _on_import_opml(self) -> None:
        """Import OPML file."""
        dlg = wx.FileDialog(self, "Import OPML", wildcard="OPML files (*.opml;*.xml)|*.opml;*.xml",
                            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        if dlg.ShowModal() == wx.ID_OK:
            from radiomaster.services.podcast_manager import PodcastManager
            import os
            with open(dlg.GetPath(), "r", encoding="utf-8") as f:
                content = f.read()
            feeds = PodcastManager.parse_opml(content)
            from radiomaster.database.repository import PodcastRepository
            repo = PodcastRepository(self._db)
            for feed in feeds:
                repo.add(feed["feed_url"], feed["title"], is_custom=True)
            self._status_bar.set_status(f"Imported {len(feeds)} feeds")
        dlg.Destroy()

    def _on_export_opml(self) -> None:
        """Export OPML file."""
        from radiomaster.database.repository import PodcastRepository
        from radiomaster.services.podcast_manager import PodcastManager
        repo = PodcastRepository(self._db)
        podcasts = repo.get_all()
        opml = PodcastManager.export_opml(podcasts)
        dlg = wx.FileDialog(self, "Export OPML", wildcard="OPML files (*.opml)|*.opml",
                            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
        if dlg.ShowModal() == wx.ID_OK:
            with open(dlg.GetPath(), "w", encoding="utf-8") as f:
                f.write(opml)
        dlg.Destroy()

    def _sync_view_menu_checks(self) -> None:
        """Sync the View menu's checkable items to actual state -- called
        once at startup (after _setup_ui(), since e.g. _lyrics_panel
        doesn't exist yet when the menu itself is built) and again after
        each toggle action, since a wx checkable menu item auto-flips its
        own check mark on click before the handler runs, which doesn't
        necessarily match what the action actually did (e.g. the Equalizer
        dialog can be cancelled without changing anything)."""
        self._view_toggle_items["toggle_equalizer"].Check(
            self._engine._effects.get("equalizer", {}).get("enabled", False)
        )
        self._view_toggle_items["toggle_lyrics"].Check(self._lyrics_panel.IsShown())
        self._view_toggle_items["fullscreen"].Check(self.IsFullScreen())

    def _toggle_lyrics(self) -> None:
        """Toggle the lyrics panel visibility."""
        self._lyrics_panel.Show(not self._lyrics_panel.IsShown())
        # Layout() on the content panel, not the Frame: the Frame's own
        # sizer just contains content_panel sized to fill the window, so
        # laying out the Frame doesn't re-flow content_panel's *own*
        # sizer (the one that actually holds lyrics_panel) on its own.
        self._content_panel.Layout()
        self._view_toggle_items["toggle_lyrics"].Check(self._lyrics_panel.IsShown())

    def _toggle_fullscreen(self) -> None:
        """Toggle fullscreen mode."""
        if self.IsFullScreen():
            self.ShowFullScreen(False)
        else:
            self.ShowFullScreen(True)
        self._view_toggle_items["fullscreen"].Check(self.IsFullScreen())

    def _apply_theme(self, theme_key: str) -> None:
        """Apply a theme."""
        self._theme_manager.apply_theme(theme_key)
        self._status_bar.set_status(f"Theme: {theme_key}")

    def _show_theme_editor(self) -> None:
        """Show the theme editor."""
        from radiomaster.ui.theme_editor import ThemeEditorDialog
        dlg = ThemeEditorDialog(self, self._theme_manager)
        dlg.ShowModal()
        dlg.Destroy()

    def _set_language(self, lang: str) -> None:
        """Set the UI language."""
        from radiomaster.i18n import I18nManager
        I18nManager().set_language(lang)
        self._status_bar.set_status(f"Language: {lang}")

    def _switch_tab(self, index: int) -> None:
        """Switch to a specific category by index and announce it in the status bar."""
        if 0 <= index < self._listbook.GetPageCount():
            self._listbook.SetSelection(index)
            page_text = self._listbook.GetPageText(index)
            self._status_bar.set_status(f"Switched to {page_text}")

    def _show_track_identifier(self) -> None:
        """Show the track identifier dialog with real fingerprinting."""
        from radiomaster.services.track_identifier import TrackIdentifier
        from radiomaster.database.repository import DownloadRepository

        # If something is playing, use it
        url = self._engine._current_url
        title = self._engine._current_title
        if not url:
            # Ask user to select a file
            dlg = wx.FileDialog(self, "Select audio file to identify",
                wildcard="Audio files|*.mp3;*.flac;*.wav;*.m4a;*.ogg",
                style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
            if dlg.ShowModal() != wx.ID_OK:
                dlg.Destroy()
                return
            url = dlg.GetPath()
            title = dlg.GetFilename()
            dlg.Destroy()

        identifier = TrackIdentifier()
        api_key = self._config.get("playback.acoustid_api_key", default="")
        if api_key:
            identifier.set_api_key(api_key)
        result = identifier.identify(url)
        if result:
            msg = (
                f"Title: {result.get('title', 'Unknown')}\n"
                f"Artist: {result.get('artist', 'Unknown')}\n"
                f"Album: {result.get('album', 'Unknown')}\n"
                f"Source: {result.get('source', 'Unknown')}"
            )
            wx.MessageBox(msg, "Track Identified", wx.OK | wx.ICON_INFORMATION)
        else:
            wx.MessageBox(
                "Could not identify this track.\n"
                "Ensure AcoustID and MusicBrainz are configured.",
                "Identification Failed", wx.OK | wx.ICON_WARNING)

    def _show_track_splitter(self) -> None:
        """Show the Track Splitter dialog (silence/chapter splitting + renaming)."""
        from radiomaster.ui.track_splitter_dialog import TrackSplitterDialog
        dlg = TrackSplitterDialog(self)
        dlg.ShowModal()
        dlg.Destroy()

    def _show_sleep_timer(self) -> None:
        """Show the sleep timer dialog."""
        from radiomaster.ui.sleep_timer_dialog import SleepTimerDialog

        def on_start(minutes: float, mode: str) -> None:
            self._sleep_timer.start(minutes, mode)
            self._sleep_timer.on_timeout(lambda: self._engine.stop())
            self._sleep_timer.on_mode_action(lambda: self._engine.stop())
            self._status_bar.set_status(f"Sleep timer: {int(minutes)} min ({mode})")

        def on_stop() -> None:
            self._sleep_timer.stop()
            self._status_bar.set_status("Sleep timer stopped")

        dlg = SleepTimerDialog(
            self,
            on_start=on_start,
            on_stop=on_stop,
            is_active=self._sleep_timer.is_active,
            remaining=self._sleep_timer.remaining,
        )
        dlg.ShowModal()
        dlg.Destroy()

    def _update_check_due(self) -> bool:
        """Whether enough time has passed since the last update check to run
        another one -- GitHub's unauthenticated API allows only 60
        requests/hour per source IP (shared across everyone behind the same
        NAT/office network), which a check on every single launch burns
        through fast. updates.check_frequency_days already existed as a
        config setting but nothing ever read it; this is what actually
        enforces it for the silent startup check. Manual Help > Check for
        Updates always runs regardless -- that's explicit user intent."""
        import time
        days = self._config.get("updates.check_frequency_days", default=7)
        last_check = self._config.get("updates.last_check_timestamp", default=0)
        return time.time() - last_check >= days * 86400

    def _ytdlp_update_due(self) -> bool:
        """Whether enough time has passed since the last background yt-dlp
        update check to run another one. Mirrors _update_check_due() so the
        startup check doesn't hit GitHub's API on every single launch."""
        import time
        days = self._config.get("updates.ytdlp_check_frequency_days", default=7)
        last_check = self._config.get("updates.ytdlp_last_check_timestamp", default=0)
        return time.time() - last_check >= days * 86400

    def _auto_update_ytdlp(self) -> None:
        """Background auto-update of the bundled yt-dlp.exe (the "YouTube
        library"), run once at startup if due. Checks for a newer release
        and, if one exists, downloads and replaces the bundled copy --
        all on a daemon thread so startup is never blocked. Fails
        silently (logged only) on any error, including a non-writable
        tools folder (e.g. installed under Program Files); the manual
        Help > Update YouTube Library is the fallback that surfaces real
        problems to the user."""
        import threading
        import time
        from radiomaster.services.youtube_dl import YouTubeService

        # Record the attempt timestamp up front so a failed/offline check
        # doesn't retry on every subsequent launch (same reasoning as
        # _check_updates).
        self._config.set("updates.ytdlp_last_check_timestamp", value=time.time())
        self._config.save()

        def worker():
            try:
                service = YouTubeService()
                available, _latest = service.check_for_update()
                if not available:
                    return
                ok, message = service.update()
                if ok:
                    logging.getLogger("radiomaster").info(
                        f"Background yt-dlp update succeeded: {message}")
                else:
                    logging.getLogger("radiomaster").warning(
                        f"Background yt-dlp update failed: {message}")
            except Exception:
                logging.getLogger("radiomaster").exception("Background yt-dlp update error")

        threading.Thread(target=worker, daemon=True).start()

    def _check_updates(self, silent: bool = False) -> None:
        """Check GitHub for a newer release. silent=True (startup auto-check)
        stays quiet on failure or "no update found" -- only a manual Help >
        Check for Updates reports either of those with a dialog."""
        import threading
        import time
        from radiomaster.services.update_checker import UpdateChecker, UpdateCheckError
        from radiomaster import __version__
        from radiomaster.utils.wx_safe import call_after_safe

        checker = UpdateChecker()

        # Recorded before the network call completes (not just on success)
        # so a rate-limited or otherwise failed attempt doesn't get retried
        # on every subsequent launch until check_frequency_days actually
        # elapses -- that retry-storm is exactly what causes the rate limit
        # in the first place.
        self._config.set("updates.last_check_timestamp", value=time.time())
        self._config.save()

        def worker():
            try:
                info = checker.check(__version__)
            except UpdateCheckError as exc:
                if silent:
                    logging.getLogger("radiomaster").info(f"Silent update check failed: {exc}")
                else:
                    call_after_safe(self, self._update_check_failed, str(exc))
                return
            call_after_safe(self, self._update_check_result, checker, info, silent)

        threading.Thread(target=worker, daemon=True).start()

    def _update_check_failed(self, message: str) -> None:
        wx.MessageBox(message, "Check for Updates", wx.OK | wx.ICON_ERROR, self)

    def _update_ytdlp(self) -> None:
        """Help > Update YouTube Library: download the latest yt-dlp.exe
        and replace the bundled copy in place.

        YouTube changes its extraction API frequently, and an outdated
        yt-dlp is the most common cause of "YouTube videos won't play"
        (the old binary gets HTTP 403 from googlevideo.com even on its
        own downloads). This lets the user refresh the library on demand
        without waiting for a full app release. Runs the download off the
        UI thread so the window doesn't freeze."""
        from radiomaster.services.youtube_dl import YouTubeService
        from radiomaster.utils.wx_safe import call_after_safe

        service = YouTubeService()
        current = service.get_version() or "unknown"

        if wx.MessageBox(
            f"Update the YouTube library (yt-dlp) to the latest version?\n\n"
            f"Current version: {current}\n\n"
            "This downloads the latest yt-dlp.exe from the official GitHub "
            "releases and replaces the bundled copy. YouTube changes its "
            "extraction API often, so keeping this up to date is the best "
            "way to keep YouTube playback working.",
            "Update YouTube Library", wx.YES_NO | wx.ICON_QUESTION, self,
        ) != wx.YES:
            return

        self._status_bar.set_status("Updating YouTube library...")

        def progress_cb(downloaded: int, total: int) -> None:
            if total:
                pct = int(downloaded * 100 / total)
                call_after_safe(self, self._status_bar.set_status,
                                f"Updating YouTube library... {pct}%")
            else:
                call_after_safe(self, self._status_bar.set_status,
                                f"Updating YouTube library... {downloaded // 1024} KB")

        def worker():
            ok, message = service.update(progress_cb=progress_cb)
            call_after_safe(self, self._update_ytdlp_result, ok, message)

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _update_ytdlp_result(self, ok: bool, message: str) -> None:
        self._status_bar.set_status("Ready")
        if ok:
            wx.MessageBox(
                f"The YouTube library was updated successfully.\n\n"
                f"New version: {message}",
                "Update YouTube Library", wx.OK | wx.ICON_INFORMATION, self,
            )
        else:
            wx.MessageBox(
                f"The YouTube library could not be updated.\n\n{message}",
                "Update YouTube Library", wx.OK | wx.ICON_ERROR, self,
            )

    def _update_check_result(self, checker, info, silent: bool) -> None:
        from radiomaster import __version__
        if info is None:
            if not silent:
                wx.MessageBox(
                    f"You're up to date -- RadioMaster+ {__version__} is the latest version.",
                    "Check for Updates", wx.OK | wx.ICON_INFORMATION, self)
            return
        if silent and self._config.get("updates.skip_version", default="") == info.version:
            return
        from radiomaster.ui.update_dialog import UpdateAvailableDialog
        dlg = UpdateAvailableDialog(self, checker, info, self._on_ready_to_install)
        result = dlg.ShowModal()
        if result == wx.ID_NO:
            self._config.set("updates.skip_version", value=info.version)
            self._config.save()
        dlg.Destroy()

    def _on_ready_to_install(self, installer_path: str) -> None:
        import subprocess
        try:
            subprocess.Popen([installer_path])
        except OSError as exc:
            wx.MessageBox(f"Could not launch the installer: {exc}", "Update", wx.OK | wx.ICON_ERROR, self)
            return
        # Must actually exit, not just self.Close() -- since v1.1.10, Close()
        # with "Close to system tray" enabled just hides the window instead
        # of quitting. If that setting is on, the running app's DLLs/files
        # stayed locked exactly while the installer just launched tries to
        # overwrite them -- the likely cause of "failed to load Python DLL"
        # after an in-app update. request_exit() is the only path that's
        # guaranteed to actually terminate the process, tray setting or not.
        self.request_exit()

    def _show_help_topics(self, title: str, topics: list[tuple[str, str]]) -> None:
        """Show one of the accessible topic-based Help documents."""
        from radiomaster.ui.help_dialog import HelpDialog
        dlg = HelpDialog(self, title=title, topics=topics)
        dlg.ShowModal()
        dlg.Destroy()

    def _show_user_manual(self) -> None:
        """Show the complete in-app user manual (F1)."""
        from radiomaster.ui.help_dialog import USER_MANUAL_TOPICS
        self._show_help_topics("RadioMaster+ User Manual", USER_MANUAL_TOPICS)

    def _show_documentation(self) -> None:
        """Compatibility alias used by the global Open Help action."""
        self._show_user_manual()

    def _show_quick_start(self) -> None:
        """Show the short task-oriented getting-started guide."""
        from radiomaster.ui.help_dialog import QUICK_START_TOPICS
        self._show_help_topics("RadioMaster+ Quick Start Guide", QUICK_START_TOPICS)

    def _show_release_notes(self) -> None:
        """Show release notes bundled with this installed version."""
        from radiomaster.ui.help_dialog import RELEASE_NOTES_TOPICS
        self._show_help_topics("RadioMaster+ Release Notes", RELEASE_NOTES_TOPICS)

    # Listbook page indices for the tabs with their own Previous/Next/
    # First/Last behavior (see AddPage order in _setup_ui) -- everything
    # else (Audiobooks/Media Player/YouTube/Scheduler) has no per-tab
    # playlist/history yet, so the transport bar falls back to seeking.
    _TAB_RADIO = 0
    _TAB_PODCASTS = 1
    _TAB_DOWNLOADS = 5

    def _next_track(self) -> None:
        """Radio: move forward in station history. Podcasts: next
        episode. Downloads: next item in History. Elsewhere: seek
        forward as a fallback."""
        sel = self._listbook.GetSelection()
        if sel == self._TAB_RADIO:
            self._status_bar.set_status("Next station")
            self._radio_panel.history_next()
            return
        if sel == self._TAB_PODCASTS:
            self._status_bar.set_status("Next episode")
            self._podcast_panel.episode_next()
            return
        if sel == self._TAB_DOWNLOADS:
            self._status_bar.set_status("Next download")
            self._downloads_panel.history_next()
            return
        self._status_bar.set_status("Next track")
        current_pos = self._engine.position
        self._engine.seek(current_pos + 10)

    def _prev_track(self) -> None:
        """Radio: move back in station history. Podcasts: previous
        episode. Downloads: previous item in History. Elsewhere: seek
        backward as a fallback."""
        sel = self._listbook.GetSelection()
        if sel == self._TAB_RADIO:
            self._status_bar.set_status("Previous station")
            self._radio_panel.history_previous()
            return
        if sel == self._TAB_PODCASTS:
            self._status_bar.set_status("Previous episode")
            self._podcast_panel.episode_previous()
            return
        if sel == self._TAB_DOWNLOADS:
            self._status_bar.set_status("Previous download")
            self._downloads_panel.history_previous()
            return
        self._status_bar.set_status("Previous track")
        current_pos = self._engine.position
        self._engine.seek(max(0, current_pos - 10))

    def _first_track(self) -> None:
        """Radio: jump to the first station in history. Podcasts: first
        episode. Downloads: first (most recent) item in History.
        Elsewhere: seek to the start."""
        sel = self._listbook.GetSelection()
        if sel == self._TAB_RADIO:
            self._status_bar.set_status("First station")
            self._radio_panel.history_first()
            return
        if sel == self._TAB_PODCASTS:
            self._status_bar.set_status("First episode")
            self._podcast_panel.episode_first()
            return
        if sel == self._TAB_DOWNLOADS:
            self._status_bar.set_status("First download")
            self._downloads_panel.history_first()
            return
        self._status_bar.set_status("First track")
        self._engine.seek(0)

    def _last_track(self) -> None:
        """Radio: jump to the most recent station in history. Podcasts:
        last episode. Downloads: last (oldest shown) item in History.
        Elsewhere: seek near the end."""
        sel = self._listbook.GetSelection()
        if sel == self._TAB_RADIO:
            self._status_bar.set_status("Last station")
            self._radio_panel.history_last()
            return
        if sel == self._TAB_PODCASTS:
            self._status_bar.set_status("Last episode")
            self._podcast_panel.episode_last()
            return
        if sel == self._TAB_DOWNLOADS:
            self._status_bar.set_status("Last download")
            self._downloads_panel.history_last()
            return
        self._status_bar.set_status("Last track")
        if self._engine.duration > 0:
            self._engine.seek(max(0, self._engine.duration - 30))

    def _fast_forward(self) -> None:
        """Fast forward by skipping ahead 30 seconds."""
        current_pos = self._engine.position
        self._engine.seek(current_pos + 30)
        self._status_bar.set_status("Fast forward")

    def _rewind(self) -> None:
        """Rewind by going back 30 seconds."""
        current_pos = self._engine.position
        self._engine.seek(max(0, current_pos - 30))
        self._status_bar.set_status("Rewind")

