"""
Contains the Granular engine class for granular synthesis over a synthetic source buffer
"""

from __future__ import annotations

import math
import random
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
)

BUFFER_SECONDS = 1.0
MAX_GRAINS_PER_VOICE = 6

# Builds the source buffer 
def _build_source_buffer(sample_rate: int) -> np.ndarray:
    n = int(sample_rate * BUFFER_SECONDS)
    t = np.linspace(0, BUFFER_SECONDS, n, endpoint=False)
    # Soft noise bed + slow sine for texture
    noise = (np.random.default_rng(42).standard_normal(n) * 0.25).astype(np.float32)
    tone = (0.35 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    buf = noise + tone
    peak = float(np.max(np.abs(buf))) or 1.0
    return (buf / peak).astype(np.float32)

# Data class for a grain
@dataclass
class _Grain:
    pos: float
    phase: float
    length: int
    age: int = 0
    pan_amp: float = 1.0

# Data class for a granular voice
@dataclass
class _GranVoice:
    voice_id: str
    env: VoiceEnvelope = field(default_factory=VoiceEnvelope)
    frequency_hz: float = 0.0
    grains: list[_Grain] = field(default_factory=list)
    spawn_accum: float = 0.0

# Class for the Granular engine
class GranularEngine(SynthEngine):
    def __init__(self, sample_rate: int = 44100) -> None:
        super().__init__(sample_rate)
        self._lock = threading.Lock()
        self._volume = 0.1
        self._grain_ms = 40.0
        self._density = 12.0  # grains per second per voice
        self._position = 0.3  # 0..1 in buffer
        self._spray = 0.15
        self._pitch_ratio = 1.0
        self._buffer = _build_source_buffer(sample_rate)
        self._voices: dict[str, _GranVoice] = {}
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
                voice = _GranVoice(voice_id=voice_id)
            voice.env.trigger_on()
            voice.frequency_hz = freq
            # Map note to pitch ratio relative to A4=440
            voice.grains.clear()
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

    # Updates the parameters of the Granular engine
    def update_params(self, params: dict) -> None:
        with self._lock:
            self._apply_global(params)
            for voice_id, freq, *_rest in params.get("voices") or []:
                voice = self._voices.get(voice_id)
                if voice:
                    voice.frequency_hz = clamp_carrier_hz(freq)

    # Applies the global parameters to the Granular engine
    def _apply_global(self, params: dict) -> None:
        if "volume_pct" in params:
            self._volume = min(
                FIRMWARE_MAX_AMPLITUDE, clamp_volume_pct(params["volume_pct"]) / 100.0
            )
        if "grain_ms" in params:
            self._grain_ms = max(5.0, min(200.0, float(params["grain_ms"])))
        if "density" in params:
            self._density = max(1.0, min(40.0, float(params["density"])))
        if "position" in params:
            self._position = max(0.0, min(1.0, float(params["position"])))
        if "spray" in params:
            self._spray = max(0.0, min(0.5, float(params["spray"])))
        if "pitch_ratio" in params:
            self._pitch_ratio = max(0.25, min(4.0, float(params["pitch_ratio"])))

    # Spawns a grain
    def _spawn_grain(self, voice: _GranVoice) -> None:
        if len(voice.grains) >= MAX_GRAINS_PER_VOICE:
            return
        buf_len = len(self._buffer)
        spray = (random.random() * 2 - 1) * self._spray
        pos = max(0.0, min(1.0, self._position + spray))
        start = int(pos * (buf_len - 1))
        length = max(32, int(self.sample_rate * self._grain_ms / 1000.0))
        # Pitch from note relative to 440 + global ratio
        note_ratio = (voice.frequency_hz / 440.0) * self._pitch_ratio
        voice.grains.append(
            _Grain(pos=float(start), phase=note_ratio, length=length)
        )

    # Renders the audio output
    def render(self, outdata, frames: int, np_mod) -> None:  # noqa: ANN001
        with self._lock:
            volume = self._volume
            density = self._density
            buffer = self._buffer
            voices = list(self._voices.values())

        attack_incr, release_incr = envelope_increments(self.sample_rate)
        samples = np_mod.zeros(frames, dtype=np_mod.float32)
        scale = voice_scale()
        finished: list[str] = []
        buf_len = len(buffer)

        for voice in voices:
            spawn_rate = density / self.sample_rate
            for i in range(frames):
                voice.env.advance(attack_incr, release_incr)
                voice.spawn_accum += spawn_rate
                while voice.spawn_accum >= 1.0:
                    voice.spawn_accum -= 1.0
                    if voice.env.note_requested:
                        self._spawn_grain(voice)

                if voice.env.envelope <= 0.0 or volume <= 0.0:
                    continue

                grain_sum = 0.0
                alive: list[_Grain] = []
                for grain in voice.grains:
                    if grain.age >= grain.length:
                        continue
                    # Hann window
                    w = 0.5 - 0.5 * math.cos(2 * math.pi * grain.age / max(1, grain.length))
                    idx = int(grain.pos + grain.age * grain.phase) % buf_len
                    grain_sum += buffer[idx] * w
                    grain.age += 1
                    if grain.age < grain.length:
                        alive.append(grain)
                voice.grains = alive
                samples[i] += grain_sum * volume * voice.env.envelope * scale * 0.35

            if voice.env.finished and not voice.grains:
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
