"""Lyrics / Show Notes / Book Text panel with sentence highlighting."""

import wx
from radiomaster.utils.accessibility import set_accessible_name


class LyricsPanel(wx.Panel):
    """Multiline text panel for lyrics, show notes, or book content."""

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Create the text display."""
        sizer = wx.BoxSizer(wx.VERTICAL)

        self._text_ctrl = wx.TextCtrl(
            self,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2 | wx.TE_WORDWRAP,
        )
        set_accessible_name(self._text_ctrl, "Content Display")
        sizer.Add(self._text_ctrl, 1, wx.EXPAND)

        self.SetSizer(sizer)

    def set_content(self, text: str) -> None:
        """Set the text content."""
        self._text_ctrl.SetValue(text)

    def append_content(self, text: str) -> None:
        """Append text to existing content."""
        self._text_ctrl.AppendText(text)

    def clear(self) -> None:
        """Clear all content."""
        self._text_ctrl.Clear()

    def highlight_sentence(self, sentence_index: int) -> None:
        """Highlight a specific sentence with configurable background color."""
        if not hasattr(self, '_lrc_lines') or not self._lrc_lines:
            return
        if sentence_index < 0 or sentence_index >= len(self._lrc_lines):
            return
        # Read highlight color from config
        from radiomaster.utils.config import ConfigManager
        config = ConfigManager.get_instance()
        color_str = config.get("accessibility.highlight_color", default="#FFFF00")
        try:
            r = int(color_str[1:3], 16)
            g = int(color_str[3:5], 16)
            b = int(color_str[5:7], 16)
            highlight = wx.Colour(r, g, b)
        except Exception:
            highlight = wx.Colour(255, 255, 0)
        # Clear previous highlighting
        self._text_ctrl.SetStyle(0, self._text_ctrl.GetLastPosition(), wx.TextAttr())
        # Highlight the current line
        line_start = 0
        for i, (ts, text) in enumerate(self._lrc_lines):
            line_end = line_start + len(text) + 1
            if i == sentence_index:
                self._text_ctrl.SetStyle(line_start, line_end,
                    wx.TextAttr(wx.BLACK, highlight))
            line_start = line_end

    def set_lrc_lines(self, lines: list[tuple[float, str]]) -> None:
        """Store LRC timed lines for synced highlighting."""
        self._lrc_lines = lines
        # Build full text from lines
        full = "\n".join(text for _, text in lines)
        self.set_content(full)

    def set_font_size(self, size: int) -> None:
        """Set the font size for readability."""
        font = self._text_ctrl.GetFont()
        font.SetPointSize(size)
        self._text_ctrl.SetFont(font)

    def set_dyslexia_font(self, enabled: bool) -> None:
        """Toggle dyslexia-friendly font."""
        font = self._text_ctrl.GetFont()
        if enabled:
            font.SetFaceName("OpenDyslexic")
        font.SetFamily(wx.FONTFAMILY_DEFAULT)
        self._text_ctrl.SetFont(font)
