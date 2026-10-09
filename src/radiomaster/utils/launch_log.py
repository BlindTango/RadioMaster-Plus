"""Pre-logging launch recorder for RadioMaster+.

The regular logging setup (utils.logging_setup) only runs once the config
and paths are loaded -- but the most useful thing a launch log can capture
is exactly the crash that happens *before* that point, when the app cannot
start at all. This module is deliberately dependency-free (stdlib only, no
wx, no config) so it can be the very first import in ``__main__`` and still
work when everything else is broken.

Borrowed from Quill Radio 3.0.4's "a launcher that says why": when the app
cannot start, the worst thing it can do is nothing at all. The launch log
keeps whatever went wrong so the failure dialog can point at it.
"""

from __future__ import annotations

import datetime
import os
import sys
import traceback

_LINES: list[str] = []
_PATH: str | None = None


def _resolve_log_path() -> str:
    """Best-effort launch.log location, mirroring utils.paths.get_paths().

    Duplicated rather than imported because utils.paths pulls in
    platformdirs and the app package -- either of which may be exactly
    what is broken. Portable copies (writable app folder) keep the log
    beside their data; installed copies use the per-user data dir.
    """
    if getattr(sys, "frozen", False):
        app_dir = os.path.dirname(sys.executable)
    else:
        # src/radiomaster/utils/launch_log.py -> repo root
        app_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    try:
        probe = os.path.join(app_dir, ".write_test")
        with open(probe, "w") as f:
            f.write("x")
        os.remove(probe)
        return os.path.join(app_dir, "data", "logs", "launch.log")
    except OSError:
        pass
    try:
        from platformdirs import user_data_dir
        app_name = "RadioMasterPlus"
        return os.path.join(user_data_dir(app_name, app_name), "logs", "launch.log")
    except Exception:
        return os.path.join(app_dir, "launch.log")


def start() -> None:
    """Begin recording this launch (idempotent; call as early as possible)."""
    global _PATH
    if _PATH is not None:
        return
    _PATH = _resolve_log_path()
    record(f"Launch started: {sys.executable or 'python'}")
    record(f"Arguments: {sys.argv!r}")
    record(f"Python {sys.version.split()[0]} on {sys.platform}")


def record(message: str) -> None:
    """Append one timestamped line to the in-memory buffer and, once the
    path is known, flush the whole buffer to disk."""
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _LINES.append(f"{stamp}  {message}")
    if _PATH is not None:
        try:
            os.makedirs(os.path.dirname(_PATH), exist_ok=True)
            with open(_PATH, "a", encoding="utf-8", errors="replace") as f:
                f.write("\n".join(_LINES) + "\n")
            _LINES.clear()
        except OSError:
            # The disk itself may be the problem -- keep buffering in
            # memory so the failure dialog can still quote recent lines.
            pass


def record_exception(exc: BaseException) -> None:
    """Record an exception with its traceback."""
    record(f"ERROR: {exc.__class__.__name__}: {exc}")
    for line in traceback.format_exception(exc):
        for tb_line in line.rstrip().splitlines():
            record(f"  {tb_line}")


def path() -> str | None:
    """Where the launch log lives, or None if start() was never called."""
    return _PATH


def recent_lines(count: int = 15) -> list[str]:
    """The last ``count`` recorded lines (for the failure dialog's details)."""
    return _LINES[-count:]


def classify_failure(exc: BaseException) -> str:
    """Turn a startup exception into one plain sentence a screen reader
    reads on its own. A bare "invalid" or a silent exit is the failure
    mode this exists to prevent -- each class of problem gets its own
    words, borrowed from Quill Radio's launcher contract.
    """
    text = f"{exc}".lower()
    name = exc.__class__.__name__

    if isinstance(exc, (FileNotFoundError, ModuleNotFoundError)) or "no such file" in text \
            or "cannot find" in text or "not found" in text:
        return ("A file RadioMaster+ needs is missing. The copy may be incomplete -- "
                "reinstall RadioMaster+ from the latest release.")
    if "dll" in text or "loadlibrary" in text or "module could not be found" in text \
            or isinstance(exc, ImportError):
        return ("A component RadioMaster+ needs could not be loaded. The copy may be "
                "damaged or incomplete -- reinstall RadioMaster+ from the latest release.")
    if isinstance(exc, PermissionError) or "access is denied" in text or "access denied" in text:
        return ("Windows refused access to a file or folder RadioMaster+ needs. Try "
                "running RadioMaster+ as administrator, or move it to a folder you own.")
    if "database" in text or "sqlite" in text or "disk i/o" in text:
        return ("RadioMaster+ could not open its database. The drive may be full or "
                "the data folder may be damaged -- free up space and try again.")
    if isinstance(exc, MemoryError):
        return "RadioMaster+ ran out of memory. Close other programs and try again."
    if isinstance(exc, OSError):
        return (f"Windows reported a problem starting RadioMaster+ ({name}). The "
                f"launch log has the details.")
    detail = str(exc).strip()
    if detail:
        return (f"RadioMaster+ could not start: {detail}. The launch log has "
                f"the details.")
    return (f"RadioMaster+ could not start: {name}. The launch log has the details.")


class BundleIncompleteError(RuntimeError):
    """The app's own folder is missing files it cannot run without.

    Raised by :func:`check_bundle` when a packaged (frozen) copy is missing
    its ``_internal`` folder or the Python runtime inside it -- the shape of
    damage left by extracting a single file out of the release zip and
    running it alone (File Explorer, 7-Zip and WinRAR all let you press
    Enter on a file inside a zip; they copy that one file out and run it).
    """


def check_bundle() -> None:
    """Verify a frozen copy still has the files it needs beside the exe.

    Only meaningful for packaged builds -- a source checkout has no
    ``_internal``. When the folder is missing or the Python DLL inside it
    is gone, raise :class:`BundleIncompleteError` so the startup failure
    dialog can say the zip was never extracted instead of a generic
    "incomplete copy". (A completely lone exe never reaches Python at all:
    PyInstaller's bootloader shows its own "Failed to load Python DLL"
    message first -- the user manual's troubleshooting topic covers that
    path; this check catches the partially-extracted cases around it.)
    """
    if not getattr(sys, "frozen", False):
        return
    exe_dir = os.path.dirname(sys.executable)
    internal = os.path.join(exe_dir, "_internal")
    if not os.path.isdir(internal):
        raise BundleIncompleteError(
            f"the app folder is missing its _internal folder ({internal})"
        )
    # The Python DLL's name varies by build (python312.dll, python313.dll...)
    # -- any python*.dll present satisfies the check; a folder with none of
    # them is a damaged extraction, not a layout we ship.
    try:
        has_python_dll = any(
            name.lower().startswith("python") and name.lower().endswith(".dll")
            for name in os.listdir(internal)
        )
    except OSError as exc:
        raise BundleIncompleteError(f"the app folder could not be read ({exc})") from exc
    if not has_python_dll:
        raise BundleIncompleteError(
            "the app folder is missing the Python runtime inside _internal"
        )