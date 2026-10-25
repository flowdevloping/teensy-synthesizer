"""FM panel: carrier waveform, modulator mode / frequency / ratio and modulation depth."""

import customtkinter as ctk

from synth.safety_limits import (
    MAX_MOD_DEPTH_PCT,
    MAX_MODULATOR_HZ,
    MAX_MODULATOR_RATIO,
    MIN_MODULATOR_HZ,
    MIN_MODULATOR_RATIO,
)
from synth.waveforms import (
    WAVETABLE_CARRIER_WAVEFORM,
    carrier_waveform_label,
    carrier_waveform_labels,
    is_wavetable_carrier,
)
from gui.synth_controller import SynthController
from gui.widgets import add_labeled_slider, set_entry_text, wire_slider_entry


class FmPanel:
    """Builds the FM controls. Value changes are forwarded to the controller.

    Args:
        parent: Widget the panel frame is created in.
        controller (SynthController): Application logic.

    Attributes:
        frame (ctk.CTkFrame): The panel frame. The caller places it in the layout.
    """

    def __init__(self, parent, controller: SynthController) -> None:
        self.controller = controller
        self.state = controller.state

        self.frame = ctk.CTkFrame(parent, fg_color="transparent")
        self._build()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build(self) -> None:
        fm = self.frame
        fm.grid_columnconfigure(0, weight=1)
        state = self.state

        carrier_waveform_row = ctk.CTkFrame(fm, fg_color="transparent")
        carrier_waveform_row.grid(
            row=0, column=0, columnspan=2, pady=(0, 6), sticky="w"
        )
        ctk.CTkLabel(carrier_waveform_row, text="Carrier waveform").grid(
            row=0, column=0, padx=(0, 8), sticky="w"
        )
        self.carrier_waveform_var = ctk.StringVar(
            value=carrier_waveform_label(state.carrier_waveform)
        )
        self.carrier_waveform_switch = ctk.CTkSegmentedButton(
            carrier_waveform_row,
            values=carrier_waveform_labels(),
            variable=self.carrier_waveform_var,
            command=self.controller.set_carrier_waveform,
        )
        self.carrier_waveform_switch.grid(row=0, column=1, sticky="w")

        self.wavetable_button = ctk.CTkButton(
            carrier_waveform_row,
            text=carrier_waveform_label(WAVETABLE_CARRIER_WAVEFORM),
            width=150,
            command=self.controller.select_wavetable_carrier,
        )
        self.wavetable_button.grid(row=0, column=2, padx=(8, 0), sticky="w")
        self.sync_carrier_waveform()

        modulator_mode_row = ctk.CTkFrame(fm, fg_color="transparent")
        modulator_mode_row.grid(row=1, column=0, columnspan=2, sticky="w")
        ctk.CTkLabel(modulator_mode_row, text="Modulator mode").grid(
            row=0, column=0, padx=(0, 8), sticky="w"
        )
        self.modulator_mode_var = ctk.StringVar(
            value="Ratio" if state.modulator_mode == "ratio" else "Fix Hz"
        )
        self.modulator_mode_switch = ctk.CTkSegmentedButton(
            modulator_mode_row,
            values=["Fix Hz", "Ratio"],
            variable=self.modulator_mode_var,
            command=self.controller.set_modulator_mode,
        )
        self.modulator_mode_switch.grid(row=0, column=1, sticky="w")

        self.modulator_hz_frame = ctk.CTkFrame(fm, fg_color="transparent")
        self.modulator_hz_frame.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.modulator_hz_frame.grid_columnconfigure(0, weight=1)
        self.ratio_frame = ctk.CTkFrame(fm, fg_color="transparent")
        self.ratio_frame.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.ratio_frame.grid_columnconfigure(0, weight=1)

        self.modulator_label = ctk.CTkLabel(
            self.modulator_hz_frame,
            text=f"Modulator: {state.modulator_hz:.1f} Hz",
        )
        self.modulator_slider = ctk.CTkSlider(
            self.modulator_hz_frame,
            from_=MIN_MODULATOR_HZ,
            to=MAX_MODULATOR_HZ,
            number_of_steps=int(MAX_MODULATOR_HZ - MIN_MODULATOR_HZ),
        )
        self.modulator_slider.set(state.modulator_hz)
        self.modulator_entry = ctk.CTkEntry(self.modulator_hz_frame, width=70)
        self.ratio_label = ctk.CTkLabel(
            self.ratio_frame,
            text=f"Ratio (Modulator Frequency / Carrier Frequency): {state.modulator_ratio:.2f}x",
        )
        self.ratio_slider = ctk.CTkSlider(
            self.ratio_frame,
            from_=MIN_MODULATOR_RATIO,
            to=MAX_MODULATOR_RATIO,
            number_of_steps=int((MAX_MODULATOR_RATIO - MIN_MODULATOR_RATIO) * 100),
        )
        self.ratio_slider.set(state.modulator_ratio)
        self.ratio_entry = ctk.CTkEntry(self.ratio_frame, width=70)
        self.mod_depth_label = ctk.CTkLabel(
            fm,
            text=self._mod_depth_label_text(),
        )
        self.mod_depth_slider = ctk.CTkSlider(
            fm,
            from_=0,
            to=MAX_MOD_DEPTH_PCT,
            number_of_steps=MAX_MOD_DEPTH_PCT,
        )
        self.mod_depth_slider.set(state.mod_depth_pct)
        self.mod_depth_entry = ctk.CTkEntry(fm, width=70)
        add_labeled_slider(
            self.modulator_hz_frame,
            0,
            self.modulator_label,
            self.modulator_slider,
            self.modulator_entry,
        )
        add_labeled_slider(
            self.ratio_frame,
            0,
            self.ratio_label,
            self.ratio_slider,
            self.ratio_entry,
        )
        add_labeled_slider(
            fm, 1, self.mod_depth_label, self.mod_depth_slider, self.mod_depth_entry
        )
        wire_slider_entry(
            self.modulator_slider,
            self.modulator_entry,
            MIN_MODULATOR_HZ,
            MAX_MODULATOR_HZ,
            self.controller.set_modulator_hz,
            decimals=1,
        )
        wire_slider_entry(
            self.ratio_slider,
            self.ratio_entry,
            MIN_MODULATOR_RATIO,
            MAX_MODULATOR_RATIO,
            self.controller.set_modulator_ratio,
            decimals=2,
        )
        wire_slider_entry(
            self.mod_depth_slider,
            self.mod_depth_entry,
            0,
            MAX_MOD_DEPTH_PCT,
            self.controller.set_mod_depth,
            decimals=0,
        )
        self.sync_modulator_mode()

    # ------------------------------------------------------------------
    # Sync with the synth state
    # ------------------------------------------------------------------

    # Slider caption: Morph for the Teensy wavetable, otherwise FM modulator depth
    def _mod_depth_label_text(self) -> str:
        pct = self.state.mod_depth_pct
        if is_wavetable_carrier(self.state.carrier_waveform):
            return f"Morph: {pct} %"
        return f"Modulator depth (FM intensity): {pct} %"

    # Shows the active carrier: Either one of the basic waveforms or the Teensy wavetable
    def sync_carrier_waveform(self) -> None:
        if is_wavetable_carrier(self.state.carrier_waveform):
            # An empty value deselects every segment of the segmented button
            self.carrier_waveform_var.set("")
            self.wavetable_button.configure(fg_color="#1f6aa5", hover_color="#144870")
        else:
            self.carrier_waveform_var.set(
                carrier_waveform_label(self.state.carrier_waveform)
            )
            self.wavetable_button.configure(fg_color="gray30", hover_color="gray40")

    def sync_modulator_mode(self) -> None:
        """Show the slider belonging to the current modulator mode."""
        if self.state.modulator_mode == "ratio":
            self.modulator_hz_frame.grid_remove()
            self.ratio_frame.grid()
        else:
            self.ratio_frame.grid_remove()
            self.modulator_hz_frame.grid()

    def sync_controls(self) -> None:
        """Move sliders and switches to the values of the synth state."""
        state = self.state
        self.modulator_slider.set(state.modulator_hz)
        self.ratio_slider.set(state.modulator_ratio)
        self.mod_depth_slider.set(state.mod_depth_pct)
        self.modulator_mode_var.set(
            "Ratio" if state.modulator_mode == "ratio" else "Fix Hz"
        )
        self.sync_carrier_waveform()
        self.sync_modulator_mode()

    def refresh(self) -> None:
        """Update labels and entries from the synth state."""
        state = self.state
        self.modulator_label.configure(text=f"Modulator: {state.modulator_display()}")
        self.ratio_label.configure(
            text=f"Ratio to note: {state.modulator_ratio:.2f}x → {state.modulator_hz:.1f} Hz"
            if state.carrier_hz is not None
            else f"Ratio to note: {state.modulator_ratio:.2f}x"
        )
        self.mod_depth_label.configure(text=self._mod_depth_label_text())
        set_entry_text(self.modulator_entry, float(state.modulator_hz), 1)
        set_entry_text(self.ratio_entry, float(state.modulator_ratio), 2)
        set_entry_text(self.mod_depth_entry, float(state.mod_depth_pct), 0)
