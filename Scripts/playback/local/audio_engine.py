"""Manage the local audio engine and sounddevice stream for audio output.

    Handle the initialization and lifecycle of the audio stream for local audio output.
    Delegate the actual Digital Signal Processing (DSP) to the audio engine.
"""

from __future__ import annotations

import threading
from typing import Any

from playback.local.engines.base import BLOCK_SIZE, CHANNELS, SAMPLE_RATE
from playback.local.engines.fm_engine import FmEngine


class LocalAudioEngine:
    """Handle the initialization and lifecycle of the audio stream.
    
    Args:
        sample_rate (int): The sample rate of the audio engine.
    """
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
        """Check if the audio engine is successfully initialized and running."""
        return self._available

    @property
    def error_message(self) -> str | None:
        """Retrieve the last error message from the audio engine"""
        return self._error

    def start(self) -> bool:
        """Initialize the audio stream and background processing thread.
        
        Returns:
            bool: True if the audio stream was successfully initialized, False otherwise.
        """
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
        """Stop the audio stream and release hardware resources."""
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
        """Turn on a voice or update an existing one at a specific frequency."""
        self._engine.note_on(voice_id, frequency_hz, params or {})

    def note_off(self, voice_id: str | None = None) -> None:
        """Turn of a specific voice."""
        self._engine.note_off(voice_id)

    def all_notes_off(self) -> None:
        """Turn off all voices."""
        self._engine.all_notes_off()

    def update_params(self, params: dict) -> None:
        """Update synthesis parameters (e.g. volume, LFO, etc.)."""
        self._engine.update_params(params)

    def _callback(self, outdata, frames, time_info, status) -> None:
        """Feed the audio output buffer with the latest audio data."""
        with self._lock:
            np = self._np
        if np is None:
            outdata.fill(0)
            return
        self._engine.render(outdata, frames, np)
