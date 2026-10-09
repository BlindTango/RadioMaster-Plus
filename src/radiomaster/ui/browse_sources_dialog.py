"""Choose Browse Sources dialog: which station sources exist in the tree.

Borrowed from Quill Radio's "Choosing which branches exist": hiding a
source removes its branch from Browse Stations while everything else
stays exactly where it was -- and the change is spoken, not silent.
"""

from __future__ import annotations

import wx

from radiomaster.services.sources import SourceRegistry, describe_source
from radiomaster.utils.accessibility import set_accessible_name


class BrowseSourcesDialog(wx.Dialog):
    """Checkbox per source; OK persists, Cancel changes nothing."""

    def __init__(self, parent, registry: SourceRegistry):
        super().__init__(parent, title="Choose Browse Sources",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._registry = registry
        self._initial = set(registry.enabled_ids())

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        intro = wx.StaticText(
            panel,
            label="Choose which station sources appear in Browse Stations. "
                  "Hidden sources are gone from the tree; everything else stays put.",
        )
        intro.Wrap(440)
        sizer.Add(intro, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)

        self._checklist = wx.CheckListBox(panel)
        set_accessible_name(self._checklist, "Station sources")
        sources = registry.all_sources()
        for source in sources:
            # The row carries its own truth: offline or not, spoken in
            # the row rather than discovered after pressing. CheckListBox
            # has no second column, so the sentence rides in the label.
            self._checklist.Append(describe_source(source))
            self._checklist.Check(self._checklist.GetCount() - 1,
                                  source.id in self._initial)
        sizer.Add(self._checklist, 1, wx.EXPAND | wx.ALL, 10)

        buttons = self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL)
        sizer.Add(buttons, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        panel.SetSizer(sizer)
        self.SetClientSize(wx.Size(480, 360))
        self.Centre()
        self._checklist.SetFocus()

    def selected_ids(self) -> list[str]:
        """The source ids checked in the list (call after ShowModal OK)."""
        sources = self._registry.all_sources()
        return [
            source.id
            for index, source in enumerate(sources)
            if self._checklist.IsChecked(index)
        ]

    def changed(self) -> bool:
        """Whether the selection differs from what was enabled on open."""
        return set(self.selected_ids()) != self._initial