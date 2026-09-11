"""
Contains: 
- MAX and MIN values for parameters (to make sure nothing gets damaged)
- Clamp functions to apply configured value boundaries
"""

# Default Volume
DEFAULT_VOLUME_PCT = 10

# Maximum Volume 
MAX_VOLUME_PCT = 100

# Maximum Modulation Depth
MAX_MOD_DEPTH_PCT = 100

# Carrier Frequency
MIN_CARRIER_HZ = 0.0
MAX_CARRIER_HZ = 2000.0

# Modulator Frequency
MIN_MODULATOR_HZ = 0.0
MAX_MODULATOR_HZ = 300.0

# Modulator Ratio
MIN_MODULATOR_RATIO = 0.25
MAX_MODULATOR_RATIO = 4.0

# LFO Rate (matches LfoMinHz/LfoMaxHz in AudioLfo)
LFO_MIN_RATE_HZ = 0.01
LFO_MAX_RATE_HZ = 100.0
LFO_DEFAULT_RATE_HZ = 2.0

# LFO Depth (percent, 0 = no wobble)
LFO_MAX_DEPTH_PCT = 100
LFO_DEFAULT_DEPTH_PCT = 0

# Filter Cutoff Frequency
FILTER_MIN_CUTOFF_HZ = 20.0
FILTER_MAX_CUTOFF_HZ = 12000.0
FILTER_DEFAULT_CUTOFF_HZ = 12000.0

# Filter Resonance (Q)
FILTER_MIN_Q = 0.7
FILTER_MAX_Q = 5.0
FILTER_DEFAULT_Q = 0.7

# Keyboard Step
VOLUME_KEYBOARD_STEP = 5

# Firmware Parameters (Teensy firmware boundaries)
FIRMWARE_MAX_AMPLITUDE = 1.0
FIRMWARE_MAX_MOD_DEPTH = 0.7

# Envelope Parameters
ENVELOPE_ATTACK_MS = 60.0
ENVELOPE_RELEASE_MS = 150.0

# Modulator Fade Time
MODULATOR_FADE_MS = 50.0

# Clamping function to apply configured value boundaries
def clamp_volume_pct(value: int | float) -> int:
    return max(0, min(MAX_VOLUME_PCT, int(round(value))))


def clamp_mod_depth_pct(value: int | float) -> int:
    return max(0, min(MAX_MOD_DEPTH_PCT, int(round(value))))


def clamp_carrier_hz(value: float) -> float:
    if value <= 0.0:
        return 0.0
    return max(MIN_CARRIER_HZ, min(MAX_CARRIER_HZ, float(value)))


def clamp_modulator_hz(value: float) -> float:
    return max(MIN_MODULATOR_HZ, min(MAX_MODULATOR_HZ, float(value)))


def clamp_modulator_ratio(value: float) -> float:
    return max(MIN_MODULATOR_RATIO, min(MAX_MODULATOR_RATIO, round(float(value), 2)))


def clamp_modulator_for_carrier(carrier_hz: float, ratio: float) -> float:
    computed = carrier_hz * clamp_modulator_ratio(ratio)
    return clamp_modulator_hz(computed)


def clamp_lfo_rate(value: float) -> float:
    return max(LFO_MIN_RATE_HZ, min(LFO_MAX_RATE_HZ, float(value)))


def clamp_lfo_depth_pct(value: int | float) -> int:
    return max(0, min(LFO_MAX_DEPTH_PCT, int(round(value))))


def clamp_filter_cutoff(value: float) -> float:
    return max(FILTER_MIN_CUTOFF_HZ, min(FILTER_MAX_CUTOFF_HZ, float(value)))


def clamp_filter_q(value: float) -> float:
    return max(FILTER_MIN_Q, min(FILTER_MAX_Q, round(float(value), 2)))
