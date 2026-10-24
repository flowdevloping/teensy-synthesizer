"""Display panel: current carrier/modulator/volume/depth values and the last packet."""

import customtkinter as ctk

from synth.safety_limits import DEFAULT_VOLUME_PCT
from synth.synth_state import SynthState
from ui.widgets import create_value_block


class DisplayPanel:
    """Builds the four value blocks and the 'Last package' line.

    The widgets are created directly in `parent` (rows 0 and 1, column 0).

    Args:
        parent: Widget (grid layout) the display widgets are created in.
        synth_state (SynthState): Shared synth state.
    """

    def __init__(self, parent, synth_state: SynthState) -> None:
        self.state = synth_state

        display_frame = ctk.CTkFrame(parent)
        display_frame.grid(row=0, column=0, pady=(0, 8), sticky="ew")
        for col in range(4):
            display_frame.grid_columnconfigure(col, weight=1)

        self.carrier_value_label = create_value_block(
            display_frame, 0, "Carrier-Frequency", "—"
        )
        self.modulator_value_label = create_value_block(
            display_frame, 1, "Modulator-Frequency", "20.0 Hz"
        )
        self.volume_value_label = create_value_block(
            display_frame, 2, "Volume", f"{DEFAULT_VOLUME_PCT} %"
        )
        self.mod_depth_value_label = create_value_block(
            display_frame, 3, "Modulator-Depth", "20 %"
        )

        self.packet_label = ctk.CTkLabel(
            parent,
            text="Last Package: —",
            anchor="w",
        )
        self.packet_label.grid(row=1, column=0, pady=(0, 8), sticky="ew")

    def refresh(self) -> None:
        """Update the displayed values from the synth state."""
        state = self.state
        self.carrier_value_label.configure(text=state.carrier_display())
        self.modulator_value_label.configure(text=state.modulator_display())
        self.volume_value_label.configure(text=state.volume_display())
        self.mod_depth_value_label.configure(text=state.mod_depth_display())
        packet_text = state.last_packet or "—"
        self.packet_label.configure(text=f"Last package: {packet_text}")
