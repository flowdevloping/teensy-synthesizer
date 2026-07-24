"""
Contains the Wavetable engine class for wavetable synthesis with morph between two tables
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field

import numpy as np

from safety_limits import FIRMWARE_MAX_AMPLITUDE, clamp_carrier_hz, clamp_volume_pct
from synth_state import MAX_VOICES

from engines.base import (
    SynthEngine,
    VoiceEnvelope,
    envelope_increments,
    soft_clip,
    voice_scale,
    wrap_phase,
)

TABLE_SIZE = 2048

# Makes a sine wave
def _make_sine() -> np.ndarray:
    t = np.linspace(0, 1, TABLE_SIZE, endpoint=False)
    return np.sin(2 * np.pi * t).astype(np.float32)

# Makes a triangle wave
def _make_triangle() -> np.ndarray:
    t = np.linspace(0, 1, TABLE_SIZE, endpoint=False)
    return (2 * np.abs(2 * t - 1) - 1).astype(np.float32)

# Makes a saw wave
def _make_saw() -> np.ndarray:
    t = np.linspace(0, 1, TABLE_SIZE, endpoint=False)
    return (2 * t - 1).astype(np.float32)

# Makes a pulse wave
def _make_pulse() -> np.ndarray:
    t = np.linspace(0, 1, TABLE_SIZE, endpoint=False)
    return np.where(t < 0.5, 1.0, -1.0).astype(np.float32)

# Dictionary of wavetables
WAVETABLES: dict[str, np.ndarray] = {
    "sine": _make_sine(),
    "triangle": _make_triangle(),
    "saw": _make_saw(),
    "pulse": _make_pulse(),
}

# Data class for a wavetable voice
@dataclass
class _WtVoice:
    voice_id: str
    env: VoiceEnvelope = field(default_factory=VoiceEnvelope)
    frequency_hz: float = 0.0
    phase: float = 0.0

# Class for the Wavetable engine
class WavetableEngine(SynthEngine):
    def __init__(self, sample_rate: int = 44100) -> None:
        super().__init__(sample_rate)
        self._lock = threading.Lock()
        self._volume = 0.1
        self._table_a = "sine"
        self._table_b = "saw"
        self._morph = 0.0  # 0 = A, 1 = B
        self._detune_cents = 0.0
        self._voices: dict[str, _WtVoice] = {}
        self._voice_order: list[str] = []

    # Turns all notes off
    def all_notes_off(self) -> None:
        self.note_off(None)

    # Turns a note on
    def note_on(self, voice_id: str, frequency_hz: float, params: dict) -> None:
        freq = clamp_carrier_hz(frequency_hz)
        if freq <= 0.0:
            self.note_off(voice_id)
            return
        with self._lock:
            self._apply_global(params)
            if voice_id in self._voices:
                voice = self._voices[voice_id]
                if voice_id in self._voice_order:
                    self._voice_order.remove(voice_id)
            else:
                if len(self._voices) >= MAX_VOICES and self._voice_order:
                    stolen = self._voice_order.pop(0)
                    self._voices.pop(stolen, None)
                voice = _WtVoice(voice_id=voice_id)
            voice.env.trigger_on()
            voice.frequency_hz = freq
            self._voices[voice_id] = voice
            self._voice_order.append(voice_id)

    # Turns a note off
    def note_off(self, voice_id: str | None = None) -> None:
        with self._lock:
            if voice_id is None:
                for v in self._voices.values():
                    v.env.note_off()
                return
            voice = self._voices.get(voice_id)
            if voice:
                voice.env.note_off()

    # Updates the parameters of the Wavetable engine
    def update_params(self, params: dict) -> None:
        with self._lock:
            self._apply_global(params)
            for voice_id, freq, *_rest in params.get("voices") or []:
                voice = self._voices.get(voice_id)
                if voice:
                    voice.frequency_hz = clamp_carrier_hz(freq)

    # Applies the global parameters to the Wavetable engine
    def _apply_global(self, params: dict) -> None:
        if "volume_pct" in params:
            self._volume = min(
                FIRMWARE_MAX_AMPLITUDE, clamp_volume_pct(params["volume_pct"]) / 100.0
            )
        if "table_a" in params and params["table_a"] in WAVETABLES:
            self._table_a = str(params["table_a"])
        if "table_b" in params and params["table_b"] in WAVETABLES:
            self._table_b = str(params["table_b"])
        if "morph" in params:
            self._morph = max(0.0, min(1.0, float(params["morph"])))
        if "detune_cents" in params:
            self._detune_cents = max(-50.0, min(50.0, float(params["detune_cents"])))

    # Renders the audio output
    def render(self, outdata, frames: int, np_mod) -> None:  # noqa: ANN001
        with self._lock:
            volume = self._volume
            morph = self._morph
            detune = self._detune_cents
            table_a = WAVETABLES[self._table_a]
            table_b = WAVETABLES[self._table_b]
            voices = list(self._voices.values())

        attack_incr, release_incr = envelope_increments(self.sample_rate)
        samples = np_mod.zeros(frames, dtype=np_mod.float32)
        scale = voice_scale()
        finished: list[str] = []
        detune_ratio = 2.0 ** (detune / 1200.0)

        for voice in voices:
            freq = voice.frequency_hz * detune_ratio
            for i in range(frames):
                voice.env.advance(attack_incr, release_incr)
                if voice.env.envelope <= 0.0 or volume <= 0.0:
                    continue
                idx = voice.phase * TABLE_SIZE
                i0 = int(idx) % TABLE_SIZE
                i1 = (i0 + 1) % TABLE_SIZE
                frac = idx - math.floor(idx)
                a = table_a[i0] * (1 - frac) + table_a[i1] * frac
                b = table_b[i0] * (1 - frac) + table_b[i1] * frac
                samples[i] += (a * (1 - morph) + b * morph) * volume * voice.env.envelope * scale
                voice.phase = wrap_phase(voice.phase + freq / self.sample_rate)
            if voice.env.finished:
                finished.append(voice.voice_id)

        soft_clip(samples, np_mod)
        outdata[:, 0] = samples
        with self._lock:
            for voice in voices:
                if voice.voice_id in self._voices:
                    self._voices[voice.voice_id] = voice
            for vid in finished:
                if vid in self._voices and self._voices[vid].env.finished:
                    del self._voices[vid]
                    if vid in self._voice_order:
                        self._voice_order.remove(vid)
