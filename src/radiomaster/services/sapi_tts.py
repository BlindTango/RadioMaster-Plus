"""Windows SAPI Text-to-Speech service for reading audiobooks."""

import logging
import threading
from typing import Any, Callable

logger = logging.getLogger("radiomaster")


class SAPITTS:
    """Windows SAPI Text-to-Speech engine for reading books without audio."""

    def __init__(self) -> None:
        self._speaker: Any = None
        self._voices: list[dict[str, Any]] = []
        self._is_speaking = False
        self._is_paused = False
        self._rate: int = 0  # Default rate
        self._volume: int = 100
        self._current_voice: str = ""
        self._text_lines: list[str] = []
        self._current_line: int = 0

        self._on_line_change: Callable[[int], None] | None = None
        self._on_complete: Callable[[], None] | None = None

        self._initialize()

    def _initialize(self) -> None:
        """Initialize SAPI via pywin32."""
        try:
            import win32com.client
            self._speaker = win32com.client.Dispatch("SAPI.SpVoice")
            self._enumerate_voices()
            logger.info("SAPI TTS initialized")
        except ImportError:
            logger.warning("pywin32 not installed. SAPI TTS unavailable.")
        except Exception as e:
            logger.error(f"Failed to initialize SAPI: {e}")

    def _enumerate_voices(self) -> None:
        """Enumerate available SAPI voices."""
        if not self._speaker:
            return
        try:
            voices = self._speaker.GetVoices()
            for voice in voices:
                self._voices.append({
                    "id": voice.Id,
                    "name": voice.GetDescription(),
                })
            if self._voices:
                self._current_voice = self._voices[0]["id"]
        except Exception as e:
            logger.error(f"Failed to enumerate voices: {e}")

    def get_voices(self) -> list[dict[str, Any]]:
        """Get available SAPI voices."""
        return self._voices

    def set_voice(self, voice_id: str) -> None:
        """Set the active voice."""
        if not self._speaker:
            return
        try:
            voices = self._speaker.GetVoices()
            for voice in voices:
                if voice.Id == voice_id:
                    self._speaker.Voice = voice
                    self._current_voice = voice_id
                    break
        except Exception as e:
            logger.error(f"Failed to set voice: {e}")

    def set_rate(self, rate: int) -> None:
        """Set speech rate (-10 to 10)."""
        if not self._speaker:
            return
        self._rate = max(-10, min(10, rate))
        try:
            self._speaker.Rate = self._rate
        except Exception as e:
            logger.error(f"Failed to set rate: {e}")

    def set_volume(self, volume: int) -> None:
        """Set speech volume (0 to 100)."""
        if not self._speaker:
            return
        self._volume = max(0, min(100, volume))
        try:
            self._speaker.Volume = self._volume
        except Exception as e:
            logger.error(f"Failed to set volume: {e}")

    def speak(self, text: str) -> None:
        """Speak text asynchronously."""
        if not self._speaker:
            return
        self._is_speaking = True
        self._is_paused = False
        try:
            self._speaker.Speak(text, 1)  # 1 = SVSFlagsAsync
            self._start_monitor()
        except Exception as e:
            logger.error(f"Failed to speak: {e}")

    def speak_lines(self, lines: list[str], start_line: int = 0) -> None:
        """Speak a list of lines, tracking current line."""
        self._text_lines = lines
        self._current_line = start_line
        if lines and start_line < len(lines):
            self.speak(lines[start_line])

    def pause(self) -> None:
        """Pause speech."""
        if not self._speaker or not self._is_speaking:
            return
        try:
            self._speaker.Pause()
            self._is_paused = True
        except Exception as e:
            logger.error(f"Failed to pause: {e}")

    def resume(self) -> None:
        """Resume speech."""
        if not self._speaker or not self._is_paused:
            return
        try:
            self._speaker.Resume()
            self._is_paused = False
        except Exception as e:
            logger.error(f"Failed to resume: {e}")

    def stop(self) -> None:
        """Stop speech."""
        if not self._speaker:
            return
        try:
            self._speaker.Speak("", 2)  # 2 = SVSFPurgeBeforeSpeak
            self._is_speaking = False
            self._is_paused = False
        except Exception as e:
            logger.error(f"Failed to stop: {e}")

    def skip_forward(self) -> None:
        """Skip to the next line."""
        if self._text_lines and self._current_line < len(self._text_lines) - 1:
            self.stop()
            self._current_line += 1
            self.speak(self._text_lines[self._current_line])
            if self._on_line_change:
                self._on_line_change(self._current_line)

    def skip_backward(self) -> None:
        """Skip to the previous line."""
        if self._text_lines and self._current_line > 0:
            self.stop()
            self._current_line -= 1
            self.speak(self._text_lines[self._current_line])
            if self._on_line_change:
                self._on_line_change(self._current_line)

    def _start_monitor(self) -> None:
        """Monitor speech completion."""
        def monitor() -> None:
            import time
            while self._is_speaking and self._speaker:
                try:
                    if self._speaker.Status.RunningState == 1:  # Finished
                        self._is_speaking = False
                        # Auto-advance to next line
                        if self._text_lines and self._current_line < len(self._text_lines) - 1:
                            self._current_line += 1
                            self.speak(self._text_lines[self._current_line])
                            if self._on_line_change:
                                self._on_line_change(self._current_line)
                        elif self._on_complete:
                            self._on_complete()
                        break
                except Exception:
                    break
                time.sleep(0.1)

        threading.Thread(target=monitor, daemon=True).start()

    def on_line_change(self, cb: Callable[[int], None]) -> None:
        self._on_line_change = cb

    def on_complete(self, cb: Callable[[], None]) -> None:
        self._on_complete = cb

    @property
    def is_speaking(self) -> bool:
        return self._is_speaking

    @property
    def is_paused(self) -> bool:
        return self._is_paused

    @property
    def current_line(self) -> int:
        return self._current_line
