"""Custom stations with a cancellable webpage stream finder."""

from __future__ import annotations

import threading

import wx

from radiomaster.services.stream_discovery import DiscoveryResult, _http_url, discover_streams
from radiomaster.utils.accessibility import set_accessible_name
from radiomaster.utils.wx_safe import call_after_safe


class CustomStationDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(
            parent, title="Add Custom Station", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER
        )
        self._scan_cancel = threading.Event()
        self._scan_generation = 0
        self._closed = False
        self._scanning = False
        self._streams = ()
        layout = wx.BoxSizer(wx.VERTICAL)
        help_text = wx.StaticText(
            self,
            label=(
                "Enter a stream URL directly, or scan a webpage for listen links.\n"
                "Select a found stream to copy its URL or use it for this station."
            ),
        )
        layout.Add(help_text, 0, wx.ALL, 12)

        def field(label, name):
            layout.Add(wx.StaticText(self, label=label), 0, wx.LEFT | wx.RIGHT | wx.TOP, 12)
            control = wx.TextCtrl(self)
            set_accessible_name(control, name)
            layout.Add(control, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
            return control

        self.name_ctrl = field("Station &Name:", "Station name")
        self.url_ctrl = field("Stream &Address:", "Stream URL")
        self.page_ctrl = field("&Webpage URL:", "Webpage URL to scan")
        scan_row = wx.BoxSizer(wx.HORIZONTAL)
        self.scan_btn = wx.Button(self, label="&Scan Webpage")
        self.stop_btn = wx.Button(self, label="S&top Scan")
        self.stop_btn.Disable()
        scan_row.Add(self.scan_btn, 0, wx.RIGHT, 8)
        scan_row.Add(self.stop_btn)
        layout.Add(scan_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        layout.Add(wx.StaticText(self, label="&Found Streams:"), 0, wx.LEFT | wx.RIGHT, 12)
        self.results = wx.ListBox(self, size=(660, 150))
        set_accessible_name(self.results, "Found streams: format and URL")
        layout.Add(self.results, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        result_row = wx.BoxSizer(wx.HORIZONTAL)
        self.use_btn = wx.Button(self, label="&Use Selected Stream")
        self.copy_btn = wx.Button(self, label="&Copy Stream URL")
        self.use_btn.Disable()
        self.copy_btn.Disable()
        result_row.Add(self.use_btn, 0, wx.RIGHT, 8)
        result_row.Add(self.copy_btn)
        layout.Add(result_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        layout.Add(wx.StaticText(self, label="Scan status:"), 0, wx.LEFT | wx.RIGHT, 12)
        self.status = wx.TextCtrl(
            self,
            value="Ready to scan a webpage.",
            style=wx.TE_MULTILINE | wx.TE_READONLY,
            size=(-1, 65),
        )
        set_accessible_name(self.status, "Stream scan status")
        layout.Add(self.status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        buttons = wx.StdDialogButtonSizer()
        self.save_btn = wx.Button(self, wx.ID_OK, label="Sa&ve Station")
        cancel_btn = wx.Button(self, wx.ID_CANCEL)
        buttons.AddButton(self.save_btn)
        buttons.AddButton(cancel_btn)
        buttons.Realize()
        layout.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 12)
        self.SetSizerAndFit(layout)
        self.SetMinSize(self.GetSize())
        self.CentreOnParent()
        self.scan_btn.Bind(wx.EVT_BUTTON, self._on_scan)
        self.stop_btn.Bind(wx.EVT_BUTTON, self._on_stop_scan)
        self.results.Bind(wx.EVT_LISTBOX, self._on_selection)
        self.results.Bind(wx.EVT_LISTBOX_DCLICK, self._on_use)
        self.use_btn.Bind(wx.EVT_BUTTON, self._on_use)
        self.copy_btn.Bind(wx.EVT_BUTTON, self._on_copy)
        self.save_btn.Bind(wx.EVT_BUTTON, self._on_save)
        cancel_btn.Bind(wx.EVT_BUTTON, self._on_cancel)
        self.Bind(wx.EVT_CLOSE, self._on_cancel)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)
        self.name_ctrl.SetFocus()

    def station_values(self) -> tuple[str, str]:
        url = self.url_ctrl.GetValue().strip()
        return self.name_ctrl.GetValue().strip() or url, url

    def _on_scan(self, event):
        if self._scanning:
            return
        url = _http_url(self.page_ctrl.GetValue())
        if not url:
            self.status.SetValue("Enter a complete HTTP or HTTPS webpage URL before scanning.")
            self.page_ctrl.SetFocus()
            return
        self._scan_generation += 1
        generation = self._scan_generation
        self._scan_cancel = cancel = threading.Event()
        self._scanning = True
        self._streams = ()
        self.results.Clear()
        self._on_selection(None)
        self.scan_btn.Disable()
        self.stop_btn.Enable()
        self.page_ctrl.Disable()
        self.status.SetValue(
            "Scanning webpage and listen links. You can stop the scan at any time."
        )
        self.stop_btn.SetFocus()

        def worker():
            try:
                result = discover_streams(url, cancel=cancel)
            except Exception as exc:
                result = DiscoveryResult((), 0, error=str(exc))
            call_after_safe(self, self._finish_scan, generation, result)

        threading.Thread(target=worker, daemon=True, name="stream-finder").start()

    def _finish_scan(self, generation: int, result: DiscoveryResult):
        if self._closed or generation != self._scan_generation:
            return
        move_focus = self.FindFocus() is self.stop_btn
        self._scanning = False
        self.scan_btn.Enable()
        self.stop_btn.Disable()
        self.page_ctrl.Enable()
        self._streams = result.streams
        self.results.Set([f"{stream.format}: {stream.url}" for stream in self._streams])
        if self._streams:
            self.results.SetSelection(0)
            text = (
                f"Found {len(self._streams)} stream(s) "
                f"after checking {result.pages_checked} link(s). "
                "Use Selected Stream fills the stream address; Copy Stream URL copies it."
            )
            if result.limited:
                text += " The scan limit was reached; more links may be available."
        elif result.error:
            text = f"Could not read the webpage: {result.error}"
        else:
            text = (
                "No accessible audio stream found. The player may require JavaScript or a sign-in. "
                "Try the station's Listen Live page or a direct player link."
            )
            if result.limited:
                text += " The scan limit was reached."
        self.status.SetValue(text)
        self._on_selection(None)
        if move_focus:
            (self.results if self._streams else self.status).SetFocus()

    def _on_stop_scan(self, event):
        self._scan_cancel.set()
        self._scan_generation += 1
        self._scanning = False
        self.scan_btn.Enable()
        self.stop_btn.Disable()
        self.page_ctrl.Enable()
        self.status.SetValue("Scan stopped. You can scan another webpage or enter a stream URL.")
        self.scan_btn.SetFocus()

    def _selected(self):
        index = self.results.GetSelection()
        return self._streams[index] if 0 <= index < len(self._streams) else None

    def _on_selection(self, event):
        selected = self._selected() is not None
        self.use_btn.Enable(selected)
        self.copy_btn.Enable(selected)

    def _on_use(self, event):
        stream = self._selected()
        if stream:
            self.url_ctrl.SetValue(stream.url)
            self.url_ctrl.SetFocus()

    def _on_copy(self, event):
        stream = self._selected()
        if not stream:
            return
        if not wx.TheClipboard.Open():
            self.status.SetValue("The clipboard is busy. Try Copy Stream URL again.")
            return
        try:
            copied = wx.TheClipboard.SetData(wx.TextDataObject(stream.url))
            if copied:
                wx.TheClipboard.Flush()
        finally:
            wx.TheClipboard.Close()
        self.status.SetValue("Stream URL copied." if copied else "Could not copy the stream URL.")

    def _on_save(self, event):
        if not _http_url(self.url_ctrl.GetValue()):
            self.status.SetValue(
                "Enter a complete HTTP or HTTPS stream URL, or use a found stream."
            )
            self.url_ctrl.SetFocus()
            return
        self._closed = True
        self._scan_cancel.set()
        self.EndModal(wx.ID_OK)

    def _on_cancel(self, event):
        self._closed = True
        self._scan_cancel.set()
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)
        else:
            self.Destroy()

    def _on_destroy(self, event):
        if event.GetEventObject() is self:
            self._closed = True
            self._scan_cancel.set()
        event.Skip()
