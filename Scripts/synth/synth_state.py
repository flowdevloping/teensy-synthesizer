"""Contains the synthesizer state and functions to manipulate it."""

from __future__ import annotations

from dataclasses import dataclass, field

from synth.lfo_waveform import (
    DEFAULT_LFO_INTERP,
    DEFAULT_LFO_PRESET,
    apply_lfo_preset,
    clamp_lfo_interp,
    clamp_lfo_points,
    clamp_lfo_preset,
    clamp_lfo_table,
    default_lfo_points,
    default_lfo_table,
    lfo_preset_label,
    lfo_state_from_mapping,
    points_to_table,
    sample_points_from_table,
)
from synth.safety_limits import (
    DEFAULT_VOLUME_PCT,
    FILTER_DEFAULT_CUTOFF_HZ,
    FILTER_DEFAULT_Q,
    LFO_DEFAULT_DEPTH_PCT,
    LFO_DEFAULT_RATE_HZ,
    clamp_filter_cutoff,
    clamp_filter_q,
    clamp_lfo_depth_pct,
    clamp_lfo_rate,
)
from synth.waveforms import (
    DEFAULT_CARRIER_WAVEFORM,
    carrier_waveform_label,
    clamp_carrier_waveform,
)

NOTE_MAPPING: dict[str, tuple[str, float]] = {
    "C4": ("261.63", 261.63),
    "D4": ("293.66", 293.66),
    "E4": ("329.63", 329.63),
    "F4": ("349.23", 349.23),
    "G4": ("392.00", 392.00),
    "A4": ("440.00", 440.00),
    "B4": ("493.88", 493.88),
    "C5": ("523.25", 523.25),
}

PC_KEYBOARD_NOTE_KEYS = ["a", "s", "d", "f", "g", "h", "j", "k"]

PC_KEYBOARD_MAPPING: dict[str, float] = {
    key: frequency_hz
    for key, (_, frequency_hz) in zip(PC_KEYBOARD_NOTE_KEYS, NOTE_MAPPING.values())
}

MAX_VOICES = 8


@dataclass
class Voice:
    """Data class for a single voice.

    Attributes:
        voice_id (str): The ID of the voice.
        carrier_hz (float): The carrier frequency.
        modulator_hz (float): The modulator frequency.
    """

    voice_id: str
    carrier_hz: float
    modulator_hz: float


@dataclass
class SynthState:
    """Data class for the synthesizer state.

    Attributes:
        key_frequencies (dict[str, float]): The frequencies of the keyboard notes.
        carrier_hz (float | None): The carrier frequency.
        carrier_waveform (str): The carrier waveform.
        modulator_hz (float): The modulator frequency.
        modulator_mode (str): The modulator mode.
        modulator_ratio (float): The modulator ratio.
        volume_pct (int): The volume percentage.
        mod_depth_pct (int): The modulator depth percentage.
        lfo_rate_hz (float): The LFO rate.
        lfo_depth_pct (int): The LFO depth percentage.
        lfo_preset (str): The LFO preset.
        lfo_interp (str): The LFO interpolation.
        lfo_points (list[float]): The LFO points.
        lfo_table (list[float]): The LFO table.
        filter_cutoff_hz (float): The filter cutoff frequency.
        filter_resonance (float): The filter resonance.
        active_preset (str): The active preset.
        connected (bool): Whether the synthesizer is connected.
        port (str | None): The port of the synthesizer.
        last_packet (str | None): The last packet sent.
        setup_name (str): The name of the setup.
        active_voices (dict[str, Voice]): The active voices.
    """

    key_frequencies: dict[str, float] = field(
        default_factory=lambda: dict(
            PC_KEYBOARD_MAPPING
        )  # lambda function to create a new dict for every instance of SynthState
    )
    carrier_hz: float | None = None
    carrier_waveform: str = DEFAULT_CARRIER_WAVEFORM
    modulator_hz: float = 20.0
    modulator_mode: str = "fixed"
    modulator_ratio: float = 1.0
    volume_pct: int = DEFAULT_VOLUME_PCT
    mod_depth_pct: int = 20
    lfo_rate_hz: float = LFO_DEFAULT_RATE_HZ
    lfo_depth_pct: int = LFO_DEFAULT_DEPTH_PCT
    lfo_preset: str = DEFAULT_LFO_PRESET
    lfo_interp: str = DEFAULT_LFO_INTERP
    lfo_points: list[float] = field(default_factory=default_lfo_points)
    lfo_table: list[float] = field(default_factory=default_lfo_table)
    filter_cutoff_hz: float = FILTER_DEFAULT_CUTOFF_HZ
    filter_resonance: float = FILTER_DEFAULT_Q
    active_preset: str = "Standard"
    connected: bool = False
    port: str | None = None
    last_packet: str | None = None
    setup_name: str = ""
    active_voices: dict[str, Voice] = field(default_factory=dict)
    _voice_order: list[str] = field(default_factory=list)

    @property
    def is_playing(self) -> bool:
        """Return whether the synthesizer is playing."""
        return len(self.active_voices) > 0

    def primary_voice(self) -> Voice | None:
        """Return the primary voice (the last voice to be turned on)."""
        if not self._voice_order:
            return None
        return self.active_voices.get(self._voice_order[-1])

    def note_on(
        self, voice_id: str, carrier_hz: float, modulator_hz: float
    ) -> str | None:
        """Turn on a voice."""
        stolen: str | None = None
        if voice_id in self.active_voices:
            if voice_id in self._voice_order:
                self._voice_order.remove(voice_id)
        elif len(self.active_voices) >= MAX_VOICES and self._voice_order:
            stolen = self._voice_order.pop(0)
            self.active_voices.pop(stolen, None)

        self.active_voices[voice_id] = Voice(
            voice_id=voice_id,
            carrier_hz=carrier_hz,
            modulator_hz=modulator_hz,
        )
        self._voice_order.append(voice_id)
        self._sync_legacy_carrier()
        return stolen

    def note_off(self, voice_id: str) -> bool:
        """Turn off a voice."""
        if voice_id not in self.active_voices:
            return False
        del self.active_voices[voice_id]
        if voice_id in self._voice_order:
            self._voice_order.remove(voice_id)
        self._sync_legacy_carrier()
        return True

    def retune(self, voice_id: str, carrier_hz: float, modulator_hz: float) -> bool:
        """Update the pitch of an already-held voice without retriggering note-on."""
        voice = self.active_voices.get(voice_id)
        if voice is None:
            return False
        voice.carrier_hz = carrier_hz
        voice.modulator_hz = modulator_hz
        self._sync_legacy_carrier()
        return True

    def all_notes_off(self) -> None:
        """Turn off all voices and reset the carrier frequency."""
        self.active_voices.clear()
        self._voice_order.clear()
        self.carrier_hz = None

    def update_voice_modulators(self, compute_modulator) -> None:
        """Update the modulator frequency for all voices based on the carrier frequency."""
        for voice in self.active_voices.values():
            voice.modulator_hz = compute_modulator(voice.carrier_hz)
        primary = self.primary_voice()
        if primary is not None:
            self.modulator_hz = primary.modulator_hz

    def engine_params(self) -> dict:
        """Return the parameters for the active local engine."""
        return {
            "volume_pct": self.volume_pct,
            "mod_depth_pct": self.mod_depth_pct,
            "modulator_hz": self.modulator_hz,
            "carrier_waveform": self.carrier_waveform,
        }

    def setup_params_dict(self) -> dict:
        """Return the parameters for the setup JSON."""
        return {
            "volume_pct": self.volume_pct,
            "carrier_waveform": self.carrier_waveform,
            "modulator_hz": self.modulator_hz,
            "modulator_mode": self.modulator_mode,
            "modulator_ratio": self.modulator_ratio,
            "mod_depth_pct": self.mod_depth_pct,
            "lfo_rate_hz": self.lfo_rate_hz,
            "lfo_depth_pct": self.lfo_depth_pct,
            "lfo_preset": self.lfo_preset,
            "lfo_interp": self.lfo_interp,
            "lfo_points": list(self.lfo_points),
            "lfo_table": list(self.lfo_table),
            "filter_cutoff_hz": self.filter_cutoff_hz,
            "filter_resonance": self.filter_resonance,
            "active_preset": self.active_preset,
        }

    def apply_setup_params(self, params: dict) -> None:
        """Apply the parameters for the setup JSON."""
        if "volume_pct" in params:
            self.volume_pct = int(params["volume_pct"])
        if "carrier_waveform" in params:
            self.carrier_waveform = clamp_carrier_waveform(params["carrier_waveform"])
        if "modulator_hz" in params:
            self.modulator_hz = float(params["modulator_hz"])
        if "modulator_mode" in params:
            self.modulator_mode = str(params["modulator_mode"])
        if "modulator_ratio" in params:
            self.modulator_ratio = float(params["modulator_ratio"])
        if "mod_depth_pct" in params:
            self.mod_depth_pct = int(params["mod_depth_pct"])
        if "lfo_rate_hz" in params:
            self.lfo_rate_hz = clamp_lfo_rate(float(params["lfo_rate_hz"]))
        if "lfo_depth_pct" in params:
            self.lfo_depth_pct = clamp_lfo_depth_pct(params["lfo_depth_pct"])
        if any(
            key in params
            for key in (
                "lfo_preset",
                "lfo_interp",
                "lfo_points",
                "lfo_table",
                "lfo_shape",
            )
        ):
            preset, interp, points, table = lfo_state_from_mapping(params)
            self.lfo_preset = preset
            self.lfo_interp = interp
            self.lfo_points = points
            self.lfo_table = table
        if "filter_cutoff_hz" in params:
            self.filter_cutoff_hz = clamp_filter_cutoff(
                float(params["filter_cutoff_hz"])
            )
        if "filter_resonance" in params:
            self.filter_resonance = clamp_filter_q(float(params["filter_resonance"]))
        if "active_preset" in params:
            self.active_preset = str(params["active_preset"])

    def _sync_legacy_carrier(self) -> None:
        """Synchronize the carrier frequency with the primary voice (the last voice to be turned on)."""
        primary = self.primary_voice()
        if primary is None:
            self.carrier_hz = None
        else:
            self.carrier_hz = primary.carrier_hz
            self.modulator_hz = primary.modulator_hz

    def carrier_display(self) -> str:
        """Return the carrier frequency display."""
        if not self.active_voices:
            return "—"
        if len(self.active_voices) == 1:
            voice = next(iter(self.active_voices.values()))
            return f"{voice.carrier_hz:.2f} Hz"
        primary = self.primary_voice()
        if primary is None:
            return "—"
        return f"{primary.carrier_hz:.2f} +{len(self.active_voices) - 1}"

    def carrier_waveform_display(self) -> str:
        """Return the carrier waveform display."""
        return carrier_waveform_label(self.carrier_waveform)

    def lfo_preset_display(self) -> str:
        """Return the LFO preset display."""
        return lfo_preset_label(self.lfo_preset)

    def set_lfo_preset(self, preset: str) -> None:
        """Set the LFO preset."""
        name, interp, points, table = apply_lfo_preset(preset)
        self.lfo_preset = name
        self.lfo_interp = interp
        self.lfo_points = points
        self.lfo_table = table

    def rebuild_lfo_from_points(self, mark_custom: bool = True) -> None:
        """Rebuild the LFO waveform from canvas points."""
        self.lfo_points = clamp_lfo_points(self.lfo_points)
        self.lfo_interp = clamp_lfo_interp(self.lfo_interp)
        self.lfo_table = points_to_table(self.lfo_points, self.lfo_interp)
        if not mark_custom:
            return
        if self.lfo_preset == "snh" and self.lfo_interp == "step":
            return
        self.lfo_preset = "custom"

    def set_lfo_table(self, table: object, preset: str = "custom") -> None:
        """Set the LFO table."""
        self.lfo_table = clamp_lfo_table(table)
        self.lfo_points = (
            clamp_lfo_points(self.lfo_points)
            if self.lfo_points
            else default_lfo_points()
        )
        self.lfo_points = sample_points_from_table(self.lfo_table)
        self.lfo_preset = clamp_lfo_preset(preset)

    def modulator_display(self) -> str:
        """Return the modulator frequency display.

        If the modulator mode is "ratio", the display shows the modulator ratio.
        Otherwise, the display shows the modulator frequency.
        """
        if self.modulator_mode == "ratio":
            if self.carrier_hz is not None:
                return f"{self.modulator_hz:.1f} Hz ({self.modulator_ratio:.2f}x)"
            return f"{self.modulator_ratio:.2f}x"
        return f"{self.modulator_hz:.1f} Hz"

    def volume_display(self) -> str:
        """Return the volume display."""
        return f"{self.volume_pct} %"

    def mod_depth_display(self) -> str:
        """Return the modulator depth display (percentage)."""
        return f"{self.mod_depth_pct} %"
