"""
Contains classes: 
- Voice: Data class for a single voice (only parameters)
- SynthState: Data class for the synthesizer state (parameters and functions)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from safety_limits import DEFAULT_VOLUME_PCT

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

KEYBOARD_NOTE_KEYS = ["a", "s", "d", "f", "g", "h", "j", "k"]

KEYBOARD_MAPPING: dict[str, float] = {
    key: frequency_hz
    for key, (_, frequency_hz) in zip(KEYBOARD_NOTE_KEYS, NOTE_MAPPING.values())
}

MAX_VOICES = 8

# Data class for a single voice
@dataclass
class Voice:
    voice_id: str
    carrier_hz: float
    modulator_hz: float

# Data class for the synthesizer state
@dataclass
class SynthState:
    synth_mode: str = "fm"
    carrier_hz: float | None = None
    modulator_hz: float = 20.0
    modulator_mode: str = "fixed"
    modulator_ratio: float = 1.0
    volume_pct: int = DEFAULT_VOLUME_PCT
    mod_depth_pct: int = 20
    active_preset: str = "Standard"
    pure_sine_test: bool = False
    # Additive
    partials: list[float] = field(
        default_factory=lambda: [1.0, 0.5, 0.33, 0.25, 0.0, 0.0, 0.0, 0.0]
    )
    # Number of currently active harmonics (H1..H{partial_count}), 4..8
    partial_count: int = 4
    # Subtractive
    waveform: str = "saw"
    cutoff_hz: float = 2000.0
    pulse_width: float = 0.5
    # Wavetable
    table_a: str = "sine"
    table_b: str = "saw"
    morph: float = 0.0
    detune_cents: float = 0.0
    # Granular
    grain_ms: float = 40.0
    density: float = 12.0
    grain_position: float = 0.3
    spray: float = 0.15
    pitch_ratio: float = 1.0
    connected: bool = False
    port: str | None = None
    last_packet: str | None = None
    setup_name: str = ""
    active_voices: dict[str, Voice] = field(default_factory=dict)
    _voice_order: list[str] = field(default_factory=list)

    @property
    def is_playing(self) -> bool:
        return len(self.active_voices) > 0

    # Only classic FM / Pure Sine can talk to current Teensy firmware
    @property
    def serial_allowed(self) -> bool:
        return self.synth_mode in ("fm", "pure_sine")

    # Returns the primary voice
    def primary_voice(self) -> Voice | None:
        if not self._voice_order:
            return None
        return self.active_voices.get(self._voice_order[-1])

    # Turns on a voice
    def note_on(self, voice_id: str, carrier_hz: float, modulator_hz: float) -> str | None:
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

    # Turns off a voice
    def note_off(self, voice_id: str) -> bool:
        if voice_id not in self.active_voices:
            return False
        del self.active_voices[voice_id]
        if voice_id in self._voice_order:
            self._voice_order.remove(voice_id)
        self._sync_legacy_carrier()
        return True

    # Turns off all voices
    def all_notes_off(self) -> None:
        self.active_voices.clear()
        self._voice_order.clear()
        self.carrier_hz = None

    # Updates the modulators for all voices
    def update_voice_modulators(self, compute_modulator) -> None:
        for voice in self.active_voices.values():
            voice.modulator_hz = compute_modulator(voice.carrier_hz)
        primary = self.primary_voice()
        if primary is not None:
            self.modulator_hz = primary.modulator_hz

    # Returns the parameters for the active local engine
    def engine_params(self) -> dict:
        base = {"volume_pct": self.volume_pct}
        if self.synth_mode in ("fm", "pure_sine"):
            base.update(
                {
                    "mod_depth_pct": self.mod_depth_pct,
                    "pure_sine": self.synth_mode == "pure_sine" or self.pure_sine_test,
                    "modulator_hz": self.modulator_hz,
                }
            )
        elif self.synth_mode == "additive":
            # Only the active harmonics should sound; mask the rest
            parts = list(self.partials)
            for index in range(self.partial_count, len(parts)):
                parts[index] = 0.0
            base["partials"] = parts
        elif self.synth_mode == "subtractive":
            base.update(
                {
                    "waveform": self.waveform,
                    "cutoff_hz": self.cutoff_hz,
                    "pulse_width": self.pulse_width,
                }
            )
        elif self.synth_mode == "wavetable":
            base.update(
                {
                    "table_a": self.table_a,
                    "table_b": self.table_b,
                    "morph": self.morph,
                    "detune_cents": self.detune_cents,
                }
            )
        elif self.synth_mode == "granular":
            base.update(
                {
                    "grain_ms": self.grain_ms,
                    "density": self.density,
                    "position": self.grain_position,
                    "spray": self.spray,
                    "pitch_ratio": self.pitch_ratio,
                }
            )
        return base

    # Returns the parameters for the setup JSON
    def setup_params_dict(self) -> dict:
        return {
            "volume_pct": self.volume_pct,
            "modulator_hz": self.modulator_hz,
            "modulator_mode": self.modulator_mode,
            "modulator_ratio": self.modulator_ratio,
            "mod_depth_pct": self.mod_depth_pct,
            "pure_sine_test": self.pure_sine_test,
            "active_preset": self.active_preset,
            "partials": list(self.partials),
            "partial_count": self.partial_count,
            "waveform": self.waveform,
            "cutoff_hz": self.cutoff_hz,
            "pulse_width": self.pulse_width,
            "table_a": self.table_a,
            "table_b": self.table_b,
            "morph": self.morph,
            "detune_cents": self.detune_cents,
            "grain_ms": self.grain_ms,
            "density": self.density,
            "grain_position": self.grain_position,
            "spray": self.spray,
            "pitch_ratio": self.pitch_ratio,
        }

    # Applies the parameters for the setup JSON
    def apply_setup_params(self, params: dict) -> None:
        if "volume_pct" in params:
            self.volume_pct = int(params["volume_pct"])
        if "modulator_hz" in params:
            self.modulator_hz = float(params["modulator_hz"])
        if "modulator_mode" in params:
            self.modulator_mode = str(params["modulator_mode"])
        if "modulator_ratio" in params:
            self.modulator_ratio = float(params["modulator_ratio"])
        if "mod_depth_pct" in params:
            self.mod_depth_pct = int(params["mod_depth_pct"])
        if "pure_sine_test" in params:
            self.pure_sine_test = bool(params["pure_sine_test"])
        if "active_preset" in params:
            self.active_preset = str(params["active_preset"])
        if "partials" in params:
            parts = [float(p) for p in params["partials"][:8]]
            while len(parts) < 8:
                parts.append(0.0)
            self.partials = parts
            # Legacy setups/presets have no explicit count: derive it from the
            # highest non-zero harmonic so all intended partials stay audible.
            if "partial_count" not in params:
                highest = max((i for i, p in enumerate(parts) if p > 0.0), default=3)
                self.partial_count = max(4, min(8, highest + 1))
        if "partial_count" in params:
            self.partial_count = max(4, min(8, int(params["partial_count"])))
        if "waveform" in params:
            self.waveform = str(params["waveform"])
        if "cutoff_hz" in params:
            self.cutoff_hz = float(params["cutoff_hz"])
        if "pulse_width" in params:
            self.pulse_width = float(params["pulse_width"])
        if "table_a" in params:
            self.table_a = str(params["table_a"])
        if "table_b" in params:
            self.table_b = str(params["table_b"])
        if "morph" in params:
            self.morph = float(params["morph"])
        if "detune_cents" in params:
            self.detune_cents = float(params["detune_cents"])
        if "grain_ms" in params:
            self.grain_ms = float(params["grain_ms"])
        if "density" in params:
            self.density = float(params["density"])
        if "grain_position" in params:
            self.grain_position = float(params["grain_position"])
        if "spray" in params:
            self.spray = float(params["spray"])
        if "pitch_ratio" in params:
            self.pitch_ratio = float(params["pitch_ratio"])

    # Synchronizes the carrier frequency with the primary voice
    def _sync_legacy_carrier(self) -> None:
        primary = self.primary_voice()
        if primary is None:
            self.carrier_hz = None
        else:
            self.carrier_hz = primary.carrier_hz
            self.modulator_hz = primary.modulator_hz

    # Returns the carrier frequency display
    def carrier_display(self) -> str:
        if not self.active_voices:
            return "—"
        if len(self.active_voices) == 1:
            voice = next(iter(self.active_voices.values()))
            return f"{voice.carrier_hz:.2f} Hz"
        primary = self.primary_voice()
        if primary is None:
            return "—"
        return f"{primary.carrier_hz:.2f} +{len(self.active_voices) - 1}"

    # Returns the modulator frequency display
    def modulator_display(self) -> str:
        if self.modulator_mode == "ratio":
            if self.carrier_hz is not None:
                return f"{self.modulator_hz:.1f} Hz ({self.modulator_ratio:.2f}x)"
            return f"{self.modulator_ratio:.2f}x"
        return f"{self.modulator_hz:.1f} Hz"

    # Returns the volume display
    def volume_display(self) -> str:
        return f"{self.volume_pct} %"

    # Returns the mod depth display
    def mod_depth_display(self) -> str:
        return f"{self.mod_depth_pct} %"
