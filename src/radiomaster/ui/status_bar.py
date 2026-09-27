"""Status bar for RadioMaster+."""

import wx

from radiomaster.utils.accessibility import _KEEPALIVE


def _format_hms(seconds: float) -> str:
    """0:00 / 12:34 / 1:02:03 -- hours only shown once actually needed,
    matching how the transport bar's own time display already reads."""
    total = max(0, int(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class _StatusAccessible(wx.Accessible):
    """Expose current painted fields without generating native text events."""

    def __init__(self, window, fields):
        super().__init__(window)
        self._fields = fields

    def GetName(self, childId):
        if childId == wx.ACC_SELF:
            return wx.ACC_OK, "Status: " + "; ".join(filter(None, self._fields))
        if 1 <= childId <= len(self._fields):
            return wx.ACC_OK, self._fields[childId - 1]
        return wx.ACC_NOT_IMPLEMENTED, ""

    def GetChildCount(self):
        return wx.ACC_OK, len(self._fields)

    def GetRole(self, childId):
        if childId == wx.ACC_SELF:
            return wx.ACC_OK, wx.ROLE_SYSTEM_STATUSBAR
        if 1 <= childId <= len(self._fields):
            return wx.ACC_OK, wx.ROLE_SYSTEM_STATICTEXT
        return wx.ACC_NOT_IMPLEMENTED, 0


class StatusBar(wx.StatusBar):
    """Custom status bar with multiple fields for playback status."""

    FIELD_STATUS = 0
    FIELD_BUFFERING = 1
    FIELD_QUALITY = 2
    FIELD_SOURCE = 3
    FIELD_FORMAT = 4

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent, style=wx.SB_FLAT)
        self.SetFieldsCount(5)
        # FIELD_QUALITY carries elapsed/total/remaining now (see
        # set_time_info) instead of the bitrate/quality text its name
        # suggests -- that needs more room than the other three fields.
        self.SetStatusWidths([-2, -1, -3, -2, -2])
        self._announcements_enabled = False
        self._last_announced = ""
        self._field_texts = ["Ready", "", "", "", ""]
        self._accessible = _StatusAccessible(self, self._field_texts)
        self.SetAccessible(self._accessible)
        _KEEPALIVE.append(self._accessible)
        self.SetName("Status")
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self._announcement_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._announce_status, self._announcement_timer)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)

    def _on_paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(self.GetBackgroundColour()))
        dc.Clear()
        dc.SetFont(self.GetFont())
        dc.SetTextForeground(self.GetForegroundColour())
        for index, text in enumerate(self._field_texts):
            rect = self.GetFieldRect(index)
            rect.Deflate(3, 0)
            if rect.width <= 0 or rect.height <= 0:
                continue
            dc.SetClippingRegion(rect)
            label = wx.Control.Ellipsize(text, dc, wx.ELLIPSIZE_END, rect.width)
            height = dc.GetTextExtent(label).height
            dc.DrawText(label, rect.x, rect.y + max(0, (rect.height - height) // 2))
            dc.DestroyClippingRegion()

    def SetStatusText(self, text: str, number: int = 0) -> None:
        """Paint cached text; native SetStatusText emits unsolicited MSAA events."""
        if self._field_texts[number] != text:
            self._field_texts[number] = text
            self.RefreshRect(self.GetFieldRect(number))

    def GetStatusText(self, number: int = 0) -> str:
        return self._field_texts[number]

    def set_status(self, text: str, announce: bool = True) -> None:
        """Coalesce status changes; numerical download progress stays silent."""
        self.SetStatusText(text, self.FIELD_STATUS)
        self._announcement_timer.Stop()
        if not announce:
            return
        if self._announcements_enabled and text != self._last_announced:
            self._announcement_timer.StartOnce(500)

    def _announce_status(self, event=None):
        self._announcement_timer.Stop()
        text = self.GetStatusText(self.FIELD_STATUS)
        if self._announcements_enabled and text and text != self._last_announced:
            self._last_announced = text
            try:
                wx.Accessible.NotifyEvent(
                    wx.ACC_EVENT_OBJECT_NAMECHANGE, self, wx.OBJID_CLIENT, 1
                )
            except (AttributeError, RuntimeError):
                pass

    def _on_destroy(self, event):
        if event.GetEventObject() == self:
            self._announcement_timer.Stop()
        event.Skip()

    def set_screen_reader_announcements(self, enabled: bool) -> None:
        """Enable concise announcements for meaningful status changes."""
        self._announcements_enabled = bool(enabled)
        if not enabled:
            self._announcement_timer.Stop()
            self._last_announced = ""

    def set_buffering(self, percent: int) -> None:
        """Set buffering percentage."""
        if percent >= 100:
            self.SetStatusText("", self.FIELD_BUFFERING)
        else:
            self.SetStatusText(f"Buffering: {percent}%", self.FIELD_BUFFERING)

    def set_quality(self, text: str) -> None:
        """Set quality/bitrate info."""
        self.SetStatusText(text, self.FIELD_QUALITY)

    def set_source(self, text: str) -> None:
        """Set source type (Radio, Podcast, etc.)."""
        self.SetStatusText(text, self.FIELD_SOURCE)

    def set_format(self, text: str) -> None:
        """Set the station's actual broadcast format -- codec, sample
        rate, channel count, bitrate (see services/stream_prober.py).
        Probed directly from the stream rather than trusted from the
        station database, whose codec/bitrate fields are self-reported
        and often missing or wrong."""
        self.SetStatusText(text, self.FIELD_FORMAT)

    def set_time_info(self, elapsed: float, duration: float) -> None:
        """Elapsed/total/remaining -- for a podcast episode (a real,
        finite duration) shows all three; for radio (duration is always
        0, unbounded) there's no total or remaining to show, so this is
        just how long the current stream connection has been playing."""
        if duration > 0:
            remaining = max(0.0, duration - elapsed)
            text = (
                f"Elapsed {_format_hms(elapsed)}  /  "
                f"Total {_format_hms(duration)}  /  "
                f"Remaining {_format_hms(remaining)}"
            )
        elif elapsed > 0:
            text = f"Elapsed {_format_hms(elapsed)}"
        else:
            text = ""
        self.SetStatusText(text, self.FIELD_QUALITY)
