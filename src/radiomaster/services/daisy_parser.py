"""DAISY 2.02 and NISO 39.86 parser for audiobook navigation."""

import os
import logging
import re
from typing import Any
from xml.etree import ElementTree as ET

logger = logging.getLogger("radiomaster")


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

    @staticmethod
    def parse_daisy2(folder_path: str) -> dict[str, Any] | None:
        """Parse a DAISY 2.02 book structure."""
        try:
            ncc_path = os.path.join(folder_path, "ncc.html")
            if not os.path.exists(ncc_path):
                # Try to find master.smil
                smil_files = [f for f in os.listdir(folder_path) if f.endswith(".smil")]
                if not smil_files:
                    return None
                ncc_path = os.path.join(folder_path, smil_files[0])

            from bs4 import BeautifulSoup
            with open(ncc_path, "r", encoding="utf-8", errors="replace") as f:
                soup = BeautifulSoup(f.read(), "html.parser")

            book: dict[str, Any] = {
                "title": "",
                "author": "",
                "publisher": "",
                "format": "daisy2",
                "total_time": 0,
                "chapters": [],
                "audio_files": [],
            }

            # Extract metadata
            title_tag = soup.find("title")
            if title_tag:
                book["title"] = title_tag.get_text(strip=True)

            # Extract chapters from navigation
            nav_points = soup.find_all("li", class_="navPoint")
            for point in nav_points:
                text = point.get_text(strip=True)
                if text:
                    book["chapters"].append({"title": text, "level": 1})

            # Find audio files
            for audio_ext in (".mp3", ".wav", ".ogg", ".aac"):
                for f in os.listdir(folder_path):
                    if f.endswith(audio_ext):
                        book["audio_files"].append(os.path.join(folder_path, f))

            return book

        except Exception as e:
            logger.error(f"Failed to parse DAISY 2.02: {e}")
            return None

    @staticmethod
    def parse_daisy3(folder_path: str) -> dict[str, Any] | None:
        """Parse a DAISY 3 / NISO 39.86 book structure."""
        try:
            # Find OPF file
            opf_files = [f for f in os.listdir(folder_path) if f.endswith(".opf")]
            if not opf_files:
                return None

            opf_path = os.path.join(folder_path, opf_files[0])
            tree = ET.parse(opf_path)
            root = tree.getroot()

            ns = {
                "opf": "http://www.idpf.org/2007/opf",
                "dc": "http://purl.org/dc/elements/1.1/",
            }

            book: dict[str, Any] = {
                "title": "",
                "author": "",
                "publisher": "",
                "format": "daisy3",
                "total_time": 0,
                "chapters": [],
                "audio_files": [],
            }

            # Metadata
            metadata = root.find(".//opf:metadata", ns)
            if metadata is not None:
                title_el = metadata.find("dc:title", ns)
                if title_el is not None:
                    book["title"] = title_el.text or ""
                creator_el = metadata.find("dc:creator", ns)
                if creator_el is not None:
                    book["author"] = creator_el.text or ""

            # Find audio files
            for audio_ext in (".mp3", ".wav", ".ogg", ".aac", ".mp4"):
                for f in os.listdir(folder_path):
                    if f.endswith(audio_ext):
                        book["audio_files"].append(os.path.join(folder_path, f))

            # Parse SMIL files for chapter structure
            smil_files = [f for f in os.listdir(folder_path) if f.endswith(".smil")]
            for smil in smil_files:
                try:
                    smil_tree = ET.parse(os.path.join(folder_path, smil))
                    smil_root = smil_tree.getroot()
                    seq = smil_root.find(".//{http://www.w3.org/2001/SMIL20/}seq")
                    if seq is not None:
                        for child in seq:
                            text = child.get("{http://www.w3.org/2001/SMIL20/}src", "")
                            if text:
                                book["chapters"].append({"title": text, "level": 1})
                except Exception:
                    continue

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
