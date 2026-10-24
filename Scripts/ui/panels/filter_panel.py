"""Filter panel: cutoff frequency and resonance."""

import customtkinter as ctk

from synth.safety_limits import (
    FILTER_MAX_CUTOFF_HZ,
    FILTER_MAX_Q,
    FILTER_MIN_CUTOFF_HZ,
    FILTER_MIN_Q,
    clamp_filter_cutoff,
    clamp_filter_q,
)
from ui.synth_controller import SynthController
from ui.widgets import (
    add_labeled_slider,
    add_teensy_only_hint,
    set_entry_text,
    wire_slider_entry,
)


class FilterPanel:
    """Builds the filter controls. The filter only works on the Teensy.

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

    def _build(self) -> None:
        panel = self.frame
        panel.grid_columnconfigure(0, weight=1)
        state = self.state

        header = ctk.CTkFrame(panel, fg_color="transparent")
        header.grid(row=0, column=0, columnspan=2, pady=(4, 4), sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header,
            text="Filter Cutoff",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, sticky="w")
        add_teensy_only_hint(header, "Filter Cutoff", row=1)

        self.filter_cutoff_label = ctk.CTkLabel(
            panel, text=f"Filter cutoff: {state.filter_cutoff_hz:.0f} Hz"
        )
        self.filter_cutoff_slider = ctk.CTkSlider(
            panel, from_=FILTER_MIN_CUTOFF_HZ, to=FILTER_MAX_CUTOFF_HZ
        )
        self.filter_cutoff_slider.set(state.filter_cutoff_hz)
        self.filter_cutoff_entry = ctk.CTkEntry(panel, width=70)

        self.filter_resonance_label = ctk.CTkLabel(
            panel, text=f"Filter resonance (Q): {state.filter_resonance:.2f}"
        )
        self.filter_resonance_slider = ctk.CTkSlider(
            panel,
            from_=FILTER_MIN_Q,
            to=FILTER_MAX_Q,
            number_of_steps=int((FILTER_MAX_Q - FILTER_MIN_Q) * 100),
        )
        self.filter_resonance_slider.set(state.filter_resonance)
        self.filter_resonance_entry = ctk.CTkEntry(panel, width=70)

        add_labeled_slider(
            panel,
            0,
            self.filter_cutoff_label,
            self.filter_cutoff_slider,
            self.filter_cutoff_entry,
        )
        add_labeled_slider(
            panel,
            1,
            self.filter_resonance_label,
            self.filter_resonance_slider,
            self.filter_resonance_entry,
        )

        wire_slider_entry(
            self.filter_cutoff_slider,
            self.filter_cutoff_entry,
            FILTER_MIN_CUTOFF_HZ,
            FILTER_MAX_CUTOFF_HZ,
            self._on_cutoff_changed,
            decimals=0,
        )
        wire_slider_entry(
            self.filter_resonance_slider,
            self.filter_resonance_entry,
            FILTER_MIN_Q,
            FILTER_MAX_Q,
            self._on_resonance_changed,
            decimals=2,
        )

    def _on_cutoff_changed(self, value: float) -> None:
        self.state.filter_cutoff_hz = clamp_filter_cutoff(value)
        self.controller.save_config()
        self.controller.send_lfo()

    def _on_resonance_changed(self, value: float) -> None:
        self.state.filter_resonance = clamp_filter_q(value)
        self.controller.save_config()
        self.controller.send_lfo()

    def sync_controls(self) -> None:
        """Move the sliders to the values of the synth state."""
        self.filter_cutoff_slider.set(self.state.filter_cutoff_hz)
        self.filter_resonance_slider.set(self.state.filter_resonance)

    def refresh(self) -> None:
        """Update labels and entries from the synth state."""
        state = self.state
        self.filter_cutoff_label.configure(
            text=f"Filter cutoff: {state.filter_cutoff_hz:.0f} Hz"
        )
        self.filter_resonance_label.configure(
            text=f"Filter resonance (Q): {state.filter_resonance:.2f}"
        )
        set_entry_text(self.filter_cutoff_entry, float(state.filter_cutoff_hz), 0)
        set_entry_text(self.filter_resonance_entry, float(state.filter_resonance), 2)
