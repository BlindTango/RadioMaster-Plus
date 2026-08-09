"""File tree browser with folder, file, and ZIP archive support."""

import os
import zipfile
import wx
from typing import Any
from radiomaster.utils.accessibility import set_accessible_name


class FileTreePanel(wx.Panel):
    """Tree view for browsing folders, files, and ZIP archives."""

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent)
        self._current_root: str = ""
        self._zip_handles: dict[str, zipfile.ZipFile] = {}
        self._on_file_selected_cb: Any = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Create the tree view and buttons."""
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Tree control
        self._tree = wx.TreeCtrl(self, style=wx.TR_DEFAULT_STYLE | wx.TR_HIDE_ROOT)
        set_accessible_name(self._tree, "File Browser Tree")
        self._root = self._tree.AddRoot("My Computer")
        sizer.Add(self._tree, 1, wx.EXPAND)

        # Button row
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self._btn_browse = wx.Button(self, label="Browse Folder...")
        set_accessible_name(self._btn_browse, "Browse Folder")
        btn_sizer.Add(self._btn_browse, 0, wx.RIGHT, 4)

        self._btn_open = wx.Button(self, label="Open File...")
        set_accessible_name(self._btn_open, "Open File")
        btn_sizer.Add(self._btn_open, 0, wx.RIGHT, 4)

        self._btn_open_zip = wx.Button(self, label="Open Archive...")
        set_accessible_name(self._btn_open_zip, "Open Archive")
        btn_sizer.Add(self._btn_open_zip, 0)

        sizer.Add(btn_sizer, 0, wx.EXPAND | wx.TOP, 4)

        self.SetSizer(sizer)

        # Bind events
        self._btn_browse.Bind(wx.EVT_BUTTON, self._on_browse)
        self._btn_open.Bind(wx.EVT_BUTTON, self._on_open_file)
        self._btn_open_zip.Bind(wx.EVT_BUTTON, self._on_open_zip)
        self._tree.Bind(wx.EVT_TREE_ITEM_EXPANDING, self._on_tree_expand)

    def _on_browse(self, event: wx.CommandEvent) -> None:
        """Browse for a folder to show in the tree."""
        dlg = wx.DirDialog(self, "Choose a folder", style=wx.DD_DEFAULT_STYLE)
        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            self._current_root = path
            self._populate_folder(path)
        dlg.Destroy()

    def _on_open_file(self, event: wx.CommandEvent) -> None:
        """Open a file dialog for media files."""
        wildcard = (
            "All supported files|*.mp3;*.flac;*.ogg;*.wav;*.aac;*.m4a;*.wma;*.opus;"
            "*.mp4;*.mkv;*.avi;*.webm;*.mov;*.m4b;*.pls;*.m3u"
            "|Audio files|*.mp3;*.flac;*.ogg;*.wav;*.aac;*.m4a;*.wma;*.opus"
            "|Video files|*.mp4;*.mkv;*.avi;*.webm;*.mov"
            "|Playlists|*.pls;*.m3u"
            "|All files|*.*"
        )
        dlg = wx.FileDialog(self, "Open media file", wildcard=wildcard,
                            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            if self._on_file_selected_cb:
                self._on_file_selected_cb(path)
        dlg.Destroy()

    def _on_open_zip(self, event: wx.CommandEvent) -> None:
        """Open a ZIP archive and show its contents in the tree."""
        dlg = wx.FileDialog(self, "Open ZIP archive", wildcard="ZIP files (*.zip)|*.zip",
                            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            self._add_zip_to_tree(path)
        dlg.Destroy()

    def _on_tree_expand(self, event: wx.TreeEvent) -> None:
        """Handle tree expansion to lazily load children."""
        item = event.GetItem()
        data = self._tree.GetItemData(item)
        if data and isinstance(data, dict) and data.get("type") == "folder":
            path = data.get("path", "")
            # GetChildrenCount, not ItemHasChildren -- ItemHasChildren can
            # reflect the same "show an expand arrow" hint
            # SetItemHasChildren() sets (see _populate_children), which
            # would already read True the very first time this fires,
            # before any real children have actually been added -- that
            # skipped populating entirely, so expanding a subfolder
            # looked like it opened but stayed empty. Checking the real
            # child count is what the lazy-loading idiom actually needs.
            if path and self._tree.GetChildrenCount(item, False) == 0:
                self._populate_children(item, path)

    def _populate_folder(self, path: str) -> None:
        """Populate the tree with a folder's contents."""
        self._tree.DeleteChildren(self._root)
        item = self._tree.AppendItem(self._root, os.path.basename(path) or path)
        self._tree.SetItemData(item, {"type": "folder", "path": path})
        self._populate_children(item, path)
        self._tree.Expand(item)

    def _populate_children(self, parent_item: wx.TreeItemId, path: str) -> None:
        """Populate child items for a folder."""
        try:
            for entry in sorted(os.listdir(path)):
                full_path = os.path.join(path, entry)
                if os.path.isdir(full_path):
                    child = self._tree.AppendItem(parent_item, f"📁 {entry}")
                    self._tree.SetItemData(child, {"type": "folder", "path": full_path})
                    # Without this, wx.TreeCtrl has no way to know this
                    # item might have children until they're actually
                    # added -- since children are only added lazily, on
                    # EVT_TREE_ITEM_EXPANDING (see _on_tree_expand), that
                    # event never fires at all for a subfolder: no expand
                    # arrow is drawn, Right/Enter on it does nothing.
                    # Every subfolder past the first browsed level was a
                    # dead end -- unnavigable for anyone, and especially
                    # unreadable for a screen reader (NVDA announces a
                    # plain, non-expandable item instead of "collapsed").
                    self._tree.SetItemHasChildren(child, True)
                elif entry.lower().endswith(".zip"):
                    child = self._tree.AppendItem(parent_item, f"📦 {entry}")
                    self._tree.SetItemData(child, {"type": "zip", "path": full_path})
                elif self._is_media_file(entry):
                    child = self._tree.AppendItem(parent_item, entry)
                    self._tree.SetItemData(child, {"type": "file", "path": full_path})
        except PermissionError:
            pass

    def _add_zip_to_tree(self, zip_path: str) -> None:
        """Add a ZIP archive as an expandable tree node."""
        try:
            zf = zipfile.ZipFile(zip_path, "r")
            self._zip_handles[zip_path] = zf
            item = self._tree.AppendItem(self._root, f"📦 {os.path.basename(zip_path)}")
            self._tree.SetItemData(item, {"type": "zip", "path": zip_path})

            # Build virtual folder structure
            names = zf.namelist()
            dirs: dict[str, wx.TreeItemId] = {}
            for name in sorted(names):
                parts = name.strip("/").split("/")
                if len(parts) == 1:
                    if name.endswith("/"):
                        child = self._tree.AppendItem(item, f"📁 {name.strip('/')}")
                        dirs[name] = child
                    else:
                        self._tree.AppendItem(item, name)
                else:
                    # Create nested structure
                    current = item
                    for i, part in enumerate(parts):
                        path_so_far = "/".join(parts[: i + 1])
                        if i < len(parts) - 1 or name.endswith("/"):
                            if path_so_far not in dirs:
                                dirs[path_so_far] = self._tree.AppendItem(
                                    current, f"📁 {part}"
                                )
                            current = dirs[path_so_far]
                        else:
                            self._tree.AppendItem(current, part)
            self._tree.Expand(item)
        except zipfile.BadZipFile:
            wx.MessageBox("Invalid ZIP file", "Error", wx.OK | wx.ICON_ERROR)

    def _is_media_file(self, filename: str) -> bool:
        """Check if a file is a supported media format."""
        ext = os.path.splitext(filename)[1].lower()
        return ext in {
            ".mp3", ".flac", ".ogg", ".wav", ".aac", ".m4a", ".wma", ".opus",
            ".mp4", ".mkv", ".avi", ".webm", ".mov", ".m4b",
            ".pls", ".m3u",
        }

    def get_selected_path(self) -> str | None:
        """Get the path of the selected tree item."""
        item = self._tree.GetSelection()
        if item and item.IsOk():
            data = self._tree.GetItemData(item)
            if data and isinstance(data, dict):
                return data.get("path")
        return None

    def get_selected_type(self) -> str | None:
        """Get the type of the selected item."""
        item = self._tree.GetSelection()
        if item and item.IsOk():
            data = self._tree.GetItemData(item)
            if data and isinstance(data, dict):
                return data.get("type")
        return None

    def on_file_selected(self, cb: Any) -> None:
        """Set callback for when a file is selected via Open File dialog."""
        self._on_file_selected_cb = cb

    def cleanup(self) -> None:
        """Close all open ZIP handles."""
        for zf in self._zip_handles.values():
            zf.close()
        self._zip_handles.clear()
