"""Tab-order regression tests for MainWindow.

Every composite panel here (SearchBar, wx.Listbook, NowPlayingBar) is its
own wx.Panel, and wx does NOT automatically escape Tab from a nested panel
up to the next sibling -- confirmed empirically, including with
TAB_TRAVERSAL passed to the Frame's constructor. Without explicit
boundary handling, Tab wraps forever inside whichever panel has focus
instead of ever reaching the next one. This has regressed multiple times
(premature escapes hijacking in-panel moves, NavigateIn() silently
skipping over the Listbook entirely, a missing SearchBar boundary leaving
it impossible to ever reach the listbook at all) -- these tests drive the
same wx.Window.Navigate() calls wx's own keyboard handling makes for a
real Tab press, without needing a running MainLoop or OS-level input.
"""

import time
import wx
import pytest
from unittest.mock import MagicMock, patch
from radiomaster.app import RadioMasterApp
from radiomaster.services.station_api import Station


@pytest.fixture
def app_and_window():
    app = RadioMasterApp()
    win = app._main_window
    # First/Previous/Next/Last are correctly greyed out (and therefore
    # Tab-skipped) until there's station history to navigate -- exactly
    # what a fresh app start looks like. These tab-order tests care about
    # the *order*, not button-enabled-state (that's covered separately in
    # test_playback_engine.py's history tests), so give the transport bar
    # some history up front to put it in its normal, fully-focusable state.
    win._radio_panel._push_history(Station(uuid="a", name="A", url="http://a"))
    win._radio_panel._push_history(Station(uuid="b", name="B", url="http://b"))
    win._radio_panel._push_history(Station(uuid="c", name="C", url="http://c"))
    win._radio_panel._history_index = 1  # middle: both Previous and Next have somewhere to go
    win._update_transport_button_states()
    yield app, win
    win._lyrics_timer.Stop()
    win.Destroy()
    app.OnExit()


def _nav(win: wx.Window, forward: bool) -> wx.Window:
    f = win.FindFocus()
    f.Navigate(wx.NavigationKeyEvent.IsForward if forward else wx.NavigationKeyEvent.IsBackward)
    return win.FindFocus()


class TestTabOrder:
    def test_forward_chain_reaches_listbook_and_transport_bar(self, app_and_window) -> None:
        """search bar -> listbook tab list -> Radio page's own controls, in
        order, with nothing skipped -> transport bar. This exact chain has
        broken three different ways in the past (see module docstring)."""
        app, win = app_and_window
        win._search_bar.SetFocus()
        assert type(win.FindFocus()).__name__ == "SearchCtrl"

        assert type(_nav(win, True)).__name__ == "Choice"
        assert type(_nav(win, True)).__name__ == "Button"  # search bar's Go button

        # Escaping the search bar must land in the listbook's tab list --
        # not skip over it into the transport bar (NavigateIn() did this).
        listbook_entry = _nav(win, True)
        assert listbook_entry is win._listbook.GetListView()

        # Walking forward through the Radio page's own controls must visit
        # each one -- not jump straight to the transport bar (an
        # over-broad escape guard did this) and not loop forever inside
        # the page (an under-broad one did this).
        seen_classes = []
        focus = listbook_entry
        # 9, not 10 -- one fewer stop since the Radio tab's "Refresh
        # Database" button was removed (its equivalent now lives as
        # "Update Now" in Settings > Radio instead).
        for _ in range(9):
            focus = _nav(win, True)
            seen_classes.append(type(focus).__name__)
        assert "_VirtualStationList" in seen_classes, (
            f"station list was skipped over entirely: {seen_classes}"
        )
        assert seen_classes[-1] == "Button" and focus.GetLabel() == "|◀", (
            f"did not land on the transport bar's first control (First Track): {seen_classes}"
        )

    def test_backward_chain_returns_to_search_bar(self, app_and_window) -> None:
        """Shift+Tab from deep in the transport bar must walk back into the
        Radio page's content (not get stranded outside the listbook with
        no way back in -- the original, most literally reported bug:
        'you cannot get back to the list of stations') and, continuing
        further, eventually reach the search bar again."""
        app, win = app_and_window
        win._now_playing._btn_mute.SetFocus()

        seen_classes = []
        seen_pages = []
        for _ in range(30):
            focus = _nav(win, False)
            seen_classes.append(type(focus).__name__)
            # Landing inside the Radio page's own widget tree (not just on
            # the listbook's tab list, which wx reaches independently of
            # whether re-entering the page's content actually worked).
            seen_pages.append(_is_descendant_of(focus, win._radio_panel))

        assert any(seen_pages), (
            f"Shift+Tab off the transport bar never re-entered the Radio "
            f"page's own content, only escaped past it: {seen_classes}"
        )
        assert "SearchCtrl" in seen_classes, (
            f"never made it all the way back to the search bar: {seen_classes}"
        )


class TestStationHistory:
    """RadioPanel's station history (Previous/Next/First/Last on the
    transport bar) and the transport-bar greying that goes with it."""

    def _reset(self, win) -> None:
        # The fixture pre-populates history for the tab-order tests above;
        # start these from a clean slate instead.
        win._radio_panel._history = []
        win._radio_panel._history_index = -1
        win._update_transport_button_states()
        # history_previous()/first()/last() call through to _play_station(),
        # which would otherwise spawn real background threads trying to
        # open fake "http://a"-style URLs -- these tests are only checking
        # the history list/index bookkeeping and button states, not real
        # playback, so stub out the actual engine/API calls.
        win._radio_panel.engine.play = MagicMock()
        win._radio_panel.station_api.click = MagicMock()

    def test_fresh_station_appends_and_becomes_current(self, app_and_window) -> None:
        app, win = app_and_window
        self._reset(win)
        panel = win._radio_panel

        panel._push_history(Station(uuid="a", name="A", url="http://a"))
        panel._push_history(Station(uuid="b", name="B", url="http://b"))

        assert [s.uuid for s in panel._history] == ["a", "b"]
        assert panel._history_index == 1
        assert panel.history_has_previous() is True
        assert panel.history_has_next() is False

    def test_reactivating_current_station_is_a_noop(self, app_and_window) -> None:
        """Double-clicking the station that's already playing shouldn't
        add a duplicate history entry."""
        app, win = app_and_window
        self._reset(win)
        panel = win._radio_panel

        panel._push_history(Station(uuid="a", name="A", url="http://a"))
        panel._push_history(Station(uuid="a", name="A", url="http://a"))

        assert len(panel._history) == 1

    def test_picking_fresh_station_after_going_back_truncates_forward_history(
        self, app_and_window
    ) -> None:
        """Browser-style: Previous, Previous, then picking a new station
        should discard the stations that were ahead of where you went
        back to, not just append after them."""
        app, win = app_and_window
        self._reset(win)
        panel = win._radio_panel

        panel._push_history(Station(uuid="a", name="A", url="http://a"))
        panel._push_history(Station(uuid="b", name="B", url="http://b"))
        panel._push_history(Station(uuid="c", name="C", url="http://c"))
        panel.history_previous()
        panel.history_previous()
        assert panel._history_index == 0

        panel._push_history(Station(uuid="d", name="D", url="http://d"))

        assert [s.uuid for s in panel._history] == ["a", "d"]
        assert panel._history_index == 1

    def test_first_last_jump_to_the_ends(self, app_and_window) -> None:
        app, win = app_and_window
        self._reset(win)
        panel = win._radio_panel
        for uuid in ("a", "b", "c", "d"):
            panel._push_history(Station(uuid=uuid, name=uuid.upper(), url=f"http://{uuid}"))
        assert panel._history_index == 3

        panel.history_first()
        assert panel._history_index == 0
        assert panel.history_has_previous() is False
        assert panel.history_has_next() is True

        panel.history_last()
        assert panel._history_index == 3
        assert panel.history_has_previous() is True
        assert panel.history_has_next() is False

    def test_previous_next_are_noop_at_the_ends(self, app_and_window) -> None:
        app, win = app_and_window
        self._reset(win)
        panel = win._radio_panel
        panel._push_history(Station(uuid="a", name="A", url="http://a"))

        panel.history_previous()  # already at (only) entry -- no previous
        assert panel._history_index == 0
        panel.history_next()  # already at (only) entry -- no next
        assert panel._history_index == 0

    def test_transport_buttons_grey_out_with_no_history(self, app_and_window) -> None:
        app, win = app_and_window
        self._reset(win)
        assert win._now_playing._btn_first.IsEnabled() is False
        assert win._now_playing._btn_prev.IsEnabled() is False
        assert win._now_playing._btn_next.IsEnabled() is False
        assert win._now_playing._btn_last.IsEnabled() is False

    def test_transport_buttons_enable_once_there_is_somewhere_to_go(self, app_and_window) -> None:
        app, win = app_and_window
        self._reset(win)
        panel = win._radio_panel
        panel._push_history(Station(uuid="a", name="A", url="http://a"))
        panel._push_history(Station(uuid="b", name="B", url="http://b"))
        panel._push_history(Station(uuid="c", name="C", url="http://c"))
        panel.history_previous()  # now on "b", the true middle -- both directions available
        win._update_transport_button_states()

        assert win._now_playing._btn_first.IsEnabled() is True
        assert win._now_playing._btn_prev.IsEnabled() is True
        assert win._now_playing._btn_next.IsEnabled() is True
        assert win._now_playing._btn_last.IsEnabled() is True

    def test_seek_controls_grey_out_for_unseekable_radio_stream(self, app_and_window) -> None:
        """Radio streams always have duration == 0 (no fixed timeline) --
        Fast Forward/Rewind/the position slider must be disabled, not just
        silently do nothing when clicked."""
        app, win = app_and_window
        assert win._engine.duration == 0
        win._update_transport_button_states()

        assert win._now_playing._btn_ffwd.IsEnabled() is False
        assert win._now_playing._btn_rewind.IsEnabled() is False
        assert win._now_playing._position_slider.IsEnabled() is False

    def test_stop_greyed_out_when_nothing_is_playing(self, app_and_window) -> None:
        """Nothing to stop before anything's ever been played -- Stop had
        no enabled/disabled logic at all before this, so it was always
        clickable even with the engine in STATE_STOPPED."""
        app, win = app_and_window
        assert win._engine.state == "stopped"
        win._update_transport_button_states()
        assert win._now_playing._btn_stop.IsEnabled() is False

    def test_stop_enables_once_something_is_playing(self, app_and_window) -> None:
        app, win = app_and_window
        for state in ("playing", "paused", "buffering"):
            win._now_playing.set_stoppable(state != "stopped")
            assert win._now_playing._btn_stop.IsEnabled() is True, state
        win._now_playing.set_stoppable("stopped" != "stopped")
        assert win._now_playing._btn_stop.IsEnabled() is False


def _is_descendant_of(window: wx.Window, ancestor: wx.Window) -> bool:
    w = window
    while w is not None:
        if w is ancestor:
            return True
        w = w.GetParent()
    return False


class TestLyricsFetch:
    """engine._current_title/_current_artist previously only ever held
    the station's own name and an empty artist (set once at play() time),
    which no lyrics provider could match against anything -- lyrics never
    showed up for radio. _on_radio_now_playing_changed (wired to
    RadioPanel.on_now_playing_changed, fired from parsed ICY metadata) is
    what actually gives the engine the real song."""

    def test_now_playing_change_updates_engine_track_info(self, app_and_window) -> None:
        app, win = app_and_window
        win._engine._current_title = "My Station Name"
        win._engine._current_artist = ""

        with patch("radiomaster.services.lyrics_service.LyricsService.fetch_lyrics", return_value=None):
            win._on_radio_now_playing_changed("Real Artist", "Real Song")

        assert win._engine._current_artist == "Real Artist"
        assert win._engine._current_title == "Real Song"

    def test_now_playing_change_captures_song_start_offset(self, app_and_window) -> None:
        """A radio station's play() only ever runs once, when it's tuned
        in -- engine.position keeps counting from then, not from when a
        song heard partway through the stream actually started. Without
        capturing an offset at the moment the song is detected, LRC
        highlighting would compare against "seconds since tuned in"
        instead of "seconds into this song" and jump straight to the
        last line."""
        app, win = app_and_window
        win._engine._live._position = 1200.0  # 20 minutes into the station
        win._lyrics_song_start_position = 0.0

        with patch("radiomaster.services.lyrics_service.LyricsService.fetch_lyrics", return_value=None):
            win._on_radio_now_playing_changed("Real Artist", "Real Song")

        assert win._lyrics_song_start_position == 1200.0

    def test_lyrics_timer_highlights_relative_to_song_start(self, app_and_window) -> None:
        app, win = app_and_window
        win._engine._live._state = "playing"
        win._lyrics_song_start_position = 1200.0
        win._lyrics_panel._lrc_lines = [(0.0, "line zero"), (5.0, "line five"), (10.0, "line ten")]
        win._lyrics_panel.highlight_sentence = MagicMock()

        # 3s into the song -> raw engine position is 1203, well past every
        # LRC timestamp; only the offset-adjusted value (3.0) picks line 0.
        win._engine._live._position = 1203.0
        win._on_lyrics_timer(None)
        win._lyrics_panel.highlight_sentence.assert_called_with(0)

        win._engine._live._position = 1207.0
        win._on_lyrics_timer(None)
        win._lyrics_panel.highlight_sentence.assert_called_with(1)

    def test_new_track_resets_song_start_offset_to_zero(self, app_and_window) -> None:
        """Local files/podcasts/etc: play() itself is the song starting,
        so engine.position is already correct with no offset -- a leftover
        nonzero offset from a previous radio session must not leak in."""
        app, win = app_and_window
        win._lyrics_song_start_position = 1200.0
        win._engine._current_title = "Some Local Track"
        with patch("radiomaster.services.lyrics_service.LyricsService.fetch_lyrics", return_value=None):
            win._on_engine_state("playing")
        assert win._lyrics_song_start_position == 0.0

    def test_fetch_lyrics_uses_lrc_key_not_the_old_wrong_keys(self, app_and_window) -> None:
        """Regression test for the exact bug that silently broke synced
        lyrics: LyricsService.fetch_lyrics() returns synced lyrics under
        the "lrc" key, but the caller used to read "lyrics_synced"/
        "lrc_data" instead, which never existed in the actual result."""
        app, win = app_and_window
        win._engine._current_artist = "Real Artist"
        win._engine._current_title = "Real Song"

        fake_result = {"lyrics": "line one\nline two", "lrc": "[00:01.00]line one\n[00:05.00]line two"}
        with patch("radiomaster.services.lyrics_service.LyricsService.fetch_lyrics", return_value=fake_result):
            win._fetch_lyrics_for_current()
            deadline = time.time() + 3
            while time.time() < deadline and not getattr(win._lyrics_panel, "_lrc_lines", None):
                wx.Yield()
                time.sleep(0.05)

        assert win._lyrics_panel._lrc_lines == [(1.0, "line one"), (5.0, "line two")]

    def test_fetch_lyrics_skipped_when_no_title(self, app_and_window) -> None:
        app, win = app_and_window
        win._engine._current_title = ""
        with patch("radiomaster.services.lyrics_service.LyricsService.fetch_lyrics") as mock_fetch:
            win._fetch_lyrics_for_current()
            wx.Yield()
        mock_fetch.assert_not_called()


class TestRecording:
    """The Record button's ffmpeg process genuinely started, but nothing
    ever told NowPlayingBar's "Record Off"/"Recording On" button -- with
    no other feedback, that was indistinguishable from the button doing
    nothing at all, especially for a screen-reader user relying on the
    button's own accessible name to know whether it worked."""

    def test_record_toggles_transport_bar_button_state(self, app_and_window) -> None:
        app, win = app_and_window
        panel = win._radio_panel
        panel._selected_station = Station(uuid="a", name="A", url="http://a")

        assert win._now_playing._btn_record.GetLabelText() == "● Record Off"

        with patch("subprocess.Popen") as mock_popen, \
                patch("radiomaster.services.stream_prober.probe_stream_format", return_value=None):
            mock_popen.return_value = MagicMock()
            panel._on_record()
        assert win._now_playing._btn_record.GetLabelText() == "● Recording On"

        panel._on_record()  # toggle off
        assert win._now_playing._btn_record.GetLabelText() == "● Record Off"

    def test_stop_does_not_halt_an_active_recording(self, app_and_window) -> None:
        """Stop only stops playback -- a recording is a separate ffmpeg
        connection to the stream, and by design is only ever stopped by
        toggling Record off again, not by Stop."""
        app, win = app_and_window
        panel = win._radio_panel
        panel._selected_station = Station(uuid="a", name="A", url="http://a")
        panel.engine.stop = MagicMock()

        with patch("subprocess.Popen") as mock_popen, \
                patch("radiomaster.services.stream_prober.probe_stream_format", return_value=None):
            mock_popen.return_value = MagicMock()
            panel._on_record()
        assert len(panel._recordings) == 1

        panel._on_stop()
        assert len(panel._recordings) == 1
        assert win._now_playing._btn_record.GetLabelText() == "● Recording On"

        panel._on_record()  # toggle off explicitly
        assert len(panel._recordings) == 0

    def test_active_recording_shows_in_downloads_panel(self, app_and_window) -> None:
        """A manual recording's ffmpeg process genuinely started, but the
        Downloads tab is where the user actually looks to confirm it's
        running -- without a "downloads" row, it never showed up there
        at all even while genuinely recording.

        Uses a distinctive station name and checks for that specific row
        rather than assuming the list is otherwise empty -- app_and_window
        uses the app's real (not test-isolated) SQLite database, which
        can carry rows over between runs.
        """
        app, win = app_and_window
        marker = f"DownloadsPanelTest-{id(self)}"
        panel = win._radio_panel
        panel._selected_station = Station(uuid="a", name=marker, url="http://a")

        def _row(list_ctrl, title):
            for i in range(list_ctrl.GetItemCount()):
                if list_ctrl.GetItemText(i, 0) == title:
                    return list_ctrl.GetItemText(i, 2)
            return None

        with patch("subprocess.Popen") as mock_popen, \
                patch("radiomaster.services.stream_prober.probe_stream_format", return_value=None):
            mock_popen.return_value = MagicMock()
            panel._on_record()

        expected_title = f"Recording: {marker}"
        assert _row(win._downloads_panel._active_list, expected_title) == "downloading"

        panel._on_record()  # stop
        assert _row(win._downloads_panel._active_list, expected_title) is None
        assert _row(win._downloads_panel._history_list, expected_title) == "completed"

    def test_multiple_stations_can_record_independently(self, app_and_window) -> None:
        """The README (and the existing Recording Scheduler) promise
        multiple simultaneous recordings -- the original single-value
        self._record_process couldn't represent more than one at a time,
        so starting a second recording silently had no way to track the
        first one at all."""
        app, win = app_and_window
        panel = win._radio_panel
        station_a = Station(uuid="rec-a", name="Rec A", url="http://a")
        station_b = Station(uuid="rec-b", name="Rec B", url="http://b")

        with patch("subprocess.Popen") as mock_popen, \
                patch("radiomaster.services.stream_prober.probe_stream_format", return_value=None):
            mock_popen.side_effect = lambda *a, **k: MagicMock()

            panel._selected_station = station_a
            panel._on_record()
            assert panel.is_station_recording(station_a) is True
            assert panel.is_station_recording(station_b) is False

            panel._selected_station = station_b
            panel._on_record()
            assert panel.is_station_recording(station_a) is True, (
                "starting B's recording must not stop A's"
            )
            assert panel.is_station_recording(station_b) is True
            assert len(panel._recordings) == 2

            # Stopping B (currently selected) must leave A running.
            panel._on_record()
            assert panel.is_station_recording(station_a) is True
            assert panel.is_station_recording(station_b) is False
            assert len(panel._recordings) == 1

    def test_record_button_reflects_the_currently_selected_station(self, app_and_window) -> None:
        """With multiple stations potentially recording at once, the
        button's state must track whichever station is now selected, not
        just whatever the last Record click happened to affect."""
        app, win = app_and_window
        panel = win._radio_panel
        station_a = Station(uuid="rec-a", name="Rec A", url="http://a")
        station_b = Station(uuid="rec-b", name="Rec B", url="http://b")

        with patch("subprocess.Popen") as mock_popen, \
                patch("radiomaster.services.stream_prober.probe_stream_format", return_value=None):
            mock_popen.side_effect = lambda *a, **k: MagicMock()
            panel._selected_station = station_a
            panel._on_record()  # A is now recording

        panel.tree.get_selected_station = lambda: station_b
        panel._on_tree_sel_changed()
        assert win._now_playing._btn_record.GetLabelText() == "● Record Off"

        panel.tree.get_selected_station = lambda: station_a
        panel._on_tree_sel_changed()
        assert win._now_playing._btn_record.GetLabelText() == "● Recording On"

    def test_downloads_panel_stops_a_specific_recording(self, app_and_window) -> None:
        """The Downloads tab's "Stop Recording" button lets any active
        recording be stopped directly from there, without needing to
        first re-select that exact station back in the Radio tab."""
        app, win = app_and_window
        panel = win._radio_panel
        downloads = win._downloads_panel
        station_a = Station(uuid="rec-a", name="Rec A", url="http://a")
        station_b = Station(uuid="rec-b", name="Rec B", url="http://b")

        with patch("subprocess.Popen") as mock_popen, \
                patch("radiomaster.services.stream_prober.probe_stream_format", return_value=None):
            mock_popen.side_effect = lambda *a, **k: MagicMock()
            panel._selected_station = station_a
            panel._on_record()
            panel._selected_station = station_b
            panel._on_record()

        assert len(panel._recordings) == 2
        download_id = next(iter(panel._recordings))

        assert panel.stop_recording_by_download_id(download_id) is True
        assert len(panel._recordings) == 1
        assert download_id not in panel._recordings

        # A download_id that isn't (or is no longer) active reports False
        # instead of raising -- e.g. the Downloads panel's own guard
        # against a stale/already-stopped selection.
        assert panel.stop_recording_by_download_id(download_id) is False
