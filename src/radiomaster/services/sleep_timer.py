"""Sleep timer service for auto-stopping playback."""

import threading
import time
import logging
from typing import Any, Callable

logger = logging.getLogger("radiomaster")


class SleepTimer:
    """Smart sleep timer with multiple stop modes."""

    MODE_COUNTDOWN = "countdown"
    MODE_END_OF_TRACK = "end_of_track"
    MODE_END_OF_PLAYLIST = "end_of_playlist"

    def __init__(self) -> None:
        self._remaining: float = 0.0
        self._mode: str = self.MODE_COUNTDOWN
        self._running = False
        self._thread: threading.Thread | None = None
        self._on_timeout: Callable[[], None] | None = None

        # Callback to be invoked when the timer expires *and* the selected
        # mode requires interaction with the playback engine.  The UI layer
        # will set this to a function that stops playback or moves to the next
        # track/playlist item.
        self._on_mode_action: Callable[[], None] | None = None
        self._pending = False

    def start(self, minutes: float, mode: str = MODE_COUNTDOWN) -> None:
        """Start the sleep timer."""
        self.stop()
        self._remaining = minutes * 60.0
        self._mode = mode
        self._running = True
        self._thread = threading.Thread(target=self._monitor, daemon=True)
        self._thread.start()
        logger.info(f"Sleep timer started: {minutes} min, mode: {mode}")

    @property
    def pending_mode(self) -> str | None:
        """The deferred mode awaiting a track/playlist boundary, if any."""
        return self._mode if self._pending else None

    def complete_pending(self) -> None:
        """Clear the deferred stop once the boundary has been honoured."""
        self._pending = False

    def stop(self) -> None:
        """Stop the sleep timer."""
        self._pending = False
        self._running = False
        self._remaining = 0.0

    def _monitor(self) -> None:
        """Monitor the timer and fire timeout."""
        while self._running and self._remaining > 0:
            time.sleep(1)
            self._remaining -= 1

        if not self._running:
            return
        if self._mode in (self.MODE_END_OF_TRACK, self.MODE_END_OF_PLAYLIST):
            # Deferred stop: the countdown only arms it. The playback layer
            # finishes the current track/playlist and then calls
            # ``complete_pending()`` (see MainWindow._on_track_finished).
            self._pending = True
            if self._on_mode_action:
                try:
                    self._on_mode_action()
                except Exception as e:
                    logger.error(f"SleepTimer mode-action failed: {e}")
            self._running = False
            return
        if self._on_timeout:
            self._on_timeout()
        self._running = False

    @property
    def remaining(self) -> float:
        """Get remaining time in seconds."""
        return self._remaining

    @property
    def is_active(self) -> bool:
        """Check if timer is running."""
        return self._running

    @property
    def mode(self) -> str:
        return self._mode

    def on_timeout(self, cb: Callable[[], None]) -> None:
        """Set callback for when timer expires."""
        self._on_timeout = cb

    def on_mode_action(self, cb: Callable[[], None]) -> None:
        """Set callback fired when the countdown ends in a deferred mode
        (``MODE_END_OF_TRACK`` / ``MODE_END_OF_PLAYLIST``), i.e. when the stop
        has been armed but playback has not yet reached its boundary.
        """
        self._on_mode_action = cb
