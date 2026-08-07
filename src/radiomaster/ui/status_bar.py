"""Status bar for RadioMaster+."""

import wx


class StatusBar(wx.StatusBar):
    """Custom status bar with multiple fields for playback status."""

    FIELD_STATUS = 0
    FIELD_BUFFERING = 1
    FIELD_QUALITY = 2
    FIELD_SOURCE = 3

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent, style=wx.SB_FLAT)
        self.SetFieldsCount(4)
        self.SetStatusWidths([-2, -2, -1, -1])

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
