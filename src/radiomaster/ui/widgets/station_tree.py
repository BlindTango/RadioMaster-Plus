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
SECTION_SEARCH = "search"

SECTION_CHOICES = [
    ("Alphabetical", SECTION_ALPHABET, "Letter", "Letters:"),
    ("By Genre", SECTION_GENRE, "Genre", "Genres:"),
    ("By Country", SECTION_COUNTRY, "Country", "Countries:"),
    ("By Language", SECTION_LANGUAGE, "Language", "Languages:"),
    ("By Network", SECTION_NETWORK, "Network", "Networks:"),
    ("Custom Stations", SECTION_CUSTOM, "Station", "Custom Stations:"),
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
        self._init_typeahead()

    def OnGetItemText(self, item, column):
        if not (0 <= item < len(self.stations)):
            return ""
        station = self.stations[item]
        if column == 0:
            return station.name
        if column == 1:
            return station.country
        return str(station.bitrate) if station.bitrate else ""

    def set_stations(self, stations: list[Station]) -> None:
        self.stations = stations
        self.SetItemCount(len(stations))
        if stations:
            self.RefreshItems(0, len(stations) - 1)

    def _typeahead_item_text(self, index: int) -> str:
        return self.stations[index].name

    def _typeahead_count(self) -> int:
        return len(self.stations)


class StationTree(wx.Panel):
    """Two-pane station browser: Category (Choice) -> Groups (ListCtrl) -> Stations (ListCtrl)."""

    def __init__(self, parent, db: StationDB):
        super().__init__(parent)
        self.db = db
        self.on_station_activated: Optional[Callable[[Station], None]] = None
        self.on_selection_changed: Optional[Callable[[], None]] = None

        self._section_groups: dict[str, list[tuple[str, int]]] = {}
        self._current_section: str = SECTION_ALPHABET
        self._current_groups: list[tuple[str, int]] = []
        self._current_stations: list[Station] = []
        self._custom_stations: list[Station] = []
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

    def get_selected_station(self) -> Optional[Station]:
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
        elif key == SECTION_CUSTOM:
            self._current_section = SECTION_CUSTOM
            self._update_group_label(SECTION_CUSTOM)
            self._show_flat_list(self._custom_stations)
        else:
            self._current_section = SECTION_SEARCH
            self._update_group_label(SECTION_SEARCH)
            self._show_flat_list(self._search_stations)

    def _on_group_selected(self, event: wx.ListEvent) -> None:
        idx = event.GetIndex()
        if not (0 <= idx < len(self._current_groups)):
            return
        name, _count = self._current_groups[idx]
        self._load_stations_for_group(name)

    def _on_station_selected(self, event: wx.ListEvent) -> None:
        if self.on_selection_changed:
            self.on_selection_changed()

    def _on_station_activated_event(self, event: wx.ListEvent) -> None:
        idx = event.GetIndex()
        if 0 <= idx < len(self._current_stations) and self.on_station_activated:
            self.on_station_activated(self._current_stations[idx])
