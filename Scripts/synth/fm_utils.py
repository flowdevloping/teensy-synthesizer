"""This script contains utility functions for FM synthesis."""

from synth.safety_limits import (
    clamp_modulator_for_carrier,
    clamp_modulator_hz,
)

def compute_modulator_hz(
    carrier_hz: float | None,
    modulator_mode: str,
    modulator_hz: float,
    modulator_ratio: float,
    ) -> float:
    """Compute the modulator frequency for the fm synthesis.
    
    Args: 
        carrier_hz (float | None): The carrier frequency in Hz.
        modulator_mode (str): The modulator mode, either "ratio" or "absolute".
        modulator_hz (float): The modulator frequency in Hz.
        modulator_ratio (float): The modulator ratio.

    Returns:
        float: The modulator frequency in Hz.
    """

    if modulator_mode == "ratio" and carrier_hz is not None:
        return clamp_modulator_for_carrier(carrier_hz, modulator_ratio)
    return clamp_modulator_hz(modulator_hz)
