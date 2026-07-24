"""
Contains the base classes for the synth engines
- MODE_LABELS: Dictionary of synth mode labels (FM, Additive, Subtractive, Wavetable, Granular)
- SAMPLE_RATE: Sample rate for the synth engine
- SYNTH_MODES: Dictionary of synth modes (FM, Additive, Subtractive, Wavetable, Granular)
- SynthEngine: Base class for all synth engines
"""

from engines.base import MODE_LABELS, SAMPLE_RATE, SYNTH_MODES, SynthEngine

__all__ = [
    "MODE_LABELS",
    "SAMPLE_RATE",
    "SYNTH_MODES",
    "SynthEngine",
]
