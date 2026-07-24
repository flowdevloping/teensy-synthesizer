"""
Contains the Subtractive engine class for subtractive synthesis
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

# Data class for a subtractive voice
@dataclass
class _SubVoice:
    voice_id: str
    env: VoiceEnvelope = field(default_factory=VoiceEnvelope)
    frequency_hz: float = 0.0
    phase: float = 0.0
    filter_state: float = 0.0

# Class for the Subtractive engine
class SubtractiveEngine(SynthEngine):
    def __init__(self, sample_rate: int = 44100) -> None:
        super().__init__(sample_rate)
        self._lock = threading.Lock()
        self._volume = 0.1
        self._waveform = "saw"  # saw | pulse
        self._cutoff_hz = 2000.0
        self._pulse_width = 0.5
        self._voices: dict[str, _SubVoice] = {}
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
                voice = _SubVoice(voice_id=voice_id)
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

    # Updates the parameters of the Subtractive engine
    def update_params(self, params: dict) -> None:
        with self._lock:
            self._apply_global(params)
            for voice_id, freq, *_rest in params.get("voices") or []:
                voice = self._voices.get(voice_id)
                if voice:
                    voice.frequency_hz = clamp_carrier_hz(freq)

    # Applies the global parameters to the Subtractive engine
    def _apply_global(self, params: dict) -> None:
        if "volume_pct" in params:
            self._volume = min(
                FIRMWARE_MAX_AMPLITUDE, clamp_volume_pct(params["volume_pct"]) / 100.0
            )
        if "waveform" in params:
            self._waveform = str(params["waveform"])
        if "cutoff_hz" in params:
            self._cutoff_hz = max(80.0, min(12000.0, float(params["cutoff_hz"])))
        if "pulse_width" in params:
            self._pulse_width = max(0.05, min(0.95, float(params["pulse_width"])))

    # Renders the audio output
    def render(self, outdata, frames: int, np) -> None:  # noqa: ANN001
        with self._lock:
            volume = self._volume
            waveform = self._waveform
            cutoff = self._cutoff_hz
            pulse_width = self._pulse_width
            voices = list(self._voices.values())

        attack_incr, release_incr = envelope_increments(self.sample_rate)
        # One-pole lowpass coefficient
        rc = 1.0 / (2.0 * math.pi * cutoff)
        dt = 1.0 / self.sample_rate
        alpha = dt / (rc + dt)

        samples = np.zeros(frames, dtype=np.float32)
        scale = voice_scale()
        finished: list[str] = []

        for voice in voices:
            for i in range(frames):
                voice.env.advance(attack_incr, release_incr)
                if voice.env.envelope <= 0.0 or volume <= 0.0:
                    continue
                if waveform == "pulse":
                    raw = 1.0 if voice.phase < pulse_width else -1.0
                else:
                    raw = 2.0 * voice.phase - 1.0  # saw
                voice.filter_state += alpha * (raw - voice.filter_state)
                samples[i] += voice.filter_state * volume * voice.env.envelope * scale
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
