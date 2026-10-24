"""Sound panel: volume, FM presets and the FM / LFO / filter sub-panels."""

import customtkinter as ctk

from synth.safety_limits import MAX_VOLUME_PCT, clamp_volume_pct
from synth.synth_mode_presets import FM_PRESETS
from ui.panels.filter_panel import FilterPanel
from ui.panels.fm_panel import FmPanel
from ui.panels.lfo_panel import LfoPanel
from ui.synth_controller import SynthController
from ui.widgets import set_entry_text, wire_slider_entry


class SoundPanel:
    """Builds the 'Sound Synthesis Configuration' area.

    Args:
        parent: Widget the panel frame is created in.
        controller (SynthController): Application logic.

    Attributes:
        frame (ctk.CTkFrame): The panel frame. The caller places it in the layout.
        fm (FmPanel): FM controls.
        lfo (LfoPanel): LFO controls.
        filter (FilterPanel): Filter controls.
    """

    def __init__(self, parent, controller: SynthController) -> None:
        self.controller = controller
        self.state = controller.state

        self.frame = ctk.CTkFrame(parent)
        self._build()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build(self) -> None:
        sound_frame = self.frame
        sound_frame.grid_columnconfigure(0, weight=1)
        state = self.state

        sound_header = ctk.CTkFrame(sound_frame, fg_color="transparent")
        sound_header.grid(row=0, column=0, padx=12, pady=(12, 8), sticky="ew")
        sound_header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            sound_header,
            text="Sound Synthesis Configuration",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).grid(row=0, column=0, sticky="w")

        self.volume_label = ctk.CTkLabel(
            sound_frame, text=f"Volume: {state.volume_pct} %"
        )
        self.volume_label.grid(row=1, column=0, padx=12, pady=(0, 4), sticky="w")
        volume_controls = ctk.CTkFrame(sound_frame, fg_color="transparent")
        volume_controls.grid(row=2, column=0, padx=12, pady=(0, 8), sticky="ew")
        volume_controls.grid_columnconfigure(0, weight=1)
        self.volume_slider = ctk.CTkSlider(
            volume_controls,
            from_=0,
            to=MAX_VOLUME_PCT,
            number_of_steps=MAX_VOLUME_PCT,
        )
        self.volume_slider.set(state.volume_pct)
        self.volume_slider.grid(row=0, column=0, sticky="ew")
        self.volume_entry = ctk.CTkEntry(volume_controls, width=70)
        self.volume_entry.grid(row=0, column=1, padx=(8, 0), sticky="e")
        wire_slider_entry(
            self.volume_slider,
            self.volume_entry,
            0,
            MAX_VOLUME_PCT,
            self.controller.set_volume,
            decimals=0,
        )

        preset_row = ctk.CTkFrame(sound_frame, fg_color="transparent")
        preset_row.grid(row=3, column=0, padx=12, pady=(0, 8), sticky="w")
        ctk.CTkLabel(preset_row, text="Presets:").grid(
            row=0, column=0, padx=(0, 8), sticky="w"
        )
        preset_names = list(FM_PRESETS)
        active_preset = state.active_preset
        self.preset_var = ctk.StringVar(
            value=active_preset if active_preset in FM_PRESETS else "Custom"
        )
        self.preset_menu = ctk.CTkOptionMenu(
            preset_row,
            variable=self.preset_var,
            values=preset_names or ["No presets"],
            command=self._on_preset_selected,
            width=140,
        )
        self.preset_menu.grid(row=0, column=1, sticky="w")
        self.sync_preset_menu()

        self.fm = FmPanel(sound_frame, self.controller)
        self.fm.frame.grid(row=5, column=0, padx=12, pady=(0, 8), sticky="ew")

        self.lfo = LfoPanel(sound_frame, self.controller)
        self.lfo.frame.grid(row=6, column=0, padx=12, pady=(0, 8), sticky="ew")

        self.filter = FilterPanel(sound_frame, self.controller)
        self.filter.frame.grid(row=7, column=0, padx=12, pady=(0, 8), sticky="ew")

        ctk.CTkLabel(
            sound_frame,
            text=(
                "Control elements are partially limited to safety values. "
                "Defined in safety_limits.py."
            ),
            text_color="gray60",
            anchor="w",
        ).grid(row=8, column=0, padx=12, pady=(0, 12), sticky="ew")

    # ------------------------------------------------------------------
    # Presets
    # ------------------------------------------------------------------

    def sync_preset_menu(self) -> None:
        """Show the active preset ('Custom' if parameters were changed manually)."""
        names = list(FM_PRESETS)
        if not names:
            self.preset_menu.configure(values=["No presets"], state="disabled")
            self.preset_var.set("No presets")
            return
        active = self.state.active_preset
        values = list(names)
        if active not in FM_PRESETS:
            values.append("Custom")
            active = "Custom"
        self.preset_menu.configure(values=values, state="normal")
        self.preset_var.set(active)

    def _on_preset_selected(self, name: str) -> None:
        if name == "Custom" or name not in FM_PRESETS:
            self.sync_preset_menu()
            return
        self.controller.apply_preset(name)

    # ------------------------------------------------------------------
    # Volume
    # ------------------------------------------------------------------

    def adjust_volume(self, delta: int) -> None:
        """Change the volume by `delta` percent (PC keyboard + / -)."""
        new_volume = clamp_volume_pct(self.state.volume_pct + delta)
        self.volume_slider.set(new_volume)
        self.controller.set_volume(new_volume)

    # ------------------------------------------------------------------
    # Sync with the synth state
    # ------------------------------------------------------------------

    def sync_controls(self) -> None:
        """Move all sliders, switches and menus to the values of the synth state."""
        self.fm.sync_controls()
        self.volume_slider.set(self.state.volume_pct)
        self.lfo.sync_controls()
        self.filter.sync_controls()
        self.refresh_entries()
        self.sync_preset_menu()

    def refresh_entries(self) -> None:
        """Update all numeric entries from the synth state."""
        set_entry_text(self.volume_entry, float(self.state.volume_pct), 0)
        self.fm.refresh()
        self.lfo.refresh()
        self.filter.refresh()

    def refresh(self) -> None:
        """Update labels and entries from the synth state."""
        self.volume_label.configure(text=f"Volume: {self.state.volume_pct} %")
        self.refresh_entries()
