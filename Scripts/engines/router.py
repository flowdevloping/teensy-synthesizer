"""
Contains functionality to route note events to the active local synth engine over one audio stream
"""

from __future__ import annotations

import threading
from typing import Any

from engines.additive_engine import AdditiveEngine
from engines.base import BLOCK_SIZE, CHANNELS, SAMPLE_RATE, SYNTH_MODES, SynthEngine
from engines.fm_engine import FmEngine
from engines.granular_engine import GranularEngine
from engines.subtractive_engine import SubtractiveEngine
from engines.wavetable_engine import WavetableEngine

# Class for the local synth router
class LocalSynthRouter:
    def __init__(self, sample_rate: int = SAMPLE_RATE) -> None:
        self.sample_rate = sample_rate
        self._lock = threading.Lock()
        self._stream: Any = None
        self._available = False
        self._error: str | None = None
        self._np: Any = None
        self._mode = "fm"
        self._engines: dict[str, SynthEngine] = {
            "fm": FmEngine(sample_rate),
            "pure_sine": FmEngine(sample_rate),
            "additive": AdditiveEngine(sample_rate),
            "subtractive": SubtractiveEngine(sample_rate),
            "wavetable": WavetableEngine(sample_rate),
            "granular": GranularEngine(sample_rate),
        }

    @property
    def is_available(self) -> bool:
        return self._available

    @property
    def error_message(self) -> str | None:
        return self._error

    @property
    def mode(self) -> str:
        return self._mode

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
            for engine in self._engines.values():
                engine.all_notes_off()

    def set_mode(self, mode: str) -> None:
        if mode not in SYNTH_MODES:
            return
        with self._lock:
            if mode == self._mode:
                return
            old = self._engines[self._mode]
            self._mode = mode
        old.all_notes_off()

    def note_on(self, voice_id: str, frequency_hz: float, params: dict | None = None) -> None:
        with self._lock:
            engine = self._engines[self._mode]
        engine.note_on(voice_id, frequency_hz, params or {})

    def note_off(self, voice_id: str | None = None) -> None:
        with self._lock:
            engine = self._engines[self._mode]
        engine.note_off(voice_id)

    def all_notes_off(self) -> None:
        with self._lock:
            engine = self._engines[self._mode]
        engine.all_notes_off()

    def update_params(self, params: dict) -> None:
        with self._lock:
            engine = self._engines[self._mode]
        engine.update_params(params)

    def _callback(self, outdata, frames, time_info, status) -> None:  # noqa: ANN001
        with self._lock:
            engine = self._engines[self._mode]
            np = self._np
        if np is None:
            outdata.fill(0)
            return
        engine.render(outdata, frames, np)
