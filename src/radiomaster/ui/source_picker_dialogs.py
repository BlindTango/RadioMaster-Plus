"""Pickers used by the recording schedule dialog: a station, or a podcast episode."""

from __future__ import annotations

import wx

from radiomaster.services.schedule_sources import (
    ScheduleSources, SourcePick, pick_from_episode, pick_from_station)
from radiomaster.utils.accessibility import set_accessible_name


class StationPickerDialog(wx.Dialog):
    """Search stations; with nothing typed it lists favorites and custom stations."""

    def __init__(self, parent, sources: ScheduleSources):
        super().__init__(parent, title="Choose Station", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._sources = sources
        self._stations: list = []
        self._pick: SourcePick | None = None
        layout = wx.BoxSizer(wx.VERTICAL)

        layout.Add(wx.StaticText(self, label="&Search stations by name (leave empty for "
                                             "favorites and custom stations):"), 0, wx.ALL, 8)
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.query = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        set_accessible_name(self.query, "Search stations by name")
        self.search_btn = wx.Button(self, label="S&earch")
        row.Add(self.query, 1, wx.RIGHT, 6)
        row.Add(self.search_btn, 0)
        layout.Add(row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        layout.Add(wx.StaticText(self, label="&Stations:"), 0, wx.ALL, 8)
        self.results = wx.ListBox(self, size=(480, 220))
        set_accessible_name(self.results, "Stations found")
        layout.Add(self.results, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        self.status = wx.StaticText(self, label="")
        layout.Add(self.status, 0, wx.ALL, 8)
        layout.Add(self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALIGN_RIGHT | wx.ALL, 8)
        self.SetSizerAndFit(layout)
        self.SetMinSize((520, -1))

        self.query.Bind(wx.EVT_TEXT_ENTER, lambda e: self.search())
        self.search_btn.Bind(wx.EVT_BUTTON, lambda e: self.search())
        self.results.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self._on_ok())
        self.results.Bind(wx.EVT_LISTBOX, lambda e: self._update_ok())
        self.Bind(wx.EVT_BUTTON, lambda e: self._on_ok(), id=wx.ID_OK)
        self.search()
        self.query.SetFocus()

    def search(self) -> None:
        self._stations = self._sources.stations(self.query.GetValue())
        labels = []
        for station in self._stations:
            detail = ", ".join(part for part in (
                getattr(station, "country", ""),
                f"{station.bitrate} kbps" if getattr(station, "bitrate", 0) else "") if part)
            labels.append(f"{station.name} ({detail})" if detail else station.name)
        self.results.Set(labels)
        if labels:
            self.results.SetSelection(0)
        self.status.SetLabel(f"{len(labels)} station(s) found." if labels else
                             "No stations found. Try other words in the name.")
        self._update_ok()

    def _update_ok(self) -> None:
        self.FindWindowById(wx.ID_OK).Enable(self.results.GetSelection() != wx.NOT_FOUND)

    def _on_ok(self) -> None:
        index = self.results.GetSelection()
        if index == wx.NOT_FOUND or index >= len(self._stations):
            return
        pick = pick_from_station(self._stations[index])
        if pick is None:
            self.status.SetLabel("That station has no online address to record.")
            return
        self._pick = pick
        if self.IsModal():
            self.EndModal(wx.ID_OK)

    def pick(self) -> SourcePick | None:
        return self._pick


class EpisodePickerDialog(wx.Dialog):
    """Choose a subscribed podcast, then one of its episodes."""

    def __init__(self, parent, sources: ScheduleSources):
        super().__init__(parent, title="Choose Podcast Episode",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._sources = sources
        self._shows = sources.podcast_shows()
        self._episodes: list = []
        self._pick: SourcePick | None = None
        layout = wx.BoxSizer(wx.VERTICAL)

        layout.Add(wx.StaticText(self, label="&Podcast:"), 0, wx.ALL, 8)
        self.show_choice = wx.Choice(self, choices=[show.get("title") or "Untitled podcast"
                                                    for show in self._shows])
        set_accessible_name(self.show_choice, "Subscribed podcast")
        layout.Add(self.show_choice, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        layout.Add(wx.StaticText(self, label="&Episodes:"), 0, wx.ALL, 8)
        self.results = wx.ListBox(self, size=(480, 220))
        set_accessible_name(self.results, "Episodes of the chosen podcast")
        layout.Add(self.results, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        self.status = wx.StaticText(self, label="")
        layout.Add(self.status, 0, wx.ALL, 8)
        layout.Add(self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALIGN_RIGHT | wx.ALL, 8)
        self.SetSizerAndFit(layout)
        self.SetMinSize((520, -1))

        self.show_choice.Bind(wx.EVT_CHOICE, lambda e: self._load_episodes())
        self.results.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self._on_ok())
        self.results.Bind(wx.EVT_LISTBOX, lambda e: self._update_ok())
        self.Bind(wx.EVT_BUTTON, lambda e: self._on_ok(), id=wx.ID_OK)
        if self._shows:
            self.show_choice.SetSelection(0)
            self._load_episodes()
        else:
            self.status.SetLabel("You are not subscribed to any podcasts yet. Subscribe in the "
                                 "Podcasts tab first.")
            self._update_ok()
        self.show_choice.SetFocus()

    def _load_episodes(self) -> None:
        index = self.show_choice.GetSelection()
        if index == wx.NOT_FOUND:
            return
        self._episodes = self._sources.episodes(self._shows[index]["id"])
        self.results.Set([
            f"{ep.get('title') or 'Episode'}" + (f" ({ep['published_date']})" if ep.get("published_date") else "")
            for ep in self._episodes])
        if self._episodes:
            self.results.SetSelection(0)
        self.status.SetLabel(f"{len(self._episodes)} episode(s)." if self._episodes else
                             "This podcast has no episodes with an online audio address.")
        self._update_ok()

    def _update_ok(self) -> None:
        self.FindWindowById(wx.ID_OK).Enable(self.results.GetSelection() != wx.NOT_FOUND)

    def _on_ok(self) -> None:
        show_index, index = self.show_choice.GetSelection(), self.results.GetSelection()
        if show_index == wx.NOT_FOUND or index == wx.NOT_FOUND or index >= len(self._episodes):
            return
        pick = pick_from_episode(self._shows[show_index], self._episodes[index])
        if pick is None:
            self.status.SetLabel("That episode has no online audio address to record.")
            return
        self._pick = pick
        if self.IsModal():
            self.EndModal(wx.ID_OK)

    def pick(self) -> SourcePick | None:
        return self._pick
