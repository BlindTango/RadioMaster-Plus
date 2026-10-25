"""Windows OneCore text-to-speech (WinRT SpeechSynthesizer) for audiobooks.

Offers the same interface as SAPITTS so the audiobook panel and the settings
preview can use either. The synthesizer renders each line to WAV in memory;
a worker thread plays it with sounddevice, preparing the next line while the
current one plays so sentences follow each other without a gap.
"""

from __future__ import annotations

import asyncio
import io
import logging
import threading
import wave
from typing import Any, Callable

logger = logging.getLogger("radiomaster")


def winrt_available() -> bool:
    try:
        from winrt.windows.media.speechsynthesis import SpeechSynthesizer  # noqa: F401
        return True
    except Exception:
        return False


class OneCoreTTS:
    def __init__(self) -> None:
        self._synth: Any = None
        self._voice_objects: list[Any] = []
        self._voices: list[dict[str, Any]] = []
        self._rate = 0
        self._volume = 100
        self._lines: list[str] = []
        self._current_line = 0
        self._is_speaking = False
        self._is_paused = False
        self._generation = 0
        self._lock = threading.Lock()
        self._on_line_change: Callable[[int], None] | None = None
        self._on_complete: Callable[[], None] | None = None
        self._initialize()

    # -- setup ----------------------------------------------------------
    def _initialize(self) -> None:
        try:
            from winrt.windows.media.speechsynthesis import SpeechSynthesizer
            self._synth = SpeechSynthesizer()
            self._voice_objects = list(SpeechSynthesizer.all_voices)
            self._voices = [{"id": v.id, "name": f"{v.display_name} ({v.language})"}
                            for v in self._voice_objects]
            if self._voice_objects:
                self._synth.voice = self._voice_objects[0]
        except Exception as exc:
            logger.warning("OneCore TTS unavailable: %s", exc)
            self._synth = None

    @property
    def available(self) -> bool:
        return self._synth is not None and bool(self._voices)

    def get_voices(self) -> list[dict[str, Any]]:
        return self._voices

    def set_voice(self, voice_id: str) -> None:
        for voice in self._voice_objects:
            if voice.id == voice_id:
                self._synth.voice = voice
                return
        raise RuntimeError("Windows could not select that speech voice.")

    def set_rate(self, rate: int) -> None:
        """SAPI-style -10..10 mapped onto the synthesizer's 0.5-6.0 multiplier."""
        self._rate = int(rate)

    def set_volume(self, volume: int) -> None:
        self._volume = max(0, min(100, int(volume)))

    # -- synthesis ------------------------------------------------------
    def _synthesize(self, text: str) -> tuple[Any, int, int]:
        """WAV for ``text`` as (int16 samples, sample rate, channels)."""
        import numpy as np
        from winrt.windows.storage.streams import DataReader

        async def render() -> bytes:
            self._synth.options.speaking_rate = max(0.5, min(6.0, 2.0 ** (self._rate / 5.0)))
            self._synth.options.audio_volume = self._volume / 100.0
            stream = await self._synth.synthesize_text_to_stream_async(text)
            size = stream.size
            reader = DataReader(stream.get_input_stream_at(0))
            await reader.load_async(size)
            buf = bytearray(size)
            reader.read_bytes(buf)
            return bytes(buf)

        data = asyncio.run(render())
        with wave.open(io.BytesIO(data)) as wav:
            frames = wav.readframes(wav.getnframes())
            return (np.frombuffer(frames, dtype=np.int16), wav.getframerate(), wav.getnchannels())

    # -- playback -------------------------------------------------------
    def speak(self, text: str) -> None:
        self.speak_lines([text])

    def speak_lines(self, lines: list[str], start_line: int = 0) -> None:
        if not self.available:
            raise RuntimeError("Windows could not start text-to-speech.")
        with self._lock:
            self._generation += 1
            generation = self._generation
            self._lines = list(lines)
            self._current_line = start_line
            self._is_speaking = True
            self._is_paused = False
        threading.Thread(target=self._run, args=(generation,), daemon=True,
                         name="onecore-tts").start()

    def _post(self, callback: Callable[..., None] | None, *args: Any) -> None:
        if callback is None:
            return
        try:
            import wx
            wx.CallAfter(callback, *args)
        except Exception:
            callback(*args)

    def _run(self, generation: int) -> None:
        import sounddevice as sd
        try:
            index = self._current_line
            pending = None
            first = True
            while index < len(self._lines) and generation == self._generation:
                audio = pending or self._synthesize(self._lines[index])
                pending = None
                if generation != self._generation:
                    return
                self._current_line = index
                if not first:
                    self._post(self._on_line_change, index)
                first = False
                samples, rate, channels = audio
                sd.play(samples.reshape(-1, channels) if channels > 1 else samples, rate)
                if index + 1 < len(self._lines):
                    pending = self._synthesize(self._lines[index + 1])
                while sd.get_stream().active and generation == self._generation:
                    sd.sleep(30)
                if generation != self._generation:
                    return
                index += 1
            if generation == self._generation:
                self._is_speaking = False
                self._post(self._on_complete)
        except Exception as exc:
            logger.error("OneCore TTS failed: %s", exc)
            if generation == self._generation:
                self._is_speaking = False

    def _halt(self) -> None:
        import sounddevice as sd
        with self._lock:
            self._generation += 1
        try:
            sd.stop()
        except Exception:
            pass

    def stop(self) -> None:
        self._halt()
        self._is_speaking = False
        self._is_paused = False

    def pause(self) -> None:
        if self._is_speaking and not self._is_paused:
            self._halt()
            self._is_paused = True

    def resume(self) -> None:
        if self._is_paused:
            self._is_paused = False
            self.speak_lines(self._lines, self._current_line)

    def skip_forward(self) -> None:
        if self._current_line < len(self._lines) - 1:
            self.speak_lines(self._lines, self._current_line + 1)
            self._post(self._on_line_change, self._current_line)

    def skip_backward(self) -> None:
        if self._current_line > 0:
            self.speak_lines(self._lines, self._current_line - 1)
            self._post(self._on_line_change, self._current_line)

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
