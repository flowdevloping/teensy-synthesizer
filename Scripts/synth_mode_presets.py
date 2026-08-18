"""
Contains presets (configurations) for FM synthesis
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ModePreset:
    name: str
    description: str
    params: dict[str, Any]


FM_PRESETS: dict[str, ModePreset] = {
    "Standard": ModePreset("Standard", "standard FM sound", {"modulator_hz": 20.0, "mod_depth_pct": 20, "modulator_mode": "fixed", "modulator_ratio": 1.0}),
    "Sci-Fi": ModePreset("Sci-Fi", "metallic, robotic", {"modulator_hz": 45.0, "mod_depth_pct": 55, "modulator_mode": "fixed", "modulator_ratio": 1.0}),
    "Bass": ModePreset("Oscillating", "oscillating", {"modulator_hz": 5.0, "mod_depth_pct": 45, "modulator_mode": "fixed", "modulator_ratio": 1.0}),
    "Organ": ModePreset("Organ", "high modulator frequency", {"modulator_hz": 300.0, "mod_depth_pct": 30, "modulator_mode": "fixed", "modulator_ratio": 1.0}),
    "Clean": ModePreset("Ghost", "ghostly", {"modulator_hz": 8.0, "mod_depth_pct": 8, "modulator_mode": "fixed", "modulator_ratio": 1.0}),
}


def apply_preset(state: object, preset_name: str) -> None:
    preset = FM_PRESETS.get(preset_name)
    if preset is None:
        return
    state.active_preset = preset.name
    state.apply_setup_params(preset.params)
