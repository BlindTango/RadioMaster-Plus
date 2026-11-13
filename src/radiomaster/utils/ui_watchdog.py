"""Detects a frozen window and records where the UI thread was stuck.

A wx timer on the UI thread refreshes a heartbeat. A daemon thread checks it;
when the UI thread has not run its timer for ``threshold`` seconds it writes
every thread's stack to ``ui-stalls.log``, once per stall. The first stack
shows the call the window is blocked in, which is what is needed to fix a
freeze that cannot be reproduced on demand.
"""

from __future__ import annotations

import datetime
import logging
import os
import sys
import threading
import time
import traceback

log = logging.getLogger("radiomaster")


class UiWatchdog:
    def __init__(self, log_dir: str, threshold: float = 2.0, interval_ms: int = 250) -> None:
        self._path = os.path.join(log_dir, "ui-stalls.log")
        self._threshold = threshold
        self._interval_ms = interval_ms
        self._beat = time.monotonic()
        self._ui_thread_id = threading.get_ident()
        self._stop = threading.Event()
        self._timer = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        import wx
        self._ui_thread_id = threading.get_ident()
        tick = self._tick

        class _Heartbeat(wx.Timer):
            def Notify(self) -> None:          # runs on the UI thread
                tick()

        self._timer = _Heartbeat()
        self._timer.Start(self._interval_ms)
        self._thread = threading.Thread(target=self._watch, daemon=True, name="ui-watchdog")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._timer is not None:
            self._timer.Stop()
            self._timer = None

    def _tick(self) -> None:
        self._beat = time.monotonic()

    def _watch(self) -> None:
        reported = False
        while not self._stop.wait(0.5):
            stalled_for = time.monotonic() - self._beat
            if stalled_for >= self._threshold:
                if not reported:
                    reported = True
                    self._write_report(stalled_for)
            elif reported:
                reported = False
                self._append(f"UI responsive again ({datetime.datetime.now():%H:%M:%S})\n\n")

    def _append(self, text: str) -> None:
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write(text)
        except OSError:
            log.debug("Could not write the UI stall log", exc_info=True)

    def _write_report(self, stalled_for: float) -> None:
        names = {t.ident: t.name for t in threading.enumerate()}
        lines = [f"=== UI thread not responding for {stalled_for:.1f} s "
                 f"at {datetime.datetime.now():%Y-%m-%d %H:%M:%S} ===\n"]
        frames = sys._current_frames()
        order = sorted(frames, key=lambda ident: ident != self._ui_thread_id)
        for ident in order:
            if ident == threading.get_ident():
                continue
            label = "UI THREAD" if ident == self._ui_thread_id else names.get(ident, str(ident))
            lines.append(f"--- {label} ---\n")
            lines.append("".join(traceback.format_stack(frames[ident])))
        lines.append("\n")
        self._append("".join(lines))
        log.warning("The window stopped responding for %.1f s; stacks written to %s",
                    stalled_for, self._path)
