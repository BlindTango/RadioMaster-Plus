"""Logging setup for RadioMaster+.

Four user-facing modes (see Settings > General):
  - "off":   logging disabled entirely (no handlers, no I/O overhead).
  - "info":  normal operational messages (the previous default).
  - "debug": verbose internal tracing.
  - "io":    debug plus explicit input/output tracing (network
    requests/responses, subprocess commands) logged via ``log_io()``.

Regardless of mode, output goes to both stdout and a rotating file under
the app's data directory so a detailed log survives after the console
window (if any) is gone.
"""

import logging
import logging.handlers
import os
import sys

# Custom level below DEBUG so "io" mode is a strict superset of "debug".
IO_LEVEL = 5
logging.addLevelName(IO_LEVEL, "IO")

LEVELS = {
    "off": logging.CRITICAL + 1,
    "info": logging.INFO,
    "debug": logging.DEBUG,
    "io": IO_LEVEL,
}

_FORMAT = "%(asctime)s %(name)s %(levelname)s %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"

_root = logging.getLogger()


def log_io(logger: logging.Logger, msg: str, *args: object) -> None:
    """Log an input/output trace message (network calls, subprocess I/O).

    Only visible when the logging level is set to "io"; a no-op cost of
    one level check otherwise.
    """
    logger.log(IO_LEVEL, msg, *args)


def setup_logging(level: str = "info", log_dir: str | None = None) -> None:
    """Configure logging for the application.

    Safe to call more than once (e.g. when the user changes the level in
    Settings) -- clears any handlers from a previous call first.
    """
    for handler in list(_root.handlers):
        _root.removeHandler(handler)
        handler.close()

    resolved = LEVELS.get(level, logging.INFO)
    _root.setLevel(resolved)

    if resolved == LEVELS["off"]:
        return

    formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(resolved)
    _root.addHandler(stream_handler)

    if log_dir:
        try:
            os.makedirs(log_dir, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                os.path.join(log_dir, "radiomaster.log"),
                maxBytes=5 * 1024 * 1024,
                backupCount=3,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            file_handler.setLevel(resolved)
            _root.addHandler(file_handler)
        except OSError:
            pass

    # Quiet noisy libraries -- irrelevant at "io"/"debug" too; these are
    # third-party internals, not RadioMaster+'s own I/O.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
