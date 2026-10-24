"""Application logic between the GUI panels and the synth/playback layers.

The controller contains everything that is not widget code: the note lifecycle,
reactions to parameter changes, presets, setup application and config persistence.
It never touches a widget directly. UI updates go through the `ControllerView`
protocol, which `SynthApp` implements.

Typical flow of a parameter change (e.g. the volume slider):
    panel -> controller.set_volume() -> SynthState -> OutputRouter -> Teensy / local engine
                                     -> ControllerView (refresh labels, sync menus)
"""

from typing import Callable, Protocol

from playback.local.audio_engine import LocalAudioEngine
from playback.output_router import OutputRouter
from playback.teensy.serial_client import SerialClient
from storage.config_store import AppConfig, save_config
from storage.setup_store import SynthSetup
from synth.fm_utils import compute_modulator_hz
from synth.safety_limits import (
    clamp_carrier_hz,
    clamp_mod_depth_pct,
    clamp_modulator_hz,
    clamp_modulator_ratio,
    clamp_volume_pct,
)
from synth.synth_mode_presets import FM_PRESETS, apply_preset
from synth.synth_state import PC_KEYBOARD_MAPPING, SynthState
from synth.waveforms import (
    WAVETABLE_CARRIER_WAVEFORM,
    carrier_waveform_from_label,
    is_wavetable_carrier,
)


class ControllerView(Protocol):
    """UI hooks the controller needs. Implemented by `SynthApp`."""

    def log(self, message: str) -> None:
        """Append a line to the event log."""

    def refresh_display(self) -> None:
        """Update all labels, entries and status fields from the synth state."""

    def sync_all_controls(self) -> None:
        """Move all sliders, menus and toggles to the values of the synth state."""

    def sync_preset_menu(self) -> None:
        """Update the preset menu (shows 'Custom' when no preset is active)."""

    def sync_carrier_waveform(self) -> None:
        """Update the carrier waveform buttons."""

    def sync_modulator_mode(self) -> None:
        """Show the slider matching the modulator mode (Fix Hz / Ratio)."""

    def show_link_error(self, exc: Exception) -> None:
        """The serial link broke while sending. Update connection controls and status."""


class SynthController:
    """Coordinates synth state, output routing, config persistence and the UI.

    Args:
        config (AppConfig): Persisted GUI settings.
        synth_state (SynthState): Shared synth state.
        serial_client (SerialClient): Serial link to the Teensy.
        audio_engine (LocalAudioEngine): Local playback engine.

    Attributes:
        config (AppConfig): Persisted GUI settings.
        state (SynthState): Shared synth state.
        router (OutputRouter): Sends events to the Teensy or the local engine.
        view (ControllerView | None): The UI, set via `attach_view`.
    """

    def __init__(
        self,
        config: AppConfig,
        synth_state: SynthState,
        serial_client: SerialClient,
        audio_engine: LocalAudioEngine,
    ) -> None:
        self.config = config
        self.state = synth_state
        self.view: ControllerView | None = None
        self._config_contributors: list[Callable[[AppConfig], None]] = []

        self.router = OutputRouter(
            synth_state,
            serial_client,
            audio_engine,
            log=self.log,
            on_link_error=self._on_link_error,
            release_voice=self.note_off,
        )
        self.router.local_audio_enabled = config.local_audio_enabled

    @classmethod
    def from_config(cls, config: AppConfig) -> "SynthController":
        """Create state, serial client and audio engine from the loaded config."""
        key_freqs = {
            key: clamp_carrier_hz(freq)
            for key, freq in {
                **PC_KEYBOARD_MAPPING,
                **config.key_frequencies,
            }.items()
        }
        synth_state = SynthState(
            key_frequencies=key_freqs,
            carrier_waveform=config.carrier_waveform,
            modulator_hz=config.modulator_hz,
            modulator_mode=config.modulator_mode,
            modulator_ratio=config.modulator_ratio,
            volume_pct=config.volume_pct,
            mod_depth_pct=config.mod_depth_pct,
            lfo_rate_hz=config.lfo_rate_hz,
            lfo_depth_pct=config.lfo_depth_pct,
            lfo_preset=config.lfo_preset,
            lfo_interp=config.lfo_interp,
            lfo_points=list(config.lfo_points),
            lfo_table=list(config.lfo_table),
            filter_cutoff_hz=config.filter_cutoff_hz,
            filter_resonance=config.filter_resonance,
            active_preset=config.active_preset,
        )
        return cls(config, synth_state, SerialClient(), LocalAudioEngine())

    def attach_view(self, view: ControllerView) -> None:
        """Connect the UI. Must happen before the first event is processed."""
        self.view = view

    # ------------------------------------------------------------------
    # UI delegates
    # ------------------------------------------------------------------

    def log(self, message: str) -> None:
        """Write a message to the event log (ignored while no view is attached)."""
        if self.view is not None:
            self.view.log(message)

    def refresh_display(self) -> None:
        """Ask the UI to update all displayed values."""
        if self.view is not None:
            self.view.refresh_display()

    def _on_link_error(self, exc: Exception) -> None:
        if self.view is not None:
            self.view.show_link_error(exc)

    # ------------------------------------------------------------------
    # Config persistence
    # ------------------------------------------------------------------

    def add_config_contributor(self, contributor: Callable[[AppConfig], None]) -> None:
        """Register a function which copies widget-owned values into the config.

        It is called on every `save_config()`.
        """
        self._config_contributors.append(contributor)

    def save_config(self) -> None:
        """Copy the synth state (and widget-owned values) into the config and save it."""
        state = self.state
        config = self.config
        config.key_frequencies = dict(state.key_frequencies)
        config.carrier_waveform = state.carrier_waveform
        config.modulator_hz = state.modulator_hz
        config.modulator_mode = state.modulator_mode
        config.modulator_ratio = state.modulator_ratio
        config.volume_pct = state.volume_pct
        config.mod_depth_pct = state.mod_depth_pct
        config.lfo_rate_hz = state.lfo_rate_hz
        config.lfo_depth_pct = state.lfo_depth_pct
        config.lfo_preset = state.lfo_preset
        config.lfo_interp = state.lfo_interp
        config.lfo_points = list(state.lfo_points)
        config.lfo_table = list(state.lfo_table)
        config.filter_cutoff_hz = state.filter_cutoff_hz
        config.filter_resonance = state.filter_resonance
        config.active_preset = state.active_preset
        for contribute in self._config_contributors:
            contribute(config)
        save_config(config)

    # ------------------------------------------------------------------
    # Note lifecycle
    # ------------------------------------------------------------------

    def modulator_for_carrier(self, carrier_hz: float) -> float:
        """Compute the modulator frequency for a carrier frequency (fixed or ratio mode)."""
        return compute_modulator_hz(
            carrier_hz,
            self.state.modulator_mode,
            self.state.modulator_hz,
            self.state.modulator_ratio,
        )

    def recompute_voice_modulators(self) -> None:
        """Recompute the modulator frequency of every sounding voice."""
        self.state.update_voice_modulators(self.modulator_for_carrier)

    def note_on(self, voice_id: str, frequency_hz: float) -> None:
        """Start playing a voice."""
        frequency_hz = clamp_carrier_hz(frequency_hz)
        modulator = self.modulator_for_carrier(frequency_hz)
        stolen = self.state.note_on(voice_id, frequency_hz, modulator)
        if stolen:
            self.router.stop_local_voice(stolen)
        self.refresh_display()
        self.router.voice_on(voice_id)
        self.refresh_display()

    def retune_voice(self, voice_id: str, frequency_hz: float) -> None:
        """Change the frequency of a sounding voice without retriggering it."""
        frequency_hz = clamp_carrier_hz(frequency_hz)
        modulator = self.modulator_for_carrier(frequency_hz)
        if not self.state.retune(voice_id, frequency_hz, modulator):
            self.note_on(voice_id, frequency_hz)
            return
        self.param_update(quiet=True)

    def note_off(self, voice_id: str) -> None:
        """Release a voice (e.g. a released PC keyboard key)."""
        if not self.state.note_off(voice_id):
            return
        self.router.voice_off(voice_id)
        self.refresh_display()

    def release_all_voices(self) -> None:
        """Release all voices in the synth state and on the active output."""
        self.state.all_notes_off()
        self.router.all_notes_off()

    def param_update(self, quiet: bool = False) -> None:
        """Push the current parameters to the sounding voices."""
        self.router.param_update(quiet)
        self.refresh_display()

    def _update_playing_voices(self, recompute_modulators: bool = False) -> None:
        """Apply a parameter change to the voices which are currently sounding."""
        if self.state.is_playing:
            if recompute_modulators:
                self.recompute_voice_modulators()
            self.param_update()

    # ------------------------------------------------------------------
    # FM / volume parameters
    # ------------------------------------------------------------------

    def mark_custom_preset(self) -> None:
        """Called when a parameter was changed manually: no preset is active anymore."""
        self.state.active_preset = "Custom"
        self.view.sync_preset_menu()

    def apply_preset(self, preset_name: str) -> None:
        """Apply a named FM preset."""
        preset = FM_PRESETS.get(preset_name)
        if preset is None:
            return
        apply_preset(self.state, preset_name)
        self.view.sync_all_controls()
        self.save_config()
        self.refresh_display()
        self.log(f"Preset '{preset_name}': {preset.description}")
        self._update_playing_voices(recompute_modulators=True)

    def set_modulator_hz(self, value: float) -> None:
        self.state.modulator_hz = clamp_modulator_hz(value)
        self.mark_custom_preset()
        self.save_config()
        self.refresh_display()
        self._update_playing_voices(recompute_modulators=True)

    def set_volume(self, value: float) -> None:
        self.state.volume_pct = clamp_volume_pct(value)
        self.mark_custom_preset()
        self.save_config()
        self.refresh_display()
        self._update_playing_voices()

    def set_mod_depth(self, value: float) -> None:
        self.state.mod_depth_pct = clamp_mod_depth_pct(value)
        self.mark_custom_preset()
        self.save_config()
        self.refresh_display()
        self._update_playing_voices()

    def set_modulator_ratio(self, value: float) -> None:
        self.state.modulator_ratio = clamp_modulator_ratio(value)
        if self.state.carrier_hz is not None:
            self.state.modulator_hz = compute_modulator_hz(
                self.state.carrier_hz,
                "ratio",
                self.state.modulator_hz,
                self.state.modulator_ratio,
            )
        self.mark_custom_preset()
        self.save_config()
        self.refresh_display()
        self._update_playing_voices(recompute_modulators=True)

    def set_modulator_mode(self, label: str) -> None:
        """Switch between fixed modulator frequency and ratio mode ("Fix Hz" / "Ratio")."""
        self.state.modulator_mode = "ratio" if label == "Ratio" else "fixed"
        if self.state.modulator_mode == "ratio" and self.state.carrier_hz is not None:
            self.state.modulator_hz = compute_modulator_hz(
                self.state.carrier_hz,
                "ratio",
                self.state.modulator_hz,
                self.state.modulator_ratio,
            )
        self.mark_custom_preset()
        self.view.sync_modulator_mode()
        self.save_config()
        self.refresh_display()
        self.log(f"Modulator mode: {label}")
        self._update_playing_voices(recompute_modulators=True)

    def set_carrier_waveform(self, label: str) -> None:
        """Select one of the basic carrier waveforms by its label."""
        self.state.carrier_waveform = carrier_waveform_from_label(label)
        self.view.sync_carrier_waveform()
        self.mark_custom_preset()
        self.save_config()
        self.refresh_display()
        self.log(f"Carrier waveform: {self.state.carrier_waveform_display()}")
        self._update_playing_voices()

    def select_wavetable_carrier(self) -> None:
        """Select the Teensy wavetable as carrier."""
        if is_wavetable_carrier(self.state.carrier_waveform):
            return

        self.state.carrier_waveform = WAVETABLE_CARRIER_WAVEFORM
        self.view.sync_carrier_waveform()
        self.mark_custom_preset()
        self.save_config()
        self.refresh_display()
        self.log(f"Carrier waveform: {self.state.carrier_waveform_display()}")
        if not self.router.teensy_connected:
            self.log(
                "Wavetable only exists on the Teensy, local playback falls back to sine"
            )
        self._update_playing_voices()

    # ------------------------------------------------------------------
    # LFO / filter transmission
    # ------------------------------------------------------------------

    def send_lfo(self) -> None:
        """Send LFO rate/depth and filter settings to the Teensy."""
        self.router.send_lfo()
        self.refresh_display()

    def send_lfo_table(self) -> None:
        """Send the LFO wavetable to the Teensy."""
        self.router.send_lfo_table()

    # ------------------------------------------------------------------
    # Setups
    # ------------------------------------------------------------------

    def apply_setup(self, setup: SynthSetup) -> None:
        """Apply a loaded setup to the synth state and push it to the Teensy."""
        self.state.apply_setup_params(setup.params)
        self.state.setup_name = setup.name
        self.config.last_setup_name = setup.name
        self.view.sync_all_controls()
        self.save_config()
        self.refresh_display()
        self.send_lfo_table()
        self.send_lfo()
        self.log(f"Setup loaded: {setup.name}")
