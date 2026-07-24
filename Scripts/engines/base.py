"""
Contains base classes for the synth engines
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from safety_limits import (
    ENVELOPE_ATTACK_MS,
    ENVELOPE_RELEASE_MS,
    FIRMWARE_MAX_AMPLITUDE,
)
from synth_state import MAX_VOICES

# Constants for the synth engine
SAMPLE_RATE = 44100
BLOCK_SIZE = 256
CHANNELS = 1

# Data class for a voice envelope
@dataclass
class VoiceEnvelope:
    note_requested: bool = False
    envelope: float = 0.0
    envelope_releasing: bool = False

    def advance(self, attack_incr: float, release_incr: float) -> None:
        if self.note_requested and not self.envelope_releasing:
            if ENVELOPE_ATTACK_MS <= 0.0:
                self.envelope = 1.0
            else:
                self.envelope = min(1.0, self.envelope + attack_incr)
        else:
            if ENVELOPE_RELEASE_MS <= 0.0:
                self.envelope = 0.0
            else:
                self.envelope = max(0.0, self.envelope - release_incr)
            if self.envelope <= 0.0:
                self.envelope_releasing = False

    def trigger_on(self) -> bool:
        starting = not self.note_requested or self.envelope_releasing
        self.note_requested = True
        self.envelope_releasing = False
        return starting

    def note_off(self) -> None:
        self.note_requested = False
        self.envelope_releasing = True

    @property
    def finished(self) -> bool:
        return self.envelope <= 0.0 and not self.note_requested


def envelope_increments(sample_rate: int) -> tuple[float, float]:
    attack_incr = (
        1.0 / max(1, int(sample_rate * ENVELOPE_ATTACK_MS / 1000.0))
        if ENVELOPE_ATTACK_MS > 0.0
        else 1.0
    )
    release_incr = (
        1.0 / max(1, int(sample_rate * ENVELOPE_RELEASE_MS / 1000.0))
        if ENVELOPE_RELEASE_MS > 0.0
        else 1.0
    )
    return attack_incr, release_incr

# Applies a soft clip to the samples
def soft_clip(samples: Any, np: Any) -> Any:
    peak = float(np.max(np.abs(samples))) if len(samples) else 0.0
    if peak > FIRMWARE_MAX_AMPLITUDE:
        samples *= FIRMWARE_MAX_AMPLITUDE / peak
    return samples

# Computes the voice scale
def voice_scale() -> float:
    return 1.0 / MAX_VOICES

# Wraps the phase
def wrap_phase(phase: float) -> float:
    if phase >= 1.0:
        phase -= math.floor(phase)
    return phase

# Dictionary of synth modes (FM, Pure Sine, Additive, Subtractive, Wavetable, Granular)
SYNTH_MODES = ("fm", "pure_sine", "additive", "subtractive", "wavetable", "granular")

# Dictionary of synth mode labels
MODE_LABELS = {
    "fm": "FM (approved on Teensy)",
    "pure_sine": "Pure Sine",
    "additive": "Additive",
    "subtractive": "Subtractive",
    "wavetable": "Wavetable",
    "granular": "Granular",
}

# Base class for all synth engines
class SynthEngine(ABC):
    def __init__(self, sample_rate: int = SAMPLE_RATE) -> None:
        self.sample_rate = sample_rate

    @abstractmethod
    def all_notes_off(self) -> None: ...

    @abstractmethod
    def note_on(self, voice_id: str, frequency_hz: float, params: dict) -> None: ...

    @abstractmethod
    def note_off(self, voice_id: str | None = None) -> None: ...

    @abstractmethod
    def update_params(self, params: dict) -> None: ...

    @abstractmethod
    def render(self, outdata, frames: int, np) -> None: ...  # noqa: ANN001
