"""Track Splitter dialog: split a mixed recording into tracks and rename them.

Wires together two services that previously had no UI entry point anywhere
in the app: TrackSplitter (silence/chapter-based splitting) and Renamer
(template-based filename rendering).
"""

from __future__ import annotations

import os
import threading

import wx

from radiomaster.services.track_splitter import TrackSplitter
from radiomaster.services.renamer import Renamer
from radiomaster.utils.accessibility import set_accessible_name


class TrackSplitterDialog(wx.Dialog):
    """Dialog to split an audio file into tracks and rename the results."""

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent, title="Track Splitter", size=(520, 420),
                          style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._output_files: list[str] = []
        self._setup_ui()
        self.Centre(wx.BOTH)

    def _setup_ui(self) -> None:
        sizer = wx.BoxSizer(wx.VERTICAL)

        sizer.Add(wx.StaticText(self, label="Source Audio File:"), 0, wx.ALL, 5)
        src_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self._source_txt = wx.TextCtrl(self)
        set_accessible_name(self._source_txt, "Source Audio File")
        src_sizer.Add(self._source_txt, 1, wx.EXPAND)
        btn_browse_src = wx.Button(self, label="Browse...")
        set_accessible_name(btn_browse_src, "Browse For Source File")
        btn_browse_src.Bind(wx.EVT_BUTTON, self._on_browse_source)
        src_sizer.Add(btn_browse_src, 0, wx.LEFT, 4)
        sizer.Add(src_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        sizer.Add(wx.StaticText(self, label="Output Folder:"), 0, wx.ALL, 5)
        out_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self._output_txt = wx.TextCtrl(self)
        set_accessible_name(self._output_txt, "Output Folder")
        out_sizer.Add(self._output_txt, 1, wx.EXPAND)
        btn_browse_out = wx.Button(self, label="Browse...")
        set_accessible_name(btn_browse_out, "Browse For Output Folder")
        btn_browse_out.Bind(wx.EVT_BUTTON, self._on_browse_output)
        out_sizer.Add(btn_browse_out, 0, wx.LEFT, 4)
        sizer.Add(out_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        sizer.Add(wx.StaticText(self, label="Split Method:"), 0, wx.ALL, 5)
        self._method_choice = wx.Choice(self, choices=["Silence Detection", "Chapter Markers"])
        self._method_choice.SetSelection(0)
        set_accessible_name(self._method_choice, "Split Method")
        sizer.Add(self._method_choice, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        sizer.Add(
            wx.StaticText(self, label="Filename Template (placeholders: {prefix} {index} {title}):"),
            0, wx.ALL, 5,
        )
        self._template_txt = wx.TextCtrl(self, value="{prefix} {index:02d}")
        set_accessible_name(self._template_txt, "Filename Template")
        sizer.Add(self._template_txt, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        self._btn_split = wx.Button(self, label="Split")
        set_accessible_name(self._btn_split, "Split Track")
        self._btn_split.Bind(wx.EVT_BUTTON, self._on_split)
        sizer.Add(self._btn_split, 0, wx.ALL, 5)

        self._status_txt = wx.TextCtrl(
            self, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 150),
        )
        set_accessible_name(self._status_txt, "Split Status")
        sizer.Add(self._status_txt, 1, wx.EXPAND | wx.ALL, 5)

        btn_close = wx.Button(self, wx.ID_CLOSE, "Close")
        btn_close.Bind(wx.EVT_BUTTON, lambda e: self.Close())
        sizer.Add(btn_close, 0, wx.ALIGN_RIGHT | wx.ALL, 5)

        self.SetSizer(sizer)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)

    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.Close()
        else:
            event.Skip()

    def _on_browse_source(self, event: wx.CommandEvent) -> None:
        dlg = wx.FileDialog(
            self, "Select audio file to split",
            wildcard="Audio files|*.mp3;*.flac;*.wav;*.m4a;*.ogg|All files|*.*",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        )
        if dlg.ShowModal() == wx.ID_OK:
            self._source_txt.SetValue(dlg.GetPath())
            if not self._output_txt.GetValue():
                self._output_txt.SetValue(
                    os.path.join(os.path.dirname(dlg.GetPath()), "split_tracks")
                )
        dlg.Destroy()

    def _on_browse_output(self, event: wx.CommandEvent) -> None:
        dlg = wx.DirDialog(self, "Choose output folder")
        if dlg.ShowModal() == wx.ID_OK:
            self._output_txt.SetValue(dlg.GetPath())
        dlg.Destroy()

    def _log(self, message: str) -> None:
        self._status_txt.AppendText(message + "\n")

    def _on_split(self, event: wx.CommandEvent) -> None:
        source = self._source_txt.GetValue().strip()
        output_dir = self._output_txt.GetValue().strip()
        if not source or not os.path.isfile(source):
            wx.MessageBox("Please select a valid source audio file.", "No Source File",
                          wx.OK | wx.ICON_WARNING)
            return
        if not output_dir:
            wx.MessageBox("Please choose an output folder.", "No Output Folder",
                          wx.OK | wx.ICON_WARNING)
            return

        by_chapters = self._method_choice.GetSelection() == 1
        template = self._template_txt.GetValue().strip() or "{prefix} {index:02d}"

        self._btn_split.Disable()
        self._status_txt.SetValue("")
        self._log(f"Splitting {os.path.basename(source)} by "
                  f"{'chapter markers' if by_chapters else 'silence detection'}...")

        def worker() -> None:
            if by_chapters:
                files = TrackSplitter.split_by_chapters(source, output_dir)
            else:
                files = TrackSplitter.split_by_silence(source, output_dir)

            if not files:
                wx.CallAfter(self._log, "No tracks were produced (no silence/chapter "
                                        "boundaries found, or splitting failed).")
                wx.CallAfter(self._btn_split.Enable)
                return

            wx.CallAfter(self._log, f"Split into {len(files)} track(s). Renaming...")
            renamed = []
            for i, path in enumerate(files):
                ext = os.path.splitext(path)[1]
                base_title = os.path.splitext(os.path.basename(path))[0]
                try:
                    new_name = Renamer.render(
                        template,
                        {"prefix": os.path.splitext(os.path.basename(source))[0],
                         "index": i + 1, "title": base_title},
                    )
                except Exception:
                    new_name = base_title
                new_name = "".join(c for c in new_name if c not in '<>:"/\\|?*') + ext
                new_path = os.path.join(os.path.dirname(path), new_name)
                try:
                    if new_path != path:
                        os.replace(path, new_path)
                    renamed.append(new_path)
                    wx.CallAfter(self._log, f"  {os.path.basename(new_path)}")
                except OSError as e:
                    renamed.append(path)
                    wx.CallAfter(self._log, f"  (rename failed for {path}: {e})")

            self._output_files = renamed
            wx.CallAfter(self._log, "Done.")
            wx.CallAfter(self._btn_split.Enable)

        threading.Thread(target=worker, daemon=True).start()
