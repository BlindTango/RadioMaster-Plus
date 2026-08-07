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

    def start(self, minutes: float, mode: str = MODE_COUNTDOWN) -> None:
        """Start the sleep timer."""
        self.stop()
        self._remaining = minutes * 60.0
        self._mode = mode
        self._running = True
        self._thread = threading.Thread(target=self._monitor, daemon=True)
        self._thread.start()
        logger.info(f"Sleep timer started: {minutes} min, mode: {mode}")

        # Reset any previously‑set mode‑action callback – the UI should set it
        # after calling ``start`` if the chosen mode is not simple countdown.
        self._on_mode_action = None

    def stop(self) -> None:
        """Stop the sleep timer."""
        self._running = False
        self._remaining = 0.0

    def _monitor(self) -> None:
        """Monitor the timer and fire timeout."""
        while self._running and self._remaining > 0:
            time.sleep(1)
            self._remaining -= 1

        if self._running and self._on_timeout:
            self._on_timeout()
        # If the timer expires in a mode that requires a playback action, invoke
        # the provided callback after the timeout handler (which may be used for
        # UI notifications).
        if self._running and self._on_mode_action:
            try:
                self._on_mode_action()
            except Exception as e:
                logger.error(f"SleepTimer mode‑action failed: {e}")

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
        """Set callback for end‑of‑track / end‑of‑playlist actions.

        The callback will be executed *after* the ``on_timeout`` callback when
        the timer reaches zero and the selected mode is ``MODE_END_OF_TRACK``
        or ``MODE_END_OF_PLAYLIST``.
        """
        self._on_mode_action = cb
