"""Listening Statistics dialog (Tools > Listening Statistics...).

Read-only sentences + a simple list of top stations/shows, announced on
open so a screen reader hears the summary without hunting for it.
"""

from __future__ import annotations

from typing import Optional

import wx

from radiomaster.services.stats_service import StatsService
from radiomaster.utils.accessibility import set_accessible_name


def format_duration(seconds: int) -> str:
    """4h 12m / 12m / 30s -- compact, screen-reader friendly."""
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours} hour{'s' if hours != 1 else ''} {minutes} minute{'s' if minutes != 1 else ''}"
    if minutes:
        return f"{minutes} minute{'s' if minutes != 1 else ''} {secs} second{'s' if secs != 1 else ''}"
    return f"{secs} second{'s' if secs != 1 else ''}"


class StatsDialog(wx.Dialog):
    """Read-only listening statistics summary."""

    def __init__(self, parent: wx.Window, stats: StatsService) -> None:
        super().__init__(parent, title="Listening Statistics",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._stats = stats

        today = stats.totals(since=stats.start_of_today())
        week = stats.totals(since=stats.start_of_week())
        all_time = stats.totals()
        top_stations = stats.top_items("station", limit=5)
        top_shows = stats.top_items("podcast", limit=5)

        sizer = wx.BoxSizer(wx.VERTICAL)
        self._summary = wx.TextCtrl(
            self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_BESTWRAP,
            value=self._build_summary(today, week, all_time),
        )
        self._summary.SetMinSize((520, 130))
        set_accessible_name(self._summary, "Listening statistics summary")
        sizer.Add(self._summary, 0, wx.EXPAND | wx.ALL, 10)

        self._top_list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        self._top_list.InsertColumn(0, "Source", width=330)
        self._top_list.InsertColumn(1, "Time listened", width=140)
        set_accessible_name(self._top_list, "Top stations and shows")
        for source_type, items, empty_sentence in (
                ("Top stations", top_stations, "No stations listened to yet."),
                ("Top shows", top_shows, "No shows listened to yet.")):
            if items:
                self._top_list.Append([source_type, ""])
                for label, seconds in items:
                    self._top_list.Append([label, format_duration(seconds)])
            else:
                # Every absence gets its own sentence, never silence.
                self._top_list.Append([source_type, empty_sentence])
        sizer.Add(self._top_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        close_btn = wx.Button(self, wx.ID_CLOSE)
        set_accessible_name(close_btn, "Close Listening Statistics")
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE))
        sizer.Add(close_btn, 0, wx.ALIGN_RIGHT | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.SetSizerAndFit(sizer)
        self.SetMinSize((560, 380))

    def _build_summary(self, today, week, all_time) -> str:
        return (
            f"Today: {format_duration(today.seconds)} "
            f"across {today.sessions} session{'s' if today.sessions != 1 else ''}.\n"
            f"This week: {format_duration(week.seconds)} "
            f"across {week.sessions} session{'s' if week.sessions != 1 else ''}.\n"
            f"All time: {format_duration(all_time.seconds)} "
            f"across {all_time.sessions} session{'s' if all_time.sessions != 1 else ''}."
        )

    def summary_sentence(self) -> str:
        """One-line announcement for the status bar on open."""
        week = self._stats.totals(since=self._stats.start_of_week())
        return f"You have listened for {format_duration(week.seconds)} this week."