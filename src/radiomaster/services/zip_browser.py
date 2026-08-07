"""ZIP archive browser service for reading archive contents without extraction."""

import zipfile
import os
from typing import Any


class ZipBrowser:
    """Provides virtual file system access to ZIP archives."""

    def __init__(self) -> None:
        self._handles: dict[str, zipfile.ZipFile] = {}

    def open(self, zip_path: str) -> bool:
        """Open a ZIP archive for browsing."""
        try:
            zf = zipfile.ZipFile(zip_path, "r")
            self._handles[zip_path] = zf
            return True
        except (zipfile.BadZipFile, FileNotFoundError) as e:
            return False

    def close(self, zip_path: str) -> None:
        """Close a ZIP archive."""
        handle = self._handles.pop(zip_path, None)
        if handle:
            handle.close()

    def close_all(self) -> None:
        """Close all open ZIP archives."""
        for handle in self._handles.values():
            handle.close()
        self._handles.clear()

    def get_file_list(self, zip_path: str) -> list[dict[str, Any]]:
        """Get a flat list of all files in the archive."""
        handle = self._handles.get(zip_path)
        if not handle:
            return []
        files = []
        for info in handle.infolist():
            files.append({
                "name": info.filename,
                "size": info.file_size,
                "compressed_size": info.compress_size,
                "is_dir": info.is_dir(),
                "date_time": info.date_time,
            })
        return files

    def get_directory_tree(self, zip_path: str) -> list[dict[str, Any]]:
        """Get a hierarchical directory tree of the archive."""
        handle = self._handles.get(zip_path)
        if not handle:
            return []
        return self._build_tree(handle.namelist())

    def _build_tree(self, names: list[str]) -> list[dict[str, Any]]:
        """Build a nested directory tree from flat file list."""
        tree: dict[str, Any] = {"children": {}}
        for name in sorted(names):
            parts = name.strip("/").split("/")
            current = tree
            for i, part in enumerate(parts):
                is_last = (i == len(parts) - 1)
                if part not in current["children"]:
                    current["children"][part] = {
                        "name": part,
                        "is_dir": not is_last or name.endswith("/"),
                        "children": {},
                    }
                current = current["children"][part]
        return self._dict_to_list(tree["children"])

    def _dict_to_list(self, children: dict) -> list[dict[str, Any]]:
        """Convert children dict to sorted list."""
        result = []
        for name, data in sorted(children.items()):
            node = {
                "name": name,
                "is_dir": data["is_dir"],
            }
            if data["children"]:
                node["children"] = self._dict_to_list(data["children"])
            result.append(node)
        return result

    def extract_file(self, zip_path: str, file_name: str, output_dir: str) -> str | None:
        """Extract a single file from the archive."""
        handle = self._handles.get(zip_path)
        if not handle:
            return None
        try:
            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, os.path.basename(file_name))
            handle.extract(file_name, output_dir)
            return os.path.join(output_dir, file_name)
        except Exception:
            return None

    def read_file(self, zip_path: str, file_name: str) -> bytes | None:
        """Read a file's contents from the archive without extracting."""
        handle = self._handles.get(zip_path)
        if not handle:
            return None
        try:
            return handle.read(file_name)
        except Exception:
            return None

    def is_media_file(self, name: str) -> bool:
        """Check if a file in the archive is a supported media format."""
        ext = os.path.splitext(name)[1].lower()
        return ext in {
            ".mp3", ".flac", ".ogg", ".wav", ".aac", ".m4a", ".wma", ".opus",
            ".mp4", ".mkv", ".avi", ".webm", ".mov", ".m4b",
        }
