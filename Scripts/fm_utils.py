"""
Contains utility functions for FM synthesis
"""

from safety_limits import (
    clamp_modulator_for_carrier,
    clamp_modulator_hz,
)

# Calls function to compute the modulator depth for a given carrier frequency, modulator mode, modulator frequency, and modulator ratio
def compute_modulator_hz(
    carrier_hz: float | None,
    modulator_mode: str,
    modulator_hz: float,
    modulator_ratio: float,
) -> float:
    if modulator_mode == "ratio" and carrier_hz is not None:
        return clamp_modulator_for_carrier(carrier_hz, modulator_ratio)
    return clamp_modulator_hz(modulator_hz)
