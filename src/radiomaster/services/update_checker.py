"""Checks GitHub Releases for a newer RadioMaster+ build and downloads the installer.

Replaces the earlier UpdateChecker, which only ever compared version
strings and showed a MessageBox -- it had no way to actually get a new
version onto the user's machine, and pointed at a placeholder GitHub org
("radiomaster/radiomaster-plus") that was never the real repo.
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Callable, Optional

import requests

log = logging.getLogger("radiomaster")

GITHUB_REPO = "BlindTango/RadioMaster-Plus"
_USER_AGENT = "RadioMasterPlus-Updater"


class UpdateCheckError(RuntimeError):
    pass


@dataclass
class UpdateInfo:
    version: str
    notes: str
    html_url: str
    download_url: Optional[str]
    asset_name: Optional[str]


def parse_version(text: str) -> tuple:
    text = text.strip().lstrip("vV")
    parts = re.findall(r"\d+", text)
    return tuple(int(p) for p in parts) or (0,)


def is_newer(remote_version: str, local_version: str) -> bool:
    return parse_version(remote_version) > parse_version(local_version)


class UpdateChecker:
    def __init__(self, repo: str = GITHUB_REPO, proxies: Optional[dict] = None):
        self.repo = repo
        self.proxies = proxies

    def check(self, current_version: str, timeout: float = 10.0) -> Optional[UpdateInfo]:
        url = f"https://api.github.com/repos/{self.repo}/releases/latest"
        try:
            resp = requests.get(
                url, timeout=timeout, proxies=self.proxies,
                headers={"Accept": "application/vnd.github+json", "User-Agent": _USER_AGENT},
            )
            if resp.status_code == 403 and resp.headers.get("X-RateLimit-Remaining") == "0":
                # GitHub's unauthenticated API allows only 60 requests/hour
                # per source IP, shared across everyone behind the same
                # NAT/office network -- easy to exhaust, and the raw
                # "403 Client Error: rate limit exceeded" requests message
                # gave the user no idea what happened or what to do about
                # it. X-RateLimit-Reset is a Unix timestamp for when the
                # window resets.
                reset_at = resp.headers.get("X-RateLimit-Reset")
                if reset_at:
                    wait_min = max(1, int((int(reset_at) - time.time()) / 60))
                    raise UpdateCheckError(
                        f"GitHub's update-check limit has been reached for this network "
                        f"(shared by everyone behind the same internet connection). "
                        f"Try again in about {wait_min} minute{'s' if wait_min != 1 else ''}."
                    )
                raise UpdateCheckError(
                    "GitHub's update-check limit has been reached for this network. "
                    "Try again in a bit -- it resets hourly."
                )
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise UpdateCheckError(f"Could not check for updates: {exc}") from exc

        tag = data.get("tag_name", "")
        if not tag or not is_newer(tag, current_version):
            return None

        download_url = None
        asset_name = None
        for asset in data.get("assets", []):
            name = asset.get("name", "")
            if name.lower().endswith(".exe"):
                download_url = asset.get("browser_download_url")
                asset_name = name
                break

        return UpdateInfo(
            version=tag.lstrip("vV"),
            notes=data.get("body", "") or "",
            html_url=data.get("html_url", f"https://github.com/{self.repo}/releases"),
            download_url=download_url,
            asset_name=asset_name,
        )

    def download_installer(
        self, info: UpdateInfo, dest_path: str,
        progress_cb: Optional[Callable[[int, int], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> None:
        if not info.download_url:
            raise UpdateCheckError("This release has no downloadable installer asset.")
        try:
            resp = requests.get(info.download_url, timeout=30, proxies=self.proxies, stream=True)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise UpdateCheckError(f"Could not download the update: {exc}") from exc

        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        tmp_path = dest_path + ".part"
        try:
            with open(tmp_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=262144):
                    if cancel_check and cancel_check():
                        raise UpdateCheckError("Download cancelled.")
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_cb:
                            progress_cb(downloaded, total)
            os.replace(tmp_path, dest_path)
        except OSError as exc:
            raise UpdateCheckError(f"Could not save the downloaded update: {exc}") from exc
        finally:
            if os.path.exists(tmp_path) and not os.path.exists(dest_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
