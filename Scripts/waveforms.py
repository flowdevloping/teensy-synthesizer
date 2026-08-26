"""
Contains the carrier waveform definitions shared by GUI, audio engine (on local audio playback) and Teensy protocol.

ID 0..3 match the waveform constants of the Teensy Audio Library 
(WAVEFORM_SINE, WAVEFORM_SAWTOOTH, WAVEFORM_SQUARE, WAVEFORM_TRIANGLE).
ID 4 selects the wavetable which is stored locally on the Teensy.
"""

from __future__ import annotations

DEFAULT_CARRIER_WAVEFORM = "sine"

# Carrier that plays the wavetable compiled into the firmware
WAVETABLE_CARRIER_WAVEFORM = "wavetable"

# Waveform name -> waveform ID of the Teensy Audio Library
CARRIER_WAVEFORM_IDS: dict[str, int] = {
    "sine": 0,
    "saw": 1,
    "square": 2,
    "triangle": 3,
    "wavetable": 4,
}

# Waveform name -> label shown in the GUI
CARRIER_WAVEFORM_LABELS: dict[str, str] = {
    "sine": "Sine",
    "saw": "Saw",
    "square": "Square",
    "triangle": "Triangle",
    "wavetable": "Wavetable stored on Teensy",
}

# Order of the basic waveforms in the GUI, the wavetable has its own button
CARRIER_WAVEFORM_ORDER: list[str] = ["sine", "saw","square", "triangle"]


# Applies a known waveform name, falls back to the default waveform
def clamp_carrier_waveform(value: object) -> str:
    name = str(value).strip().lower()
    return name if name in CARRIER_WAVEFORM_IDS else DEFAULT_CARRIER_WAVEFORM


# Returns the Teensy waveform ID for a waveform name
def carrier_waveform_id(value: object) -> int:
    return CARRIER_WAVEFORM_IDS[clamp_carrier_waveform(value)]


# Returns the GUI label for a waveform name
def carrier_waveform_label(value: object) -> str:
    return CARRIER_WAVEFORM_LABELS[clamp_carrier_waveform(value)]


# Returns the waveform name for a GUI label
def carrier_waveform_from_label(label: str) -> str:
    for name, text in CARRIER_WAVEFORM_LABELS.items():
        if text == label:
            return name
    return DEFAULT_CARRIER_WAVEFORM


# Returns all GUI labels of the basic waveforms in the configured order
def carrier_waveform_labels() -> list[str]:
    return [CARRIER_WAVEFORM_LABELS[name] for name in CARRIER_WAVEFORM_ORDER]


# Returns True if the waveform is the wavetable stored on the Teensy
def is_wavetable_carrier(value: object) -> bool:
    return clamp_carrier_waveform(value) == WAVETABLE_CARRIER_WAVEFORM
