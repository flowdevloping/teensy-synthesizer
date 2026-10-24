"""Test []
Builds GUI and handles input.

This script provides the main window to either control the audio module or just play around with
sound creation on the local device (when not connected to the audio module).
It composes the GUI panels and wires them to the `SynthController`, which translates user
inputs into events for the `OutputRouter` (Teensy via USB serial OR local sounddevice engine).

Structure:
- `ui/synth_controller.py`: application logic (note lifecycle, parameter changes, config).
- `ui/panels/`: one module per GUI area (connection, display, keyboard, conlang, sound, setup, log).
- `ui/widgets.py`: shared widget helpers (slider + entry wiring, value blocks).
- `playback/output_router.py`: routes events to the Teensy or the local audio engine.

Hardware Dependencies:
- (optional): Teensy 4.1 connected via USB + MAX98357A + Visaton FRWS 5 (4 Ohm)
    IMPORTANT: Make sure to use seperate power sources:
        - 5V USB for the Teensy
        - Lipo 1S for MAX98357A + Visaton FRWS 5, connected via the charging module.
- (optional): MIDI Keyboard connected via USB
"""

import customtkinter as ctk  # Python UI library based on tkinter (standard Python GUI toolkit)

from storage.config_store import load_config
from ui.midi_input import MidiInputHandler
from ui.panels.conlang_panel import ConlangPanel
from ui.panels.connection_panel import ConnectionPanel
from ui.panels.display_panel import DisplayPanel
from ui.panels.keyboard_panel import KeyboardPanel
from ui.panels.log_panel import LogPanel
from ui.panels.setup_panel import SetupPanel
from ui.panels.sound_panel import SoundPanel
from ui.synth_controller import SynthController
from ui.widgets import disable_all_slider_scrolling


class SynthApp(ctk.CTk):
    """Main window: composes the panels and wires them to the controller.

    The app implements the `ControllerView` protocol, i.e. it forwards the controller's
    UI requests (refresh, sync, log) to the panels which own the widgets.

    Attributes:
        controller (SynthController): Application logic, owns config, synth state and router.
        midi_handler (MidiInputHandler): Midi input handler object (see midi_input.py).
        connection_panel (ConnectionPanel): Serial, MIDI and local audio connection.
        display_panel (DisplayPanel): Current values and last packet.
        keyboard_panel (KeyboardPanel): Note buttons and PC keyboard input.
        conlang_panel (ConlangPanel): Conlang playback.
        sound_panel (SoundPanel): Volume, presets, FM / LFO / filter.
        setup_panel (SetupPanel): Save / load / export setups.
        log_panel (LogPanel): Event log.
    """

    def __init__(self) -> None:
        """Creates GUI window initially."""

        super().__init__()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("Sonic HRI Synth")
        self.geometry("800x820")
        self.minsize(600, 520)

        self.controller = SynthController.from_config(load_config())
        self.controller.attach_view(self)
        self.midi_handler = MidiInputHandler()

        self._build_ui()
        disable_all_slider_scrolling(self)
        self.focus_set()
        self.keyboard_panel.bind_keys()
        self.connection_panel.start()
        self.refresh_display()
        self.log("Config loaded")
        self.connection_panel.start_local_audio()
        self.connection_panel.start_watchdog()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        """Build up the high level layout: connection, scrollable controls and log."""

        controller = self.controller

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=0)

        self.connection_panel = ConnectionPanel(self, controller, self.midi_handler)
        self.connection_panel.frame.grid(
            row=0, column=0, padx=16, pady=(16, 8), sticky="ew"
        )

        scroll_frame = ctk.CTkScrollableFrame(self, label_text="")
        scroll_frame.grid(row=1, column=0, padx=16, pady=8, sticky="nsew")
        scroll_frame.grid_columnconfigure(0, weight=1)

        # Rows 0 and 1 of the scroll frame
        self.display_panel = DisplayPanel(scroll_frame, controller.state)

        controls_frame = ctk.CTkFrame(scroll_frame)
        controls_frame.grid(row=2, column=0, pady=(0, 8), sticky="ew")
        controls_frame.grid_columnconfigure(0, weight=1)

        # Rows 0 to 2 of the controls frame
        self.keyboard_panel = KeyboardPanel(
            controls_frame,
            controller,
            on_stop=self.stop_all_sounds,
            adjust_volume=lambda delta: self.sound_panel.adjust_volume(delta),
        )

        self.conlang_panel = ConlangPanel(
            controls_frame, controller, on_stop=self.stop_all_sounds
        )
        self.conlang_panel.frame.grid(
            row=3, column=0, padx=0, pady=(0, 8), sticky="ew"
        )

        self.sound_panel = SoundPanel(controls_frame, controller)
        self.sound_panel.frame.grid(row=4, column=0, padx=0, pady=(0, 8), sticky="ew")

        self.setup_panel = SetupPanel(
            controls_frame, controller, on_stop=self.stop_all_sounds
        )
        self.setup_panel.frame.grid(row=5, column=0, pady=(0, 8), sticky="ew")

        self.log_panel = LogPanel(self)
        self.log_panel.frame.grid(row=2, column=0, padx=16, pady=(0, 16), sticky="ew")

    # ------------------------------------------------------------------
    # ControllerView: UI requests of the controller
    # ------------------------------------------------------------------

    def log(self, message: str) -> None:
        self.log_panel.log(message)

    def refresh_display(self) -> None:
        self.display_panel.refresh()
        self.sound_panel.refresh()
        self.connection_panel.refresh()

    def sync_all_controls(self) -> None:
        self.sound_panel.sync_controls()

    def sync_preset_menu(self) -> None:
        self.sound_panel.sync_preset_menu()

    def sync_carrier_waveform(self) -> None:
        self.sound_panel.fm.sync_carrier_waveform()

    def sync_modulator_mode(self) -> None:
        self.sound_panel.fm.sync_modulator_mode()

    def show_link_error(self, exc: Exception) -> None:
        self.connection_panel.show_send_error(exc)

    # ------------------------------------------------------------------
    # Window level actions
    # ------------------------------------------------------------------

    def stop_all_sounds(self) -> None:
        """Stop conlang playback, release all keys and silence every voice."""
        self.conlang_panel.stop(release=False)
        self.keyboard_panel.clear_pressed_keys()
        self.controller.release_all_voices()
        self.conlang_panel.reset_status()
        self.refresh_display()

    def _on_close(self) -> None:
        self.stop_all_sounds()
        self.keyboard_panel.unbind_keys()
        self.connection_panel.shutdown()
        self.controller.router.shutdown()
        self.controller.save_config()
        self.destroy()


# Entry point of customTkinter app
def run_app() -> None:
    # Create main window of GUI
    app = SynthApp()
    # Keep window opened
    app.mainloop()
