"""Accessible station browser: Category -> Groups -> Stations using virtual list controls."""

from __future__ import annotations

import time
from typing import Callable, Optional

import wx

from radiomaster.services.station_api import Station
from radiomaster.services.station_db import StationDB
from radiomaster.utils.accessibility import set_accessible_name

_TYPEAHEAD_TIMEOUT = 1.0  # seconds before the search buffer resets


class _TypeAheadMixin:
    """Type-to-jump for LC_VIRTUAL wx.ListCtrl.

    Windows' native find-as-you-type for a ListView relies on the control
    owning its item text; a virtual/owner-data list (LC_VIRTUAL, used here so
    the group/station lists don't need thousands of real wx list items) never
    gets that text, so typing letters normally does nothing. This reimplements
    it manually: accumulate typed characters into a buffer (reset after a
    pause) and jump to the next item whose text starts with that buffer.
    """

    def _init_typeahead(self) -> None:
        self._typeahead_buffer = ""
        self._typeahead_last_time = 0.0
        self.Bind(wx.EVT_CHAR, self._on_typeahead_char)

    def _typeahead_item_text(self, index: int) -> str:
        raise NotImplementedError

    def _typeahead_count(self) -> int:
        raise NotImplementedError

    def _on_typeahead_char(self, event: wx.KeyEvent) -> None:
        if event.ControlDown() or event.AltDown() or event.MetaDown():
            event.Skip()
            return
        uc = event.GetUnicodeKey()
        if uc == wx.WXK_NONE:
            event.Skip()
            return
        char = chr(uc)
        if not (char.isalnum() or char in " &-"):
            event.Skip()
            return
        char = char.lower()

        count = self._typeahead_count()
        if count == 0:
            return

        now = time.time()
        if now - self._typeahead_last_time > _TYPEAHEAD_TIMEOUT:
            self._typeahead_buffer = ""
        self._typeahead_last_time = now
        self._typeahead_buffer += char

        current = self.GetFirstSelected()

        def find(query: str) -> int:
            start = (current + 1) if current >= 0 else 0
            for offset in range(count):
                idx = (start + offset) % count
                if self._typeahead_item_text(idx).lower().startswith(query):
                    return idx
            return -1

        idx = find(self._typeahead_buffer)
        if idx < 0 and len(self._typeahead_buffer) > 1:
            # No match for the accumulated buffer (e.g. repeated presses of
            # the same letter to cycle matches) -- restart with just this key.
            self._typeahead_buffer = char
            idx = find(self._typeahead_buffer)

        if idx >= 0:
            self.Select(idx)
            self.Focus(idx)
            self.EnsureVisible(idx)
            evt = wx.ListEvent(wx.EVT_LIST_ITEM_SELECTED.typeId, self.GetId())
            evt.SetIndex(idx)
            evt.SetEventObject(self)
            self.GetEventHandler().ProcessEvent(evt)

SECTION_ALPHABET = "alphabet"
SECTION_GENRE = "genre"
SECTION_COUNTRY = "country"
SECTION_LANGUAGE = "language"
SECTION_NETWORK = "network"
SECTION_CUSTOM = "custom"
SECTION_FAVORITES = "favorites"
SECTION_SEARCH = "search"
SECTION_SOURCES = "sources"

SECTION_CHOICES = [
    ("Alphabetical", SECTION_ALPHABET, "Letter", "Letters:"),
    ("By Genre", SECTION_GENRE, "Genre", "Genres:"),
    ("By Country", SECTION_COUNTRY, "Country", "Countries:"),
    ("By Language", SECTION_LANGUAGE, "Language", "Languages:"),
    ("By Network", SECTION_NETWORK, "Network", "Networks:"),
    ("Sources", SECTION_SOURCES, "Source", "Sources:"),
    ("Custom Stations", SECTION_CUSTOM, "Station", "Custom Stations:"),
    ("Favorites", SECTION_FAVORITES, "Station", "Favorites:"),
    ("Search Results", SECTION_SEARCH, "Station", "Search Results:"),
]

ALL_LABELS = {
    SECTION_ALPHABET: "All Stations",
    SECTION_GENRE: "All Genres",
    SECTION_COUNTRY: "All Countries",
    SECTION_LANGUAGE: "All Languages",
    SECTION_NETWORK: "All Networks",
}


class _VirtualGroupList(_TypeAheadMixin, wx.ListCtrl):
    def __init__(self, parent):
        super().__init__(parent, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_VIRTUAL)
        self.groups: list[tuple[str, int]] = []
        self._init_typeahead()

    def OnGetItemText(self, item, column):
        if 0 <= item < len(self.groups):
            name, count = self.groups[item]
            return name if column == 0 else str(count)
        return ""

    def set_groups(self, groups: list[tuple[str, int]]) -> None:
        self.groups = groups
        self.SetItemCount(len(groups))
        if groups:
            self.RefreshItems(0, len(groups) - 1)

    def _typeahead_item_text(self, index: int) -> str:
        return self.groups[index][0]

    def _typeahead_count(self) -> int:
        return len(self.groups)


class _VirtualStationList(_TypeAheadMixin, wx.ListCtrl):
    def __init__(self, parent):
        super().__init__(parent, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_VIRTUAL)
        self.stations: list[Station] = []
        # Multi-source rows (SourceNode list) or a single failure
        # sentence (str) -- rendered instead of stations when the tree
        # is in the Sources section. A virtual list can only serve
        # OnGetItemText, so both modes flow through _rows below.
        self.source_rows: list = []
        self._init_typeahead()

    def OnGetItemText(self, item, column):
        if self.source_rows:
            row = self.source_rows[item]
            if isinstance(row, str):
                return row if column == 0 else ""
            if column == 0:
                return row.label
            return row.note or ""
        if not (0 <= item < len(self.stations)):
            return ""
        station = self.stations[item]
        if column == 0:
            return station.name
        if column == 1:
            return station.country
        return str(station.bitrate) if station.bitrate else ""

    def set_stations(self, stations: list[Station]) -> None:
        self.source_rows = []
        self.stations = stations
        self.SetItemCount(len(stations))
        if stations:
            self.RefreshItems(0, len(stations) - 1)

    def set_source_rows(self, rows: list) -> None:
        """Render SourceNodes (or one failure sentence) in place of
        stations. The list is virtual, so rows are served through
        OnGetItemText rather than inserted as real items."""
        self.stations = []
        self.source_rows = rows
        self.SetItemCount(len(rows))
        if rows:
            self.RefreshItems(0, len(rows) - 1)

    def _typeahead_item_text(self, index: int) -> str:
        if self.source_rows:
            row = self.source_rows[index]
            return row if isinstance(row, str) else row.label
        return self.stations[index].name

    def _typeahead_count(self) -> int:
        return len(self.source_rows) if self.source_rows else len(self.stations)


class StationTree(wx.Panel):
    """Two-pane station browser: Category (Choice) -> Groups (ListCtrl) -> Stations (ListCtrl)."""

    def __init__(self, parent, db: StationDB):
        super().__init__(parent)
        self.db = db
        self.on_station_activated: Optional[Callable[[Station], None]] = None
        self.on_selection_changed: Optional[Callable[[], None]] = None
        # Multi-source catalog (services/sources/): the Sources section's
        # group list shows enabled sources; selecting one lazily browses
        # it on a worker thread (radio_panel drives the thread part --
        # this class only renders what it is handed, keeping wx calls on
        # the UI thread).
        self._source_nodes: dict[str, list] = {}
        self._source_failed: set[str] = set()
        self._source_selected: Optional[str] = None
        self._source_ids: list[str] = []
        self._source_labels: list[str] = []
        self._current_source_rows: list = []
        self.on_source_selected: Optional[Callable[[str], None]] = None
        self.on_source_node_activated: Optional[Callable[[object], None]] = None
        # Fired when the user switches to the Sources section before any
        # source list has been handed over -- the panel responds by
        # calling show_sources() with the enabled set.
        self.on_sources_needed: Optional[Callable[[], None]] = None

        self._section_groups: dict[str, list[tuple[str, int]]] = {}
        self._current_section: str = SECTION_ALPHABET
        self._current_groups: list[tuple[str, int]] = []
        self._current_stations: list[Station] = []
        self._custom_stations: list[Station] = []
        self._favorite_stations: list[Station] = []
        self._search_stations: list[Station] = []
        self._show_duplicates: bool = True

        self.section_choice = wx.Choice(self, choices=[label for label, *_ in SECTION_CHOICES])
        self.section_choice.SetSelection(0)
        set_accessible_name(self.section_choice, "Station Category")

        self.group_label = wx.StaticText(self, label="Letters:")
        self.group_list = _VirtualGroupList(self)
        self.group_list.InsertColumn(0, "Letter", width=220)
        self.group_list.InsertColumn(1, "Stations", width=80)

        stations_label = wx.StaticText(self, label="Stations:")
        self.station_list = _VirtualStationList(self)
        self.station_list.InsertColumn(0, "Station", width=240)
        self.station_list.InsertColumn(1, "Country", width=140)
        self.station_list.InsertColumn(2, "Bitrate", width=80)

        left = wx.BoxSizer(wx.VERTICAL)
        left.Add(self.group_label, 0, wx.BOTTOM, 2)
        left.Add(self.group_list, 1, wx.EXPAND)

        right = wx.BoxSizer(wx.VERTICAL)
        right.Add(stations_label, 0, wx.BOTTOM, 2)
        right.Add(self.station_list, 1, wx.EXPAND)

        body = wx.BoxSizer(wx.HORIZONTAL)
        body.Add(left, 1, wx.EXPAND | wx.RIGHT, 4)
        body.Add(right, 1, wx.EXPAND)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(self.section_choice, 0, wx.EXPAND | wx.BOTTOM, 4)
        outer.Add(body, 1, wx.EXPAND)
        self.SetSizer(outer)

        self.section_choice.Bind(wx.EVT_CHOICE, self._on_section_changed)
        self.group_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_group_selected)
        self.station_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_station_selected)
        self.station_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_station_activated_event)

        # Column widths above are fixed pixel values with no resize
        # handling, so a maximized/wide window left them exactly as narrow
        # as at the default size instead of using the extra room -- long
        # station/group names truncated the same amount regardless of how
        # much space was actually available. Grow the leading (name)
        # column to absorb whatever's left after the others' fixed widths.
        self.group_list.Bind(wx.EVT_SIZE, self._on_group_list_resize)
        self.station_list.Bind(wx.EVT_SIZE, self._on_station_list_resize)

    def _on_group_list_resize(self, event: wx.SizeEvent) -> None:
        event.Skip()
        available = self.group_list.GetClientSize().width
        fixed = 80  # "Stations" column
        self.group_list.SetColumnWidth(0, max(220, available - fixed))

    def _on_station_list_resize(self, event: wx.SizeEvent) -> None:
        event.Skip()
        available = self.station_list.GetClientSize().width
        fixed = 140 + 80  # "Country" + "Bitrate" columns
        self.station_list.SetColumnWidth(0, max(240, available - fixed))

    def load_sections(self) -> None:
        total = self.db.station_count()
        self._section_groups = {
            SECTION_ALPHABET: [(ALL_LABELS[SECTION_ALPHABET], total)] + self.db.alphabet_groups(),
            SECTION_GENRE: [(ALL_LABELS[SECTION_GENRE], total)] + self.db.genre_groups(),
            SECTION_COUNTRY: [(ALL_LABELS[SECTION_COUNTRY], total)] + self.db.country_groups(),
            SECTION_LANGUAGE: [(ALL_LABELS[SECTION_LANGUAGE], total)] + self.db.language_groups(),
            SECTION_NETWORK: [(ALL_LABELS[SECTION_NETWORK], total)] + self.db.network_groups(),
        }
        self.section_choice.SetSelection(0)
        self._show_section(SECTION_ALPHABET)

    def add_custom_section(self, stations: list[Station]) -> None:
        self._custom_stations = sorted(stations, key=lambda s: s.name.lower())
        if self._current_section == SECTION_CUSTOM:
            self._show_flat_list(self._custom_stations)

    def show_custom_stations(self) -> None:
        idx = [key for _, key, *_ in SECTION_CHOICES].index(SECTION_CUSTOM)
        self.section_choice.SetSelection(idx)
        self._current_section = SECTION_CUSTOM
        self._update_group_label(SECTION_CUSTOM)
        self._show_flat_list(self._custom_stations)

    def set_favorite_stations(self, stations: list[Station]) -> None:
        """Refreshes the Favorites section's contents -- called at
        startup and after every Add/Remove Favorite from the station
        list's context menu, so the section reflects the change
        immediately if it's the one currently on screen."""
        self._favorite_stations = sorted(stations, key=lambda s: s.name.lower())
        if self._current_section == SECTION_FAVORITES:
            self._show_flat_list(self._favorite_stations)

    def show_favorites(self) -> None:
        idx = [key for _, key, *_ in SECTION_CHOICES].index(SECTION_FAVORITES)
        self.section_choice.SetSelection(idx)
        self._current_section = SECTION_FAVORITES
        self._update_group_label(SECTION_FAVORITES)
        self._show_flat_list(self._favorite_stations)

    def show_country(self, country: str) -> bool:
        """Switch to the Country section and select *country*'s group, if
        it exists in the loaded catalog. Returns False (no-op) otherwise."""
        idx = [key for _, key, *_ in SECTION_CHOICES].index(SECTION_COUNTRY)
        self.section_choice.SetSelection(idx)
        self._current_section = SECTION_COUNTRY
        self._update_group_label(SECTION_COUNTRY)
        groups = self._section_groups.get(SECTION_COUNTRY, [])
        self._current_groups = groups
        self.group_list.set_groups(groups)
        for i, (name, _count) in enumerate(groups):
            if name.lower() == country.lower():
                self._select_group_index(i)
                return True
        self._select_group_index(0)
        return False

    def set_search_results(self, stations: list[Station]) -> None:
        self._search_stations = sorted(stations, key=lambda s: s.name.lower())
        idx = [key for _, key, *_ in SECTION_CHOICES].index(SECTION_SEARCH)
        self.section_choice.SetSelection(idx)
        self._current_section = SECTION_SEARCH
        self._update_group_label(SECTION_SEARCH)
        self._show_flat_list(self._search_stations)

    def append_search_results(self, stations: list[Station]) -> None:
        """Append late-arriving search results (source fanout) to the
        Search Results section without moving the cursor: the user's
        current selection index is captured before the merge and
        restored after, so a late group landing mid-arrow never jumps
        the focus (Quill's 'your place is kept')."""
        if self._current_section != SECTION_SEARCH:
            # The user moved on; keep the results for when they return,
            # but do not yank the tree out from under another section.
            self._search_stations = sorted(
                self._search_stations + stations, key=lambda s: s.name.lower())
            return
        selected = self.station_list.GetFirstSelected()
        merged = sorted(self._search_stations + stations,
                        key=lambda s: s.name.lower())
        self._search_stations = merged
        self._show_flat_list(merged)
        if 0 <= selected < len(merged):
            self.station_list.Select(selected)
            self.station_list.Focus(selected)
            self.station_list.EnsureVisible(selected)

    # ------------------------------------------------------------------
    # Multi-source catalog (services/sources/) -- the Sources section.
    # The group list shows enabled sources; the station list shows the
    # selected source's browse rows. radio_panel owns the worker thread
    # and calls set_source_rows()/set_source_failed() back on the UI
    # thread; this class only renders, so every method here is cheap.
    # ------------------------------------------------------------------

    def show_sources(self, source_labels: list[tuple[str, str]],
                     switch_section: bool = True) -> None:
        """Populate the Sources section's group list. When
        *switch_section* is True (user action), switches to the Sources
        section; when False (startup priming), just stores the data so
        _on_section_changed can render it instantly when the user arrives.
        """
        self._source_labels = [label for label, _sid in source_labels]
        self._source_ids = [sid for _label, sid in source_labels]
        if not source_labels or not switch_section:
            return
        idx = [key for _, key, *_ in SECTION_CHOICES].index(SECTION_SOURCES)
        self.section_choice.SetSelection(idx)
        self._current_section = SECTION_SOURCES
        self._update_group_label(SECTION_SOURCES)
        self._current_groups = [(label, 0) for label in self._source_labels]
        self.group_list.set_groups(self._current_groups)
        if self._current_groups:
            self._select_group_index(0)

    def set_source_rows(self, source_id: str, rows: list) -> None:
        """Render a source's browse rows (SourceNode list) in the station
        list. Rows are kept as-is: playable nodes activate through
        on_source_node_activated, folder nodes re-browse through
        on_source_selected with the node's path."""
        self._source_nodes[source_id] = rows
        self._source_failed.discard(source_id)
        if self._source_selected == source_id:
            self._render_source_rows(source_id)

    def set_source_failed(self, source_id: str, sentence: str) -> None:
        """Render a source's honest failure sentence as its single row --
        never a silent empty list, which is indistinguishable from
        'nothing here'."""
        self._source_failed.add(source_id)
        self._source_nodes[source_id] = [sentence]
        if self._source_selected == source_id:
            self._render_source_rows(source_id)

    def _render_source_rows(self, source_id: str) -> None:
        rows = self._source_nodes.get(source_id, [])
        self._current_source_rows = rows
        # The virtual list serves rows through OnGetItemText (see
        # _VirtualStationList.set_source_rows) -- a failure sentence is
        # just a one-string row list, so it renders identically.
        self.station_list.set_source_rows(rows)
        if rows:
            self.station_list.SetItemState(0, wx.LIST_STATE_SELECTED, wx.LIST_STATE_SELECTED)

    def get_selected_source_row(self):
        """The SourceNode under the cursor in the Sources section, or None."""
        idx = self.station_list.GetFirstSelected()
        rows = getattr(self, "_current_source_rows", [])
        if 0 <= idx < len(rows):
            return rows[idx]
        return None

    def get_selected_station(self) -> Optional[Station]:
        if self._current_section == SECTION_SOURCES:
            # Source rows are SourceNodes, not Stations -- returning a
            # stale Station from the previous section would make the
            # Record/context-menu actions target the wrong thing.
            return None
        idx = self.station_list.GetFirstSelected()
        if 0 <= idx < len(self._current_stations):
            return self._current_stations[idx]
        return None

    def _update_group_label(self, key: str) -> None:
        for _label, section_key, column_header, caption in SECTION_CHOICES:
            if section_key == key:
                self.group_label.SetLabel(caption)
                col = wx.ListItem()
                col.SetText(column_header)
                self.group_list.SetColumn(0, col)
                return

    def _show_section(self, key: str) -> None:
        self._current_section = key
        self._update_group_label(key)
        groups = self._section_groups.get(key, [])
        self._current_groups = groups
        self.group_list.set_groups(groups)
        self._select_group_index(0)

    def _show_flat_list(self, stations: list[Station]) -> None:
        self._current_groups = []
        self.group_list.set_groups([])
        self._populate_station_list(stations)

    def _select_group_index(self, idx: int) -> None:
        if not (0 <= idx < len(self._current_groups)):
            self._populate_station_list([])
            return
        if self._current_section == SECTION_SOURCES and idx < len(self._source_ids):
            # Sources mode: claim the selection BEFORE Select() fires
            # _on_group_selected (which would otherwise re-browse the
            # previously selected source), then render the cache or ask
            # the panel to browse -- a re-expand of a cached source is
            # instant with no second "Loading...".
            self._source_selected = self._source_ids[idx]
            self.group_list.Select(idx)
            self.group_list.Focus(idx)
            self.group_list.EnsureVisible(idx)
            if self._source_selected in self._source_nodes:
                self._render_source_rows(self._source_selected)
            elif self.on_source_selected:
                self.on_source_selected(self._source_selected)
            return
        self.group_list.Select(idx)
        self.group_list.Focus(idx)
        self.group_list.EnsureVisible(idx)
        name, _count = self._current_groups[idx]
        self._load_stations_for_group(name)

    def _load_stations_for_group(self, name: str) -> None:
        if name == ALL_LABELS.get(self._current_section):
            stations = self.db.all_stations()
        elif self._current_section == SECTION_ALPHABET:
            stations = self.db.stations_by_letter(name)
        elif self._current_section == SECTION_GENRE:
            stations = self.db.stations_by_genre(name)
        elif self._current_section == SECTION_COUNTRY:
            stations = self.db.stations_by_country(name)
        elif self._current_section == SECTION_NETWORK:
            stations = self.db.stations_by_network(name)
        else:
            stations = self.db.stations_by_language(name)
        self._populate_station_list(stations)

    def set_show_duplicates(self, enabled: bool) -> None:
        """When disabled, stations sharing the same name (case/whitespace
        insensitive) are collapsed to the single highest-bitrate entry --
        radio-browser.info commonly has the same station submitted more
        than once with slightly different metadata."""
        self._show_duplicates = enabled

    def _dedupe_stations(self, stations: list[Station]) -> list[Station]:
        if self._show_duplicates:
            return stations
        best: dict[str, Station] = {}
        order: list[str] = []
        for s in stations:
            key = " ".join(s.name.split()).lower()
            if key not in best:
                order.append(key)
                best[key] = s
            elif s.bitrate > best[key].bitrate:
                best[key] = s
        return [best[key] for key in order]

    def _populate_station_list(self, stations: list[Station]) -> None:
        stations = self._dedupe_stations(stations)
        self._current_stations = stations
        self.station_list.set_stations(stations)
        if stations:
            self.station_list.Select(0)
            self.station_list.Focus(0)
        if self.on_selection_changed:
            self.on_selection_changed()

    def _on_section_changed(self, event: wx.CommandEvent) -> None:
        idx = self.section_choice.GetSelection()
        if idx == wx.NOT_FOUND:
            return
        key = SECTION_CHOICES[idx][1]
        if key in (SECTION_ALPHABET, SECTION_GENRE, SECTION_COUNTRY, SECTION_LANGUAGE, SECTION_NETWORK):
            self._show_section(key)
        elif key == SECTION_SOURCES:
            # The Sources section's group list is populated by
            # show_sources() (called at startup or by on_sources_needed).
            # If the data is already there, just render it; otherwise ask.
            self._current_section = SECTION_SOURCES
            self._update_group_label(SECTION_SOURCES)
            if self._source_ids:
                self._current_groups = [(label, 0) for label in self._source_labels]
                self.group_list.set_groups(self._current_groups)
                self._select_group_index(0)
            elif self.on_sources_needed:
                self.on_sources_needed()
        elif key == SECTION_CUSTOM:
            self._current_section = SECTION_CUSTOM
            self._update_group_label(SECTION_CUSTOM)
            self._show_flat_list(self._custom_stations)
        elif key == SECTION_FAVORITES:
            self._current_section = SECTION_FAVORITES
            self._update_group_label(SECTION_FAVORITES)
            self._show_flat_list(self._favorite_stations)
        else:
            self._current_section = SECTION_SEARCH
            self._update_group_label(SECTION_SEARCH)
            self._show_flat_list(self._search_stations)

    def _on_group_selected(self, event: wx.ListEvent) -> None:
        idx = event.GetIndex()
        if not (0 <= idx < len(self._current_groups)):
            return
        name, _count = self._current_groups[idx]
        if self._current_section == SECTION_SOURCES:
            # Selecting a source lazily browses it: the panel's worker
            # thread calls set_source_rows()/set_source_failed() back.
            # Until then the station list keeps whatever it had -- the
            # "Loading..." row is the panel's to add, matching Quill's
            # contract that a branch never looks permanently stuck.
            # _select_group_index() already fired the browse for this
            # selection (Select() re-enters here), so skip when the
            # source is already the selected one -- a double browse
            # would race two workers over one "Loading..." row.
            if idx < len(self._source_ids):
                source_id = self._source_ids[idx]
                if source_id != self._source_selected:
                    self._source_selected = source_id
                    if self.on_source_selected:
                        self.on_source_selected(source_id)
            return
        self._load_stations_for_group(name)

    def _on_station_selected(self, event: wx.ListEvent) -> None:
        if self.on_selection_changed:
            self.on_selection_changed()

    def _on_station_activated_event(self, event: wx.ListEvent) -> None:
        idx = event.GetIndex()
        if self._current_section == SECTION_SOURCES:
            # A source row: playable nodes hand their StationRef to the
            # panel; folder nodes re-browse through on_source_selected
            # with the node's own path (the panel knows the source).
            row = self.get_selected_source_row()
            if row is not None and self.on_source_node_activated:
                self.on_source_node_activated(row)
            return
        if 0 <= idx < len(self._current_stations) and self.on_station_activated:
            self.on_station_activated(self._current_stations[idx])
