"""
Contains LocalAudioEngine: owns the sounddevice stream and delegates DSP to a single FmEngine.
"""

from __future__ import annotations

import threading
from typing import Any

from engines.base import BLOCK_SIZE, CHANNELS, SAMPLE_RATE
from engines.fm_engine import FmEngine


class LocalAudioEngine:
    def __init__(self, sample_rate: int = SAMPLE_RATE) -> None:
        self.sample_rate = sample_rate
        self._lock = threading.Lock()
        self._stream: Any = None
        self._available = False
        self._error: str | None = None
        self._np: Any = None
        self._engine = FmEngine(sample_rate)

    @property
    def is_available(self) -> bool:
        return self._available

    @property
    def error_message(self) -> str | None:
        return self._error

    def start(self) -> bool:
        if self._stream is not None:
            return self._available
        try:
            import numpy as np
            import sounddevice as sd
        except ImportError as exc:
            self._available = False
            self._error = f"Audio library missing: {exc}"
            return False

        self._np = np
        try:
            self._stream = sd.OutputStream(
                samplerate=self.sample_rate,
                blocksize=BLOCK_SIZE,
                channels=CHANNELS,
                dtype="float32",
                callback=self._callback,
            )
            self._stream.start()
            self._available = True
            self._error = None
            return True
        except Exception as exc:
            self._stream = None
            self._available = False
            self._error = str(exc)
            return False

    def close(self) -> None:
        stream = self._stream
        self._stream = None
        self._available = False
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        with self._lock:
            self._engine.all_notes_off()

    def note_on(self, voice_id: str, frequency_hz: float, params: dict | None = None) -> None:
        self._engine.note_on(voice_id, frequency_hz, params or {})

    def note_off(self, voice_id: str | None = None) -> None:
        self._engine.note_off(voice_id)

    def all_notes_off(self) -> None:
        self._engine.all_notes_off()

    def update_params(self, params: dict) -> None:
        self._engine.update_params(params)

    def _callback(self, outdata, frames, time_info, status) -> None:  # noqa: ANN001
        with self._lock:
            np = self._np
        if np is None:
            outdata.fill(0)
            return
        self._engine.render(outdata, frames, np)
