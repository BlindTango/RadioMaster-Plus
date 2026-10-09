"""Continue Listening: every unfinished thing, across content types.

Borrowed from Quill Radio's Continue Listening: RadioMaster+ already
remembers where you were in a podcast episode, an audiobook, and a local
file -- but only one type at a time, each behind its own prompt. This
service gathers them into one newest-first list so "what was I in the
middle of?" has one answer.

Missing files are quietly absent (a moved or deleted file is not
unfinished business), and the empty case is the caller's to speak in its
own sentence -- never a silent empty dialog.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


#: Positions under this many seconds are "I just started it" noise, not
#: something worth resuming -- Quill uses the same threshold idea.
MIN_POSITION_SECONDS = 30.0


@dataclass
class ContinueItem:
    """One unfinished thing, normalized across content types."""

    kind: str          # "podcast episode" | "audiobook" | "media file"
    title: str
    parent: str        # show name / book author / album -- "" when none
    position: float    # seconds in
    duration: float    # seconds total (0 when unknown)
    source_type: str   # repository discriminator: episode|audiobook|media
    source_id: int     # the owning table's row id
    file_path: str     # "" when the item is a stream, not a file


class ContinueListeningService:
    """Queries across episodes, audiobooks, and media files."""

    def __init__(self, db):
        self._db = db

    def items(self, limit: int = 50) -> list[ContinueItem]:
        """Unfinished things, newest activity first. A row's "activity"
        is its created_at/last-updated timestamp; SQLite's MAX over the
        three tables orders the merged list."""
        results: list[tuple[str, ContinueItem]] = []
        results.extend(self._episodes())
        results.extend(self._audiobooks())
        results.extend(self._media_files())
        results.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _stamp, item in results[:limit]]

    def _episodes(self) -> list[tuple[str, ContinueItem]]:
        rows = self._db.fetchall(
            "SELECT e.id, e.title, e.play_position, e.file_path, e.created_at, "
            "p.title AS show_title "
            "FROM episodes e JOIN podcasts p ON p.id = e.podcast_id "
            "WHERE e.is_played = 0 AND e.play_position > ? "
            "ORDER BY e.created_at DESC",
            (MIN_POSITION_SECONDS,),
        )
        out = []
        for row in rows:
            data = dict(row)
            path = data.get("file_path") or ""
            if path and not os.path.exists(path):
                continue  # quietly absent -- see the module docstring
            out.append((data.get("created_at") or "", ContinueItem(
                kind="podcast episode",
                title=data.get("title") or "Untitled episode",
                parent=data.get("show_title") or "",
                position=float(data.get("play_position") or 0),
                duration=0.0,
                source_type="episode",
                source_id=int(data.get("id") or 0),
                file_path=path,
            )))
        return out

    def _audiobooks(self) -> list[tuple[str, ContinueItem]]:
        rows = self._db.fetchall(
            "SELECT id, title, author, last_position, duration, file_path, "
            "folder_path, created_at FROM audiobooks "
            "WHERE last_position > ? ORDER BY created_at DESC",
            (MIN_POSITION_SECONDS,),
        )
        out = []
        for row in rows:
            data = dict(row)
            path = data.get("file_path") or ""
            folder = data.get("folder_path") or ""
            if path and not os.path.exists(path):
                continue
            if not path and folder and not os.path.isdir(folder):
                continue
            out.append((data.get("created_at") or "", ContinueItem(
                kind="audiobook",
                title=data.get("title") or "Untitled book",
                parent=data.get("author") or "",
                position=float(data.get("last_position") or 0),
                duration=float(data.get("duration") or 0),
                source_type="audiobook",
                source_id=int(data.get("id") or 0),
                file_path=path or folder,
            )))
        return out

    def _media_files(self) -> list[tuple[str, ContinueItem]]:
        rows = self._db.fetchall(
            "SELECT id, title, artist, album, last_position, duration, "
            "file_path, created_at FROM media_files "
            "WHERE last_position > ? ORDER BY created_at DESC",
            (MIN_POSITION_SECONDS,),
        )
        out = []
        for row in rows:
            data = dict(row)
            path = data.get("file_path") or ""
            if path and not os.path.exists(path):
                continue
            out.append((data.get("created_at") or "", ContinueItem(
                kind="media file",
                title=data.get("title") or os.path.basename(path) or "Untitled",
                parent=data.get("artist") or data.get("album") or "",
                position=float(data.get("last_position") or 0),
                duration=float(data.get("duration") or 0),
                source_type="media",
                source_id=int(data.get("id") or 0),
                file_path=path,
            )))
        return out

    def forget(self, item: ContinueItem) -> None:
        """Zero the position and (for episodes) mark unplayed. The file
        itself is never touched."""
        if item.source_type == "episode":
            self._db.execute(
                "UPDATE episodes SET play_position = 0, is_played = 0 "
                "WHERE id = ?", (item.source_id,))
        elif item.source_type == "audiobook":
            self._db.execute(
                "UPDATE audiobooks SET last_position = 0 WHERE id = ?",
                (item.source_id,))
        elif item.source_type == "media":
            self._db.execute(
                "UPDATE media_files SET last_position = 0 WHERE id = ?",
                (item.source_id,))
        if hasattr(self._db, "commit"):
            self._db.commit()

    @staticmethod
    def describe_position(position: float, duration: float) -> str:
        """"12 of 45 minutes" -- words, never a bare 12:34."""
        def _minutes(seconds: float) -> int:
            return max(0, int(round(seconds / 60)))
        if duration > 0:
            return (f"{_minutes(position)} of {_minutes(duration)} minutes")
        total = int(position)
        hours, remainder = divmod(total, 3600)
        minutes = remainder // 60
        if hours:
            return f"{hours} hour{'s' if hours != 1 else ''} {minutes} minute{'s' if minutes != 1 else ''}"
        return f"{minutes} minute{'s' if minutes != 1 else ''}"

    @staticmethod
    def summary_sentence(items: list[ContinueItem]) -> str:
        """The opening announcement: what's waiting, by kind."""
        if not items:
            return "Nothing is waiting to be continued."
        kinds = sorted({item.kind for item in items})
        noun = "thing" if len(items) == 1 else "things"
        return (f"{len(items)} {noun} you did not finish, "
                f"across {', '.join(kinds)}.")