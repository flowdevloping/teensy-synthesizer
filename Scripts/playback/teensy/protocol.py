"""
Contains packet format for Teensy FM synth.

Note packet format:
voiceId,carrierHz,modHz,volumePct,modDepthPct,carrierWave

voiceId -1..7 = per-voice note on/off (-1 = all notes off)
carrierHz  = carrier frequency in Hz (0 = note off)
modulatorHz = modulator frequency in Hz
volumePct   = volume in percent (0..100%)
modDepthPct  = modulation depth in percent (0..100%)
carrierWave  = waveform ID of the Teensy Audio Library (0 sine, 1 saw, 2 square, 3 triangle, 4 wavetable)


LFO/filter packet format:
L,rate,depth,cutoff,res

rate   = LFO frequency in Hz
depth  = LFO depth in percent (0..100, 0 = no wobble)
cutoff = filter cutoff frequency in Hz
res    = filter resonance (Q)

LFO wavetable packet format:
W,offset,count,v0,...,vN-1

offset = sample index in the 256-sample RAM table
count  = number of int16 samples in this chunk (typically 32)
v*     = int16 samples (-32767..32767)

The LFO commands use their own "L," / "W," prefixes because they are global
parameters, not per-voice notes. The shape lives in the RAM table uploaded via W.
"""

"""Contains the class SynthPacket + functions to enable synthesis control via sending messages."""

from dataclasses import dataclass

from synth.lfo_waveform import LFO_TABLE_CHUNK_SIZE, LFO_WAVETABLE_SIZE
from synth.safety_limits import (
    clamp_carrier_hz,
    clamp_filter_cutoff,
    clamp_filter_q,
    clamp_lfo_depth_pct,
    clamp_lfo_rate,
    clamp_mod_depth_pct,
    clamp_modulator_hz,
    clamp_volume_pct,
)
from synth.waveforms import carrier_waveform_id


@dataclass(frozen=True)
class SynthPacket:
    """Package of synthesizer parameters that can be sent, e.g. to the Teensy via serial connection.

    Attributes:
        voice_id (int): ID of the voice to be altered.
        carrier_hz (foat): Frequency of the carrier waveform (FM synth).
        modulator_hz (float): Frequency of the modulator waveform (FM synth).
        volume_pct (int): Volume in percent.
        mod_depth_pct: Modulator depth in percent (FM synth).
        carrier_wave: Shape of the carrier waveform (see waveforms.py for options)
    """

    voice_id: int
    carrier_hz: float
    modulator_hz: float
    volume_pct: int
    mod_depth_pct: int
    carrier_wave: int

    def to_line(self) -> str:
        """Convert the voice packet to a string in the format expected by the Teensy.

        Format: "voiceId,carrierHz,modHz,volumePct,modDepthPct,carrierWave\n"
        """
        return (
            f"{self.voice_id},"
            f"{self.carrier_hz:.2f},"
            f"{self.modulator_hz:.1f},"
            f"{self.volume_pct},"
            f"{self.mod_depth_pct},"
            f"{self.carrier_wave}\n"
        )


def build_voice_packet(
    carrier_hz: float,
    modulator_hz: float,
    volume_pct: int,
    mod_depth_pct: int,
    voice_id: int = 0,
    carrier_waveform: str | None = None,
) -> str:
    """Build a packet to control a voice of the synthesizer.

    Args:
        carrier_hz: Frequency of the carrier waveform (FM synth).
        modulator_hz: Frequency of the modulator waveform (FM synth).
        volume_pct: Volume in percent.
        mod_depth_pct: Modulator depth in percent (FM synth).
        voice_id: ID of the voice to be altered.
        carrier_waveform: Shape of the carrier waveform (see waveforms.py for options).
    """

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
    return packet.to_line()


def build_note_on(
    carrier_hz: float,
    modulator_hz: float,
    volume_pct: int,
    mod_depth_pct: int,
    voice_id: int = 0,
    carrier_waveform: str | None = None,
) -> str:
    """Build a packet to turn a voice on."""
    return build_voice_packet(
        carrier_hz=carrier_hz,
        modulator_hz=modulator_hz,
        volume_pct=volume_pct,
        mod_depth_pct=mod_depth_pct,
        voice_id=voice_id,
        carrier_waveform=carrier_waveform,
    )


def build_note_off(
    modulator_hz: float,
    volume_pct: int,
    mod_depth_pct: int,
    voice_id: int = 0,
    carrier_waveform: str | None = None,
) -> str:
    """Build a packet to turn a single voice off."""
    return build_voice_packet(
        carrier_hz=0.0,
        modulator_hz=modulator_hz,
        volume_pct=volume_pct,
        mod_depth_pct=mod_depth_pct,
        voice_id=voice_id,
        carrier_waveform=carrier_waveform,
    )


def build_all_notes_off(volume_pct: int) -> str:
    """Build a packet to turn all voices off."""
    return build_voice_packet(
        carrier_hz=0.0,
        modulator_hz=0.0,
        volume_pct=volume_pct,
        mod_depth_pct=0,
        voice_id=-1,
    )


def build_lfo_packet(
    rate_hz: float,
    depth_pct: int,
    cutoff_hz: float,
    resonance: float,
) -> str:
    """Build a packet to control the LFO ("L" packet).

    Format: "L,rate_hz,depth_pct,cutoff_hz,resonance\n"
    """
    return (
        "L,"
        f"{clamp_lfo_rate(rate_hz):.2f},"
        f"{clamp_lfo_depth_pct(depth_pct)},"
        f"{clamp_filter_cutoff(cutoff_hz):.2f},"
        f"{clamp_filter_q(resonance):.2f}\n"
    )


def build_lfo_waveform_packets(samples: list[int]) -> list[str]:
    """Build a packet to control the LFO waveform ("W" packet).

    Format: "W,offset,count,value0,...,valueN-1\n"
    """
    values = [max(-32767, min(32767, int(v))) for v in samples]
    if len(values) < LFO_WAVETABLE_SIZE:
        values = values + [0] * (LFO_WAVETABLE_SIZE - len(values))
    else:
        values = values[:LFO_WAVETABLE_SIZE]
    packets: list[str] = []
    for offset in range(0, LFO_WAVETABLE_SIZE, LFO_TABLE_CHUNK_SIZE):
        chunk = values[offset : offset + LFO_TABLE_CHUNK_SIZE]
        joined = ",".join(str(v) for v in chunk)
        packets.append(f"W,{offset},{len(chunk)},{joined}\n")
    return packets
