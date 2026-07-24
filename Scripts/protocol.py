"""
Contains packet format for Teensy FM synth.

format: voiceId,carrierHz,modHz,volumePct,modDepthPct\\n

voiceId 0..7 = per-voice note on/off (carrier 0 = note off)
voiceId -1   = all notes off
"""

from dataclasses import dataclass

from safety_limits import (
    clamp_carrier_hz,
    clamp_mod_depth_pct,
    clamp_modulator_hz,
    clamp_volume_pct,
)

@dataclass(frozen=True)
class SynthPacket:
    voice_id: int
    carrier_hz: float
    modulator_hz: float
    volume_pct: int
    mod_depth_pct: int


def build_packet(
    carrier_hz: float,
    modulator_hz: float,
    volume_pct: int,
    mod_depth_pct: int,
    pure_sine: bool = False,
    voice_id: int = 0,
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
    )
    return (
        f"{packet.voice_id},"
        f"{packet.carrier_hz:.2f},"
        f"{packet.modulator_hz:.1f},"
        f"{packet.volume_pct},"
        f"{packet.mod_depth_pct}\n"
    )


def build_note_off(
    modulator_hz: float,
    volume_pct: int,
    mod_depth_pct: int,
    pure_sine: bool = False,
    voice_id: int = 0,
) -> str:
    if pure_sine:
        return build_packet(0.0, 0.0, volume_pct, 0, pure_sine=True, voice_id=voice_id)
    return build_packet(0.0, modulator_hz, volume_pct, mod_depth_pct, voice_id=voice_id)


def build_all_notes_off(volume_pct: int = 0) -> str:
    return build_packet(0.0, 0.0, volume_pct, 0, pure_sine=True, voice_id=-1)
