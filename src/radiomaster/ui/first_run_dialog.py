"""First-run wizard: 3-4 arrow-through text pages, shown once.

Follows Quill Radio's contract: each page is a read-only text box the
user can arrow through (not a wall of static labels), and Skip leaves
in one keystroke and never asks again (general.first_run_complete).
No network, no account.
"""

from __future__ import annotations

import wx

from radiomaster.utils.accessibility import set_accessible_name

PAGES: list[tuple[str, str]] = [
    (
        "Welcome",
        "Welcome to RadioMaster+.\n\n"
        "RadioMaster+ plays internet radio, podcasts, audiobooks, local "
        "media, and YouTube in one accessible window.\n\n"
        "Press the Down arrow to read more, or Tab to reach the Next and "
        "Skip buttons. Press Next to continue.",
    ),
    (
        "Where things are stored",
        "Where things are stored.\n\n"
        "Your station catalog, subscriptions, downloads, and recordings "
        "are saved on this computer -- nothing is uploaded, and no "
        "account is needed.\n\n"
        "The offline station catalog is refreshed automatically in the "
        "background (Tools > Station Catalog Status shows when).",
    ),
    (
        "Keyboard shortcuts",
        "Keyboard shortcuts.\n\n"
        "Everything can be done from the keyboard: Tab moves between "
        "regions, F6 cycles them, and Ctrl+Tab switches panels.\n\n"
        "Press Ctrl+K to open the Keyboard Shortcuts editor and change "
        "any shortcut.",
    ),
    (
        "Screen reader users",
        "Screen reader users.\n\n"
        "Every control is labeled, every action announces itself in the "
        "status bar, and every refusal gets its own sentence -- never "
        "silence.\n\n"
        "Press Skip to finish. This wizard will not appear again.",
    ),
]


class FirstRunDialog(wx.Dialog):
    """Arrow-through first-run wizard. Skip sets the flag and never
    asks again; Next walks the pages; Escape also completes."""

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent, title="Welcome to RadioMaster+",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._page = 0

        sizer = wx.BoxSizer(wx.VERTICAL)
        self._page_text = wx.TextCtrl(
            self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_BESTWRAP,
            value=PAGES[0][1],
        )
        self._page_text.SetMinSize((520, 220))
        set_accessible_name(self._page_text, f"Welcome page 1 of {len(PAGES)}: {PAGES[0][0]}")
        sizer.Add(self._page_text, 1, wx.EXPAND | wx.ALL, 10)

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self._skip_btn = wx.Button(self, wx.ID_CANCEL, label="&Skip")
        self.SetEscapeId(wx.ID_CANCEL)
        set_accessible_name(self._skip_btn, "Skip the welcome wizard")
        # wx has no ID_SKIP; ID_CANCEL carries the "leave without
        # continuing" meaning and both Skip and Finish set the flag in
        # MainWindow._show_first_run_wizard, so the code only ends the
        # dialog.
        self._skip_btn.Bind(wx.EVT_BUTTON, lambda e: self._finish(wx.ID_CANCEL))
        btn_sizer.Add(self._skip_btn, 0, wx.RIGHT, 8)
        self._next_btn = wx.Button(self, label="&Next")
        set_accessible_name(self._next_btn, "Next welcome page")
        self._next_btn.Bind(wx.EVT_BUTTON, self._on_next)
        btn_sizer.Add(self._next_btn, 0)
        sizer.Add(btn_sizer, 0, wx.ALIGN_RIGHT | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.SetSizerAndFit(sizer)
        self.SetMinSize((560, 340))
        # The text box is the whole point: focus starts there so arrows
        # read the page immediately.
        self._page_text.SetFocus()

    def _on_next(self, event: wx.CommandEvent) -> None:
        if self._page + 1 < len(PAGES):
            self._page += 1
            title, body = PAGES[self._page]
            self._page_text.SetValue(body)
            set_accessible_name(
                self._page_text,
                f"Welcome page {self._page + 1} of {len(PAGES)}: {title}",
            )
            self._page_text.SetFocus()
            if self._page + 1 == len(PAGES):
                self._next_btn.SetLabel("&Finish")
                set_accessible_name(self._next_btn, "Finish the welcome wizard")
        else:
            self._finish(wx.ID_OK)

    def _finish(self, code: int) -> None:
        self.EndModal(code)
