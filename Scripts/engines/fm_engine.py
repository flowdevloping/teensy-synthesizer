"""
Contains the FM engine class for polyphonic FM synthesis
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field

from safety_limits import (
    FIRMWARE_MAX_AMPLITUDE,
    FIRMWARE_MAX_MOD_DEPTH,
    MODULATOR_FADE_MS,
    clamp_carrier_hz,
    clamp_mod_depth_pct,
    clamp_modulator_hz,
    clamp_volume_pct,
)
from synth_state import MAX_VOICES

from engines.base import (
    SynthEngine,
    VoiceEnvelope,
    envelope_increments,
    soft_clip,
    voice_scale,
    wrap_phase,
)

PURE_SINE_MOD_HZ_THRESHOLD = 1.0

# Data class for a FM voice
@dataclass
class _FmVoice:
    voice_id: str
    env: VoiceEnvelope = field(default_factory=VoiceEnvelope)
    carrier_hz: float = 0.0
    modulator_hz: float = 20.0
    mod_fade: float = 0.0
    mod_fade_active: bool = False
    carrier_phase: float = 0.0
    mod_phase: float = 0.0

# Class for the FM engine
class FmEngine(SynthEngine):
    def __init__(self, sample_rate: int = 44100) -> None:
        super().__init__(sample_rate)
        self._lock = threading.Lock()
        self._volume = 0.1
        self._mod_depth = 0.2
        self._pure_sine = False
        self._voices: dict[str, _FmVoice] = {}
        self._voice_order: list[str] = []

    # Turns all notes off
    def all_notes_off(self) -> None:
        self.note_off(None)

    # Turns a note on
    def note_on(self, voice_id: str, frequency_hz: float, params: dict) -> None:
        carrier = clamp_carrier_hz(frequency_hz)
        if carrier <= 0.0:
            self.note_off(voice_id)
            return

        volume_pct = int(params.get("volume_pct", 10))
        mod_depth_pct = int(params.get("mod_depth_pct", 20))
        pure_sine = bool(params.get("pure_sine", False))
        modulator_hz = float(params.get("modulator_hz", 20.0))

        with self._lock:
            self._volume = min(FIRMWARE_MAX_AMPLITUDE, clamp_volume_pct(volume_pct) / 100.0)
            self._mod_depth = min(
                FIRMWARE_MAX_MOD_DEPTH, clamp_mod_depth_pct(mod_depth_pct) / 100.0
            )
            self._pure_sine = pure_sine
            mod_hz = 0.0 if pure_sine else clamp_modulator_hz(modulator_hz)
            use_pure = pure_sine or mod_hz < PURE_SINE_MOD_HZ_THRESHOLD

            if voice_id in self._voices:
                voice = self._voices[voice_id]
                if voice_id in self._voice_order:
                    self._voice_order.remove(voice_id)
            else:
                if len(self._voices) >= MAX_VOICES and self._voice_order:
                    stolen = self._voice_order.pop(0)
                    self._voices.pop(stolen, None)
                voice = _FmVoice(voice_id=voice_id)

            starting = voice.env.trigger_on()
            voice.carrier_hz = carrier
            voice.modulator_hz = mod_hz
            if starting:
                voice.mod_fade = 0.0
                voice.mod_fade_active = not use_pure and MODULATOR_FADE_MS > 0.0
                if not voice.mod_fade_active and not use_pure:
                    voice.mod_fade = 1.0
            self._voices[voice_id] = voice
            self._voice_order.append(voice_id)

    # Turns a note off
    def note_off(self, voice_id: str | None = None) -> None:
        with self._lock:
            if voice_id is None:
                for voice in self._voices.values():
                    voice.env.note_off()
                    voice.mod_fade_active = False
                return
            voice = self._voices.get(voice_id)
            if voice is None:
                return
            voice.env.note_off()
            voice.mod_fade_active = False

    # Updates the parameters of the FM engine
    def update_params(self, params: dict) -> None:
        with self._lock:
            if "volume_pct" in params:
                self._volume = min(
                    FIRMWARE_MAX_AMPLITUDE,
                    clamp_volume_pct(params["volume_pct"]) / 100.0,
                )
            if "mod_depth_pct" in params:
                self._mod_depth = min(
                    FIRMWARE_MAX_MOD_DEPTH,
                    clamp_mod_depth_pct(params["mod_depth_pct"]) / 100.0,
                )
            if "pure_sine" in params:
                self._pure_sine = bool(params["pure_sine"])
            voices = params.get("voices")
            if voices is not None:
                for voice_id, carrier_hz, modulator_hz in voices:
                    voice = self._voices.get(voice_id)
                    if voice is None:
                        continue
                    voice.carrier_hz = clamp_carrier_hz(carrier_hz)
                    if self._pure_sine:
                        voice.modulator_hz = 0.0
                        voice.mod_fade = 0.0
                        voice.mod_fade_active = False
                    else:
                        voice.modulator_hz = clamp_modulator_hz(modulator_hz)

    # Renders the audio output
    def render(self, outdata, frames: int, np) -> None:  # noqa: ANN001
        with self._lock:
            volume = self._volume
            mod_depth = self._mod_depth
            pure_sine = self._pure_sine
            voices = list(self._voices.values())

        attack_incr, release_incr = envelope_increments(self.sample_rate)
        fade_incr = (
            1.0 / max(1, int(self.sample_rate * MODULATOR_FADE_MS / 1000.0))
            if MODULATOR_FADE_MS > 0.0
            else 1.0
        )
        samples = np.zeros(frames, dtype=np.float32)
        two_pi = 2.0 * math.pi
        scale = voice_scale()
        finished: list[str] = []

        for voice in voices:
            for i in range(frames):
                voice.env.advance(attack_incr, release_incr)
                use_pure = pure_sine or voice.modulator_hz < PURE_SINE_MOD_HZ_THRESHOLD
                if voice.mod_fade_active and not use_pure:
                    voice.mod_fade = min(1.0, voice.mod_fade + fade_incr)
                    if voice.mod_fade >= 1.0:
                        voice.mod_fade_active = False

                if voice.env.envelope <= 0.0 or volume <= 0.0 or voice.carrier_hz <= 0.0:
                    continue

                if use_pure:
                    instant_freq = voice.carrier_hz
                else:
                    mod_signal = math.sin(two_pi * voice.mod_phase)
                    instant_freq = voice.carrier_hz * (
                        2.0 ** (mod_depth * voice.mod_fade * mod_signal)
                    )

                samples[i] += (
                    math.sin(two_pi * voice.carrier_phase)
                    * volume
                    * voice.env.envelope
                    * scale
                )
                voice.carrier_phase = wrap_phase(
                    voice.carrier_phase + instant_freq / self.sample_rate
                )
                if not use_pure:
                    voice.mod_phase = wrap_phase(
                        voice.mod_phase + voice.modulator_hz / self.sample_rate
                    )

            if voice.env.finished:
                finished.append(voice.voice_id)

        soft_clip(samples, np)
        outdata[:, 0] = samples

        with self._lock:
            for voice in voices:
                if voice.voice_id in self._voices:
                    self._voices[voice.voice_id] = voice
            for voice_id in finished:
                if voice_id in self._voices and self._voices[voice_id].env.finished:
                    del self._voices[voice_id]
                    if voice_id in self._voice_order:
                        self._voice_order.remove(voice_id)
