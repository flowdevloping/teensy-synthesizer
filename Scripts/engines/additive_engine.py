"""
Contains the Additive engine class for additive harmonic synthesis
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field

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

MAX_PARTIALS = 8

# Data class for an additive voice
@dataclass
class _AddVoice:
    voice_id: str
    env: VoiceEnvelope = field(default_factory=VoiceEnvelope)
    frequency_hz: float = 0.0
    phase: float = 0.0

# Class for the Additive engine
class AdditiveEngine(SynthEngine):
    def __init__(self, sample_rate: int = 44100) -> None:
        super().__init__(sample_rate)
        self._lock = threading.Lock()
        self._volume = 0.1
        # Relative amplitudes for harmonics 1..8
        self._partials = [1.0, 0.5, 0.33, 0.25, 0.0, 0.0, 0.0, 0.0]
        self._voices: dict[str, _AddVoice] = {}
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
            voice = self._alloc(voice_id)
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

    # Updates the parameters of the Additive engine
    def update_params(self, params: dict) -> None:
        with self._lock:
            self._apply_global(params)
            for voice_id, freq, *_rest in params.get("voices") or []:
                voice = self._voices.get(voice_id)
                if voice:
                    voice.frequency_hz = clamp_carrier_hz(freq)

    # Applies the global parameters to the Additive engine
    def _apply_global(self, params: dict) -> None:
        if "volume_pct" in params:
            self._volume = min(
                FIRMWARE_MAX_AMPLITUDE, clamp_volume_pct(params["volume_pct"]) / 100.0
            )
        if "partials" in params:
            parts = list(params["partials"])[:MAX_PARTIALS]
            while len(parts) < MAX_PARTIALS:
                parts.append(0.0)
            self._partials = [max(0.0, min(1.0, float(p))) for p in parts]

    # Allocates a voice
    def _alloc(self, voice_id: str) -> _AddVoice:
        if voice_id in self._voices:
            if voice_id in self._voice_order:
                self._voice_order.remove(voice_id)
            return self._voices[voice_id]
        if len(self._voices) >= MAX_VOICES and self._voice_order:
            stolen = self._voice_order.pop(0)
            self._voices.pop(stolen, None)
        return _AddVoice(voice_id=voice_id)

    # Renders the audio output
    def render(self, outdata, frames: int, np) -> None:  # noqa: ANN001
        with self._lock:
            volume = self._volume
            partials = list(self._partials)
            voices = list(self._voices.values())

        attack_incr, release_incr = envelope_increments(self.sample_rate)
        samples = np.zeros(frames, dtype=np.float32)
        two_pi = 2.0 * math.pi
        scale = voice_scale()
        finished: list[str] = []
        norm = sum(partials) or 1.0

        for voice in voices:
            for i in range(frames):
                voice.env.advance(attack_incr, release_incr)
                if voice.env.envelope <= 0.0 or volume <= 0.0:
                    continue
                s = 0.0
                for n, amp in enumerate(partials, start=1):
                    if amp <= 0.0:
                        continue
                    s += amp * math.sin(two_pi * wrap_phase(voice.phase * n))
                samples[i] += (s / norm) * volume * voice.env.envelope * scale
                voice.phase = wrap_phase(
                    voice.phase + voice.frequency_hz / self.sample_rate
                )
            if voice.env.finished:
                finished.append(voice.voice_id)

        soft_clip(samples, np)
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
