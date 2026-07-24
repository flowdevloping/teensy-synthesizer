"""
Contains presets for different synthesis modes (FM, Additive, Subtractive, Wavetable, Granular)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from safety_limits import MAX_MOD_DEPTH_PCT

# Data class for a mode preset
@dataclass(frozen=True)
class ModePreset:
    name: str
    description: str
    params: dict[str, Any]

# Dictionary of FM presets 
FM_PRESETS: dict[str, ModePreset] = {
    "Standard": ModePreset("Standard", "standard FM sound", {"modulator_hz": 20.0, "mod_depth_pct": 20, "modulator_mode": "fixed", "modulator_ratio": 1.0}),
    "Sci-Fi": ModePreset("Sci-Fi", "metallic, robotic", {"modulator_hz": 45.0, "mod_depth_pct": 55, "modulator_mode": "fixed", "modulator_ratio": 1.0}),
    "Bass": ModePreset("Oscillating", "oscillating", {"modulator_hz": 5.0, "mod_depth_pct": 45, "modulator_mode": "fixed", "modulator_ratio": 1.0}),
    "Organ": ModePreset("Organ", "high modulator frequency", {"modulator_hz": 300.0, "mod_depth_pct": 30, "modulator_mode": "fixed", "modulator_ratio": 1.0}),
    "Clean": ModePreset("Ghost", "ghostly", {"modulator_hz": 8.0, "mod_depth_pct": 8, "modulator_mode": "fixed", "modulator_ratio": 1.0}),
}

# Dictionary of Additive FM presets (Organ, Bright, Hollow)
ADDITIVE_PRESETS: dict[str, ModePreset] = {
    "Organ": ModePreset("Organ", "First 4 harmonics", {"partials": [1.0, 0.5, 0.33, 0.25, 0.0, 0.0, 0.0, 0.0]}),
    "Bright": ModePreset("Bright", "Many overtones", {"partials": [1.0, 0.7, 0.5, 0.4, 0.3, 0.2, 0.15, 0.1]}),
    "Hollow": ModePreset("Hollow", "Odd harmonics", {"partials": [1.0, 0.0, 0.4, 0.0, 0.25, 0.0, 0.15, 0.0]}),
}

# Dictionary of Subtractive FM presets (Warm, Buzz, Pulse)
SUBTRACTIVE_PRESETS: dict[str, ModePreset] = {
    "Warm": ModePreset("Warm", "Saw, soft filter", {"waveform": "saw", "cutoff_hz": 1200.0, "pulse_width": 0.5}),
    "Buzz": ModePreset("Buzz", "Saw, open", {"waveform": "saw", "cutoff_hz": 4500.0, "pulse_width": 0.5}),
    "Pulse": ModePreset("Pulse", "Pulse, narrow filter", {"waveform": "pulse", "cutoff_hz": 900.0, "pulse_width": 0.25}),
}

# Dictionary of Wavetable synth presets (Glass, Grit, Pure)
WAVETABLE_PRESETS: dict[str, ModePreset] = {
    "Glass": ModePreset("Glass", "Sine→Triangle", {"table_a": "sine", "table_b": "triangle", "morph": 0.4, "detune_cents": 0.0}),
    "Grit": ModePreset("Grit", "Saw→Pulse", {"table_a": "saw", "table_b": "pulse", "morph": 0.55, "detune_cents": 7.0}),
    "Pure": ModePreset("Pure", "Sine only", {"table_a": "sine", "table_b": "sine", "morph": 0.0, "detune_cents": 0.0}),
}

# Dictionary of Granular synth presets (Cloud, Scatter, Slow)
GRANULAR_PRESETS: dict[str, ModePreset] = {
    "Cloud": ModePreset("Cloud", "Soft grains", {"grain_ms": 60.0, "density": 10.0, "grain_position": 0.35, "spray": 0.2, "pitch_ratio": 1.0}),
    "Scatter": ModePreset("Scatter", "Short and dense", {"grain_ms": 18.0, "density": 28.0, "grain_position": 0.5, "spray": 0.35, "pitch_ratio": 1.0}),
    "Slow": ModePreset("Slow", "Long grains", {"grain_ms": 120.0, "density": 4.0, "grain_position": 0.2, "spray": 0.1, "pitch_ratio": 0.5}),
}

# Dictionary of mode presets (FM, Additive, Subtractive, Wavetable, Granular)
MODE_PRESETS: dict[str, dict[str, ModePreset]] = {
    "fm": FM_PRESETS,
    "pure_sine": {},
    "additive": ADDITIVE_PRESETS,
    "subtractive": SUBTRACTIVE_PRESETS,
    "wavetable": WAVETABLE_PRESETS,
    "granular": GRANULAR_PRESETS,
}

# Applies a mode preset to the synthesizer state
def apply_mode_preset(state: object, mode: str, preset_name: str) -> None:
    presets = MODE_PRESETS.get(mode, {})
    preset = presets.get(preset_name)
    if preset is None:
        return
    state.active_preset = preset.name
    state.apply_setup_params(preset.params)
