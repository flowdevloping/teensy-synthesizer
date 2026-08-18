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
class FmEngine:
    def __init__(self, sample_rate: int = 44100) -> None:
        self.sample_rate = sample_rate
        self._lock = threading.Lock()
        self._volume = 0.1
        self._mod_depth = 0.2
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
        modulator_hz = float(params.get("modulator_hz", 20.0))

        # Update the volume and modulator depth
        with self._lock:
            # Update the volume 
            self._volume = min(FIRMWARE_MAX_AMPLITUDE, clamp_volume_pct(volume_pct) / 100.0)
            # Update the modulator depth
            self._mod_depth = min(
                FIRMWARE_MAX_MOD_DEPTH, clamp_mod_depth_pct(mod_depth_pct) / 100.0
            )
            # Update the modulator frequency
            mod_hz = clamp_modulator_hz(modulator_hz)
            # Check if the modulator frequency is less than the threshold for pure sine
            use_pure = mod_hz < PURE_SINE_MOD_HZ_THRESHOLD

            # Check if the voice is already playing
            if voice_id in self._voices:
                # If the voice is already playing, remove it from the voice order
                voice = self._voices[voice_id]
                if voice_id in self._voice_order:
                    self._voice_order.remove(voice_id)
            # If the voice is not playing, create a new voice
            else:
                # If the number of voices is greater than the maximum number of voices, steal the first voice from the voice order
                if len(self._voices) >= MAX_VOICES and self._voice_order:
                    stolen = self._voice_order.pop(0)
                    self._voices.pop(stolen, None)
                # Create a new voice
                voice = _FmVoice(voice_id=voice_id)

            # Trigger the voice on
            starting = voice.env.trigger_on()
            # Update the carrier frequency
            voice.carrier_hz = carrier
            # Update the modulator frequency
            voice.modulator_hz = mod_hz
            # Update the modulator fade
            if starting:
                # If the voice is starting, set the modulator fade to 0.0
                voice.mod_fade = 0.0
                # Update the modulator fade active
                voice.mod_fade_active = not use_pure and MODULATOR_FADE_MS > 0.0
                # If the modulator fade is not active and the modulator frequency is less than the threshold for pure sine, set the modulator fade to 1.0
                if not voice.mod_fade_active and not use_pure:
                    # Set the modulator fade to 1.0
                    voice.mod_fade = 1.0
            # Update the voice
            self._voices[voice_id] = voice
            # Add the voice to the voice order
            self._voice_order.append(voice_id)

    # Turns a note off
    def note_off(self, voice_id: str | None = None) -> None:
        with self._lock:
            if voice_id is None:
                # Turn off all voices
                for voice in self._voices.values():
                    # Turn off the voice
                    voice.env.note_off()
                    # Update the modulator fade active
                    voice.mod_fade_active = False
                return
            # Get the voice
            voice = self._voices.get(voice_id)
            # If the voice is not found, return
            if voice is None:
                return
            # Turn off the voice
            voice.env.note_off()
            # Update the modulator fade active
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
            voices = params.get("voices")
            if voices is not None:
                for voice_id, carrier_hz, modulator_hz in voices:
                    voice = self._voices.get(voice_id)
                    if voice is None:
                        continue
                    voice.carrier_hz = clamp_carrier_hz(carrier_hz)
                    voice.modulator_hz = clamp_modulator_hz(modulator_hz)

    # Calculate audio samples and send it to the hardware 
    # process voices -> calculate sound samples out of them -> soft clip the samples -> output the samples to the sound card of the computer
    def render(self, outdata, frames: int, np) -> None:  # noqa: ANN001
        with self._lock:
            volume = self._volume
            mod_depth = self._mod_depth
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

        # Process each voice
        for voice in voices:
            for i in range(frames):
                # Apply envelope attack and release
                voice.env.advance(attack_incr, release_incr)
                # Check if the voice is using pure sine
                use_pure = voice.modulator_hz < PURE_SINE_MOD_HZ_THRESHOLD
                # If the modulator fade is active and the voice is not using pure sine, update the modulator fade
                if voice.mod_fade_active and not use_pure:
                    voice.mod_fade = min(1.0, voice.mod_fade + fade_incr)
                    if voice.mod_fade >= 1.0:
                        voice.mod_fade_active = False

                # Check if the voice is finished
                if voice.env.envelope <= 0.0 or volume <= 0.0 or voice.carrier_hz <= 0.0:
                    continue

                # If the voice is using pure sine, set the instant frequency to the carrier frequency
                if use_pure:
                    # Create sound samples for pure sine
                    instant_freq = voice.carrier_hz
                # If the voice is using FM, create sound samples for FM
                else:
                    # Create sound samples for FM
                    mod_signal = math.sin(two_pi * voice.mod_phase)
                    instant_freq = voice.carrier_hz * (
                        2.0 ** (mod_depth * voice.mod_fade * mod_signal)
                    )

                # Add the sound sample to the samples array
                samples[i] += (
                    math.sin(two_pi * voice.carrier_phase)
                    * volume
                    * voice.env.envelope
                    * scale
                )
                # Update the carrier phase
                voice.carrier_phase = wrap_phase(
                    voice.carrier_phase + instant_freq / self.sample_rate
                )
                if not use_pure:
                    # Update the modulator phase
                    voice.mod_phase = wrap_phase(
                        voice.mod_phase + voice.modulator_hz / self.sample_rate
                    )
            
            # If the voice is finished, add it to the finished list
            if voice.env.finished:
                finished.append(voice.voice_id)

        # Soft clip the samples
        soft_clip(samples, np)
        # Output the samples (outdata goes to the sound card of the computer)
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
