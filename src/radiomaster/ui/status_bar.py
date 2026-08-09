"""Status bar for RadioMaster+."""

import wx


def _format_hms(seconds: float) -> str:
    """0:00 / 12:34 / 1:02:03 -- hours only shown once actually needed,
    matching how the transport bar's own time display already reads."""
    total = max(0, int(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class StatusBar(wx.StatusBar):
    """Custom status bar with multiple fields for playback status."""

    FIELD_STATUS = 0
    FIELD_BUFFERING = 1
    FIELD_QUALITY = 2
    FIELD_SOURCE = 3

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent, style=wx.SB_FLAT)
        self.SetFieldsCount(4)
        # FIELD_QUALITY carries elapsed/total/remaining now (see
        # set_time_info) instead of the bitrate/quality text its name
        # suggests -- that needs more room than the other three fields.
        self.SetStatusWidths([-2, -1, -3, -2])

        self._set_defaults()

    def _set_defaults(self) -> None:
        """Set default status text."""
        self.SetStatusText("Ready", self.FIELD_STATUS)
        self.SetStatusText("", self.FIELD_BUFFERING)
        self.SetStatusText("", self.FIELD_QUALITY)
        self.SetStatusText("", self.FIELD_SOURCE)

    def set_status(self, text: str) -> None:
        """Set the main status field."""
        self.SetStatusText(text, self.FIELD_STATUS)

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
