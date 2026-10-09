"""Station Catalog Status dialog (Tools > Station Catalog Status...).

Read-only summary of the offline station catalog: how many stations are
stored, when it was last refreshed, the configured refresh schedule, and
when the next scheduled refresh is due -- plus an "Update Now" button
that reuses the exact same StationUpdater flow (background thread +
progress) the Settings > Radio page already runs, so there is one update
code path, not two.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Callable, Optional

import wx

from radiomaster.services.station_update_scheduler import (
    FREQUENCY_LABELS,
    UPDATE_OFF_HOUR,
)
from radiomaster.utils.accessibility import set_accessible_name
from radiomaster.utils.wx_safe import call_after_safe


def relative_time(when: Optional[datetime], now: Optional[datetime] = None) -> str:
    """English relative time ("3 days ago", "just now") for a timestamp.

    Every refusal gets its own sentence: a missing timestamp is never
    silently rendered as an empty string -- callers get "never" so a
    screen reader hears a specific fact, not silence.
    """
    if when is None:
        return "never"
    now = now or datetime.now()
    seconds = int((now - when).total_seconds())
    if seconds < 0:
        return "just now"
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = hours // 24
    if days < 30:
        return f"{days} day{'s' if days != 1 else ''} ago"
    months = days // 30
    if months < 12:
        return f"{months} month{'s' if months != 1 else ''} ago"
    years = months // 12
    return f"{years} year{'s' if years != 1 else ''} ago"


def _next_run(frequency: str, last_updated: Optional[datetime],
              now: Optional[datetime] = None) -> Optional[datetime]:
    """When the scheduler's cron job next fires, from the same rules
    services/station_update_scheduler.py builds its CronTrigger from
    (daily/weekly/monthly/... at the fixed off-peak hour). "off" and
    unknown frequencies have no next run -- None, which the dialog
    renders as its own sentence rather than silence."""
    if frequency not in FREQUENCY_LABELS or frequency == "off":
        return None
    now = now or datetime.now()
    candidates: list[datetime] = []
    if frequency == "daily":
        # Today's off-peak hour AND tomorrow's -- after 3 AM has already
        # passed, "today" is filtered out below and tomorrow answers.
        today = now.replace(hour=UPDATE_OFF_HOUR, minute=0, second=0, microsecond=0)
        candidates = [today, today + timedelta(days=1)]
    elif frequency == "weekly":
        start = (now - timedelta(days=(now.weekday() + 1) % 7)).replace(
            hour=UPDATE_OFF_HOUR, minute=0, second=0, microsecond=0)
        candidates = [start, start + timedelta(days=7)]
    elif frequency == "monthly":
        first = now.replace(day=1, hour=UPDATE_OFF_HOUR, minute=0, second=0, microsecond=0)
        next_month = (first + timedelta(days=32)).replace(day=1)
        candidates = [first, next_month]
    elif frequency == "quarterly":
        first = now.replace(month=((now.month - 1) // 3) * 3 + 1, day=1,
                            hour=UPDATE_OFF_HOUR, minute=0, second=0, microsecond=0)
        candidates = [first, first + timedelta(days=95)]
    elif frequency == "six_monthly":
        first = now.replace(month=1 if now.month <= 6 else 7, day=1,
                            hour=UPDATE_OFF_HOUR, minute=0, second=0, microsecond=0)
        candidates = [first, first + timedelta(days=185)]
    elif frequency == "yearly":
        first = now.replace(month=1, day=1, hour=UPDATE_OFF_HOUR, minute=0,
                            second=0, microsecond=0)
        candidates = [first, first + timedelta(days=366)]
    upcoming = [c for c in candidates if c > now]
    return min(upcoming) if upcoming else None


class CatalogStatusDialog(wx.Dialog):
    """Read-only catalog summary + "Update Now" (existing updater flow)."""

    def __init__(self, parent: wx.Window, station_db, station_updater,
                 frequency: str = "weekly",
                 on_update_finished: Optional[Callable[[], None]] = None) -> None:
        super().__init__(parent, title="Station Catalog Status",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._station_db = station_db
        self._station_updater = station_updater
        self._frequency = frequency
        self._on_update_finished = on_update_finished
        self._updating = False

        count = self._station_db.station_count()
        last_updated = self._station_db.last_updated()
        self._count = count
        self._last_updated = last_updated

        sizer = wx.BoxSizer(wx.VERTICAL)
        self._summary = wx.TextCtrl(
            self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_BESTWRAP,
            value=self._build_summary(count, last_updated),
        )
        self._summary.SetMinSize((520, 120))
        set_accessible_name(self._summary, "Station catalog status summary")
        sizer.Add(self._summary, 1, wx.EXPAND | wx.ALL, 10)

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self._update_btn = wx.Button(self, label="Update &Now")
        set_accessible_name(self._update_btn, "Update station catalog now")
        self._update_btn.Bind(wx.EVT_BUTTON, self._on_update_now)
        btn_sizer.Add(self._update_btn, 0, wx.RIGHT, 8)
        close_btn = wx.Button(self, wx.ID_CLOSE)
        set_accessible_name(close_btn, "Close Station Catalog Status")
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE))
        btn_sizer.Add(close_btn, 0)
        sizer.Add(btn_sizer, 0, wx.ALIGN_RIGHT | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.SetSizerAndFit(sizer)
        self.SetMinSize((560, 260))

    def _build_summary(self, count: int, last_updated: Optional[datetime]) -> str:
        """The sentences announced on open -- one per fact, never silence."""
        label = FREQUENCY_LABELS.get(self._frequency, self._frequency or "Off")
        refresh_sentence = (
            f"Refreshes {label.lower()}." if self._frequency not in ("off", "")
            else "Automatic refresh is off. Update manually with the Update Now button."
        )
        next_run = _next_run(self._frequency, last_updated)
        next_sentence = (
            f"Next scheduled update {relative_time(next_run)} "
            f"({next_run.strftime('%A, %B %d at %I:%M %p') if next_run else ''})."
            if next_run else "No update is currently scheduled."
        )
        return (
            f"{count:,} stations stored in the offline catalog.\n"
            f"Last updated {relative_time(last_updated)}.\n"
            f"{refresh_sentence}\n"
            f"{next_sentence}"
        )

    def summary_sentence(self) -> str:
        """One-line announcement for the status bar on open."""
        label = FREQUENCY_LABELS.get(self._frequency, self._frequency or "Off")
        return (
            f"{self._count:,} stations stored. "
            f"Last updated {relative_time(self._last_updated)}. "
            f"Refreshes {label.lower()}."
            if self._frequency not in ("off", "")
            else f"{self._count:,} stations stored. "
                 f"Last updated {relative_time(self._last_updated)}. "
                 "Automatic refresh is off."
        )

    def _on_update_now(self, event: wx.CommandEvent) -> None:
        """Run the existing StationUpdater flow (same as Settings > Radio):
        background thread, progress text, and a specific failure sentence
        -- never a silent success or a silent failure."""
        if self._updating or not self._station_updater:
            return
        self._updating = True
        self._update_btn.Disable()
        self._summary.SetValue("Updating station catalog...")

        def progress_cb(bytes_read: int, total) -> None:
            if total:
                percent = min(100, int(bytes_read * 100 / total))
                text = f"Updating station catalog... {percent}%"
            else:
                text = f"Updating station catalog... ({bytes_read // 1024} KB)"
            call_after_safe(self, self._summary.SetValue, text)

        def worker():
            try:
                result = self._station_updater.update_now(progress_cb=progress_cb)
            except Exception as exc:
                result = None
                call_after_safe(self, self._update_failed, str(exc))
            if result is not None:
                if result.ok:
                    call_after_safe(self, self._update_succeeded, result)
                else:
                    call_after_safe(self, self._update_failed, result.error)

        threading.Thread(target=worker, daemon=True).start()

    def _update_succeeded(self, result) -> None:
        self._updating = False
        self._update_btn.Enable()
        self._last_updated = self._station_db.last_updated()
        self._summary.SetValue(
            f"Update finished: {result.changed} stations changed, "
            f"{result.unchanged} unchanged.\n\n"
            + self._build_summary(self._station_db.station_count(), self._last_updated)
        )
        if self._on_update_finished:
            self._on_update_finished()

    def _update_failed(self, error: str) -> None:
        self._updating = False
        self._update_btn.Enable()
        self._summary.SetValue(
            f"Update failed: {error}\n\n"
            + self._build_summary(self._count, self._last_updated)
        )