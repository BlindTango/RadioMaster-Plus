"""DAISY 2.02 and NISO 39.86 parser for audiobook navigation.

Beyond a list of chapter titles, the parser follows the book's own links:
a navigation entry (NCC heading / NCX navPoint / page marker) points at a SMIL
file, whose ``par`` elements name the audio file, the clip within it and the
text that is spoken. Each chapter and page therefore carries the audio file
and start offset to play, and the text to read.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any
from urllib.parse import unquote
from xml.etree import ElementTree as ET

logger = logging.getLogger("radiomaster")

_AUDIO_EXTS = (".mp3", ".wav", ".ogg", ".aac", ".mp4", ".m4a", ".opus", ".flac")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def parse_clock(value: str | None) -> float | None:
    """SMIL clip times: 'npt=12.5s', 'npt=0:01:02.500', '12.5s', '1500ms'."""
    if not value:
        return None
    v = value.strip().lower()
    if v.startswith("npt="):
        v = v[4:]
    try:
        if v.endswith("ms"):
            return float(v[:-2]) / 1000.0
        if v.endswith("s"):
            return float(v[:-1])
        if v.endswith("min"):
            return float(v[:-3]) * 60.0
        if v.endswith("h"):
            return float(v[:-1]) * 3600.0
        if ":" in v:
            total = 0.0
            for part in v.split(":"):
                total = total * 60.0 + float(part)
            return total
        return float(v)
    except ValueError:
        return None


def _split_ref(ref: str) -> tuple[str, str]:
    path, _, frag = ref.partition("#")
    return unquote(path), frag


class _Smil:
    """The par elements of one SMIL file, indexed by id (of the par itself
    and of its text/audio children)."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.base = os.path.dirname(path)
        self.pars: dict[str, dict[str, Any]] = {}
        self.order: list[dict[str, Any]] = []
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError):
            return
        for par in root.iter():
            if _local(par.tag) != "par":
                continue
            entry: dict[str, Any] = {"audio": None, "begin": 0.0, "end": None, "text_ref": None}
            for child in par.iter():
                kind = _local(child.tag)
                if kind == "audio" and entry["audio"] is None:
                    src = child.get("src")
                    if src:
                        entry["audio"] = os.path.normpath(
                            os.path.join(self.base, _split_ref(src)[0]))
                        entry["begin"] = parse_clock(
                            child.get("clip-begin") or child.get("clipBegin")) or 0.0
                        entry["end"] = parse_clock(
                            child.get("clip-end") or child.get("clipEnd"))
                elif kind == "text" and entry["text_ref"] is None:
                    src = child.get("src")
                    if src:
                        entry["text_ref"] = src
            self.order.append(entry)
            for ident in {par.get("id")} | {c.get("id") for c in par.iter()}:
                if ident:
                    self.pars.setdefault(ident, entry)


class _TextSources:
    """Looks up the text a SMIL ``text src="file#id"`` points at, in either
    an HTML (DAISY 2.02) or XML (DTBook) content file."""

    def __init__(self, base: str) -> None:
        self.base = base
        self._cache: dict[str, dict[str, str]] = {}

    def _load(self, path: str) -> dict[str, str]:
        if path in self._cache:
            return self._cache[path]
        texts: dict[str, str] = {}
        try:
            if path.lower().endswith((".htm", ".html")):
                from bs4 import BeautifulSoup
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    soup = BeautifulSoup(fh.read(), "html.parser")
                for el in soup.find_all(id=True):
                    texts[el["id"]] = " ".join(el.get_text(" ", strip=True).split())
            else:
                root = ET.parse(path).getroot()
                for el in root.iter():
                    ident = el.get("id")
                    if ident:
                        texts[ident] = " ".join("".join(el.itertext()).split())
        except Exception as exc:  # unreadable text file: audio still works
            logger.debug("DAISY text file %s unreadable: %s", path, exc)
        self._cache[path] = texts
        return texts

    def get(self, smil: _Smil, ref: str | None) -> str:
        if not ref:
            return ""
        rel, frag = _split_ref(ref)
        path = os.path.normpath(os.path.join(smil.base, rel))
        texts = self._load(path)
        return texts.get(frag, "") if frag else ""


def _resolve_target(book_dir: str, ref: str, smils: dict[str, _Smil],
                    texts: _TextSources) -> dict[str, Any]:
    """Follow ``file.smil#id`` into the SMIL; returns audio/start/end/text."""
    out: dict[str, Any] = {"audio": None, "start": 0.0, "end": None, "text": ""}
    rel, frag = _split_ref(ref)
    path = os.path.normpath(os.path.join(book_dir, rel))
    if not path.lower().endswith(".smil"):
        return out
    smil = smils.get(path)
    if smil is None:
        smil = smils[path] = _Smil(path)
    entry = smil.pars.get(frag) if frag else (smil.order[0] if smil.order else None)
    if entry is None:
        return out
    out["audio"] = entry["audio"]
    out["start"] = entry["begin"]
    out["end"] = entry["end"]
    out["text"] = texts.get(smil, entry["text_ref"])
    return out


def _chapter_text(chapter: dict[str, Any], smils: dict[str, _Smil],
                  texts: _TextSources) -> str:
    """Text for a whole chapter: every par in the chapter's SMIL file from the
    chapter's own par to the next chapter's (or the end of the file)."""
    smil = chapter.get("_smil")
    start = chapter.get("_entry")
    if smil is None or start is None:
        return chapter.get("text", "")
    try:
        first = smil.order.index(start)
    except ValueError:
        return chapter.get("text", "")
    stop = chapter.get("_stop_entry")
    try:
        last = smil.order.index(stop) if stop is not None else len(smil.order)
    except ValueError:
        last = len(smil.order)
    parts = [texts.get(smil, e["text_ref"]) for e in smil.order[first:max(first + 1, last)]]
    return "\n".join(p for p in parts if p)


def _chapter_duration(chapter: dict[str, Any]) -> float | None:
    """Seconds from the chapter's start to the end of its last clip in the
    same audio file, or None when the clips do not say."""
    smil, first, stop = chapter.get("_smil"), chapter.get("_entry"), chapter.get("_stop_entry")
    if smil is None or first is None:
        return None
    try:
        lo = smil.order.index(first)
        hi = smil.order.index(stop) if stop is not None else len(smil.order)
    except ValueError:
        return None
    ends = [e["end"] for e in smil.order[lo:max(lo + 1, hi)]
            if e["audio"] == first["audio"] and e["end"] is not None]
    if not ends:
        return None
    return max(0.0, max(ends) - (first["begin"] or 0.0))


class DaisyParser:
    """Parses DAISY 2.02 and NISO 39.86 (DAISY 3) book structures."""

    @staticmethod
    def detect_format(folder_path: str) -> str | None:
        """Detect the DAISY format in a folder."""
        files = os.listdir(folder_path)
        if "ncc.html" in files:
            return "daisy2"
        if "master.smil" in files:
            return "daisy2"
        if any(f.endswith(".opf") for f in files):
            return "daisy3"
        return None

    # ------------------------------------------------------------------
    @staticmethod
    def _audio_files(folder_path: str) -> list[str]:
        return [os.path.join(folder_path, f) for f in sorted(os.listdir(folder_path), key=str.casefold)
                if f.lower().endswith(_AUDIO_EXTS)]

    @staticmethod
    def _attach_targets(book: dict[str, Any], folder_path: str, items: list[dict[str, Any]],
                        smils: dict[str, _Smil], texts: _TextSources, key: str) -> None:
        """Fill audio/start/end/text on chapters or pages from their refs."""
        for item in items:
            ref = item.pop("_ref", None)
            if not ref:
                continue
            target = _resolve_target(folder_path, ref, smils, texts)
            item.update({k: v for k, v in target.items()})
            rel, frag = _split_ref(ref)
            smil = smils.get(os.path.normpath(os.path.join(folder_path, rel)))
            if smil is not None:
                item["_smil"] = smil
                item["_entry"] = smil.pars.get(frag) if frag else None

    @staticmethod
    def _finish_chapters(chapters: list[dict[str, Any]], smils: dict[str, _Smil],
                         texts: _TextSources) -> None:
        # A chapter's text runs up to the next chapter in the same SMIL file.
        for i, ch in enumerate(chapters):
            nxt = chapters[i + 1] if i + 1 < len(chapters) else None
            if nxt and nxt.get("_smil") is ch.get("_smil"):
                ch["_stop_entry"] = nxt.get("_entry")
            if ch.get("_smil") is not None and ch.get("_entry") is not None:
                ch["text"] = _chapter_text(ch, smils, texts) or ch.get("text", "")
                ch["duration"] = _chapter_duration(ch)
        for ch in chapters:
            for k in ("_smil", "_entry", "_stop_entry"):
                ch.pop(k, None)

    # ------------------------------------------------------------------
    @staticmethod
    def parse_daisy2(folder_path: str) -> dict[str, Any] | None:
        """Parse a DAISY 2.02 book structure."""
        try:
            ncc_path = os.path.join(folder_path, "ncc.html")
            if not os.path.exists(ncc_path):
                smil_files = [f for f in os.listdir(folder_path) if f.endswith(".smil")]
                if not smil_files:
                    return None
                ncc_path = os.path.join(folder_path, smil_files[0])

            from bs4 import BeautifulSoup
            with open(ncc_path, "r", encoding="utf-8", errors="replace") as f:
                soup = BeautifulSoup(f.read(), "html.parser")

            book: dict[str, Any] = {
                "title": "", "author": "", "publisher": "", "format": "daisy2",
                "total_time": 0, "chapters": [], "pages": [], "audio_files": [],
            }
            title_tag = soup.find("title")
            if title_tag:
                book["title"] = title_tag.get_text(strip=True)
            for meta in soup.find_all("meta"):
                name = (meta.get("name") or "").lower()
                if name == "dc:creator" and not book["author"]:
                    book["author"] = meta.get("content", "")
                elif name == "dc:publisher" and not book["publisher"]:
                    book["publisher"] = meta.get("content", "")

            smils: dict[str, _Smil] = {}
            texts = _TextSources(folder_path)
            body = soup.body or soup
            for el in body.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "span", "div"]):
                link = el.find("a", href=True)
                if link is None:
                    continue
                label = link.get_text(" ", strip=True)
                if el.name and el.name[0] == "h" and len(el.name) == 2:
                    if label:
                        book["chapters"].append({
                            "title": label, "level": int(el.name[1]), "_ref": link["href"]})
                else:
                    classes = " ".join(el.get("class") or []).lower()
                    if "page-" in classes and label:
                        book["pages"].append({"label": label, "_ref": link["href"]})

            DaisyParser._attach_targets(book, folder_path, book["chapters"], smils, texts, "chapters")
            DaisyParser._attach_targets(book, folder_path, book["pages"], smils, texts, "pages")
            DaisyParser._finish_chapters(book["chapters"], smils, texts)
            for page in book["pages"]:
                for k in ("_smil", "_entry"):
                    page.pop(k, None)

            book["audio_files"] = DaisyParser._audio_files(folder_path)
            if not book["chapters"]:
                # Older fallback: navPoint list items with no links we can follow.
                for point in soup.find_all("li", class_="navPoint"):
                    text = point.get_text(strip=True)
                    if text:
                        book["chapters"].append({"title": text, "level": 1})
            return book
        except Exception as e:
            logger.error(f"Failed to parse DAISY 2.02: {e}")
            return None

    @staticmethod
    def parse_daisy3(folder_path: str) -> dict[str, Any] | None:
        """Parse a DAISY 3 / NISO 39.86 book structure."""
        try:
            opf_files = [f for f in os.listdir(folder_path) if f.endswith(".opf")]
            if not opf_files:
                return None
            opf_path = os.path.join(folder_path, opf_files[0])
            root = ET.parse(opf_path).getroot()

            book: dict[str, Any] = {
                "title": "", "author": "", "publisher": "", "format": "daisy3",
                "total_time": 0, "chapters": [], "pages": [], "audio_files": [],
            }
            for el in root.iter():
                name = _local(el.tag)
                if name == "title" and not book["title"]:
                    book["title"] = (el.text or "").strip()
                elif name == "creator" and not book["author"]:
                    book["author"] = (el.text or "").strip()
                elif name == "publisher" and not book["publisher"]:
                    book["publisher"] = (el.text or "").strip()

            # The NCX is named in the OPF manifest; fall back to any .ncx file.
            ncx_name = None
            for el in root.iter():
                if _local(el.tag) == "item" and (el.get("media-type") or "") == "application/x-dtbncx+xml":
                    ncx_name = _split_ref(el.get("href") or "")[0]
                    break
            if ncx_name is None:
                ncx_name = next((f for f in os.listdir(folder_path) if f.lower().endswith(".ncx")), None)

            smils: dict[str, _Smil] = {}
            texts = _TextSources(folder_path)
            if ncx_name and os.path.exists(os.path.join(folder_path, ncx_name)):
                ncx = ET.parse(os.path.join(folder_path, ncx_name)).getroot()

                def label_of(node: ET.Element) -> str:
                    for sub in node.iter():
                        if _local(sub.tag) == "text" and (sub.text or "").strip():
                            return " ".join(sub.text.split())
                    return ""

                def content_of(node: ET.Element) -> str:
                    for sub in node:
                        if _local(sub.tag) == "content":
                            return sub.get("src", "")
                    return ""

                def walk(node: ET.Element, level: int) -> None:
                    for child in node:
                        if _local(child.tag) == "navpoint":
                            book["chapters"].append({
                                "title": label_of(child) or f"Section {len(book['chapters']) + 1}",
                                "level": level, "_ref": content_of(child)})
                            walk(child, level + 1)

                for node in ncx.iter():
                    kind = _local(node.tag)
                    if kind == "navmap":
                        walk(node, 1)
                    elif kind == "pagetarget":
                        label = (node.get("value") or "").strip() or label_of(node)
                        if label:
                            book["pages"].append({"label": label, "_ref": content_of(node)})

            DaisyParser._attach_targets(book, folder_path, book["chapters"], smils, texts, "chapters")
            DaisyParser._attach_targets(book, folder_path, book["pages"], smils, texts, "pages")
            DaisyParser._finish_chapters(book["chapters"], smils, texts)
            for page in book["pages"]:
                for k in ("_smil", "_entry"):
                    page.pop(k, None)

            book["audio_files"] = DaisyParser._audio_files(folder_path)
            return book
        except Exception as e:
            logger.error(f"Failed to parse DAISY 3: {e}")
            return None

    @staticmethod
    def parse(folder_path: str) -> dict[str, Any] | None:
        """Auto-detect and parse a DAISY book."""
        fmt = DaisyParser.detect_format(folder_path)
        if fmt == "daisy2":
            return DaisyParser.parse_daisy2(folder_path)
        elif fmt == "daisy3":
            return DaisyParser.parse_daisy3(folder_path)
        return None
