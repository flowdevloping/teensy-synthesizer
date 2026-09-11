"""
Contains packet format for Teensy FM synth.

Note packet format: voiceId,carrierHz,modHz,volumePct,modDepthPct,carrierWave

voiceId -1..7 = per-voice note on/off (-1 = all notes off)
carrierHz  = carrier frequency in Hz (0 = note off)
modulatorHz = modulator frequency in Hz
volumePct   = volume in percent (0..100%)
modDepthPct  = modulation depth in percent (0..100%)
carrierWave  = waveform ID of the Teensy Audio Library (0 sine, 1 saw, 2 square, 3 triangle, 4 wavetable)


LFO/filter packet format: L,rate,depth,shape,cutoff,res

rate   = LFO frequency in Hz
depth  = LFO depth in percent (0..100, 0 = no wobble)
shape  = LFO shape ID (0 sine, 1 triangle, 2 ramp, 3 square)
cutoff = filter cutoff frequency in Hz
res    = filter resonance (Q)

The LFO command uses its own "L," prefix (not the positional note format) because it is
a global parameter, not a per-voice note.
"""

from dataclasses import dataclass

from safety_limits import (
    clamp_carrier_hz,
    clamp_filter_cutoff,
    clamp_filter_q,
    clamp_lfo_depth_pct,
    clamp_lfo_rate,
    clamp_mod_depth_pct,
    clamp_modulator_hz,
    clamp_volume_pct,
)
from waveforms import carrier_waveform_id, lfo_shape_id

@dataclass(frozen=True)
class SynthPacket:
    voice_id: int
    carrier_hz: float
    modulator_hz: float
    volume_pct: int
    mod_depth_pct: int
    carrier_wave: int


def build_packet(
    carrier_hz: float,
    modulator_hz: float,
    volume_pct: int,
    mod_depth_pct: int,
    pure_sine: bool = False,
    voice_id: int = 0,
    carrier_waveform: str | None = None,
) -> str:
    if pure_sine:
        modulator_value = 0.0
        mod_depth_value = 0
    else:
        modulator_value = clamp_modulator_hz(modulator_hz)
        mod_depth_value = clamp_mod_depth_pct(mod_depth_pct)

    packet = SynthPacket(
        voice_id=int(voice_id),
        carrier_hz=clamp_carrier_hz(carrier_hz),
        modulator_hz=modulator_value,
        volume_pct=clamp_volume_pct(volume_pct),
        mod_depth_pct=mod_depth_value,
        carrier_wave=carrier_waveform_id(carrier_waveform),
    )
    return (
        f"{packet.voice_id},"
        f"{packet.carrier_hz:.2f},"
        f"{packet.modulator_hz:.1f},"
        f"{packet.volume_pct},"
        f"{packet.mod_depth_pct},"
        f"{packet.carrier_wave}\n"
    )


def build_note_off(
    modulator_hz: float,
    volume_pct: int,
    mod_depth_pct: int,
    pure_sine: bool = False,
    voice_id: int = 0,
    carrier_waveform: str | None = None,
) -> str:
    if pure_sine:
        return build_packet(
            0.0,
            0.0,
            volume_pct,
            0,
            pure_sine=True,
            voice_id=voice_id,
            carrier_waveform=carrier_waveform,
        )
    return build_packet(
        0.0,
        modulator_hz,
        volume_pct,
        mod_depth_pct,
        voice_id=voice_id,
        carrier_waveform=carrier_waveform,
    )


def build_all_notes_off(volume_pct: int = 0) -> str:
    return build_packet(0.0, 0.0, volume_pct, 0, pure_sine=True, voice_id=-1)


def build_lfo_packet(
    rate_hz: float,
    depth_pct: int,
    shape: str | int,
    cutoff_hz: float,
    resonance: float,
) -> str:
    shape_value = shape if isinstance(shape, int) else lfo_shape_id(shape)
    return (
        "L,"
        f"{clamp_lfo_rate(rate_hz):.2f},"
        f"{clamp_lfo_depth_pct(depth_pct)},"
        f"{int(shape_value)},"
        f"{clamp_filter_cutoff(cutoff_hz):.2f},"
        f"{clamp_filter_q(resonance):.2f}\n"
    )
