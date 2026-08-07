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

import wx
import pytest
from unittest.mock import MagicMock
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
        for _ in range(10):
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
