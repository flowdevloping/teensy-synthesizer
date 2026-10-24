"""Connection panel: Teensy serial link, MIDI keyboard and local audio playback."""

from tkinter import TclError

import customtkinter as ctk

from playback.teensy.serial_client import list_serial_ports
from storage.config_store import AppConfig
from ui.midi_input import MidiCallbacks, MidiInputHandler, list_midi_ports
from ui.synth_controller import SynthController


class ConnectionPanel:
    """Builds the connection area and manages the serial and MIDI connections.

    Args:
        parent: Widget the panel frame is created in.
        controller (SynthController): Application logic.
        midi_handler (MidiInputHandler): MIDI input handler.

    Attributes:
        frame (ctk.CTkFrame): The panel frame. The caller places it in the layout.
    """

    def __init__(
        self,
        parent,
        controller: SynthController,
        midi_handler: MidiInputHandler,
    ) -> None:
        self.controller = controller
        self.midi_handler = midi_handler
        self.state = controller.state
        self.config = controller.config
        self.router = controller.router
        self.serial_client = controller.router.serial_client
        self.audio_engine = controller.router.audio_engine

        self._connect_in_progress = False
        self._midi_connect_in_progress = False

        self.frame = ctk.CTkFrame(parent)
        self._build()
        controller.add_config_contributor(self._contribute_config)

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build(self) -> None:
        frame = self.frame
        frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(frame, text="Serial Connection").grid(
            row=0, column=0, padx=12, pady=12, sticky="w"
        )

        self.port_var = ctk.StringVar(value="")
        self.port_menu = ctk.CTkOptionMenu(
            frame,
            variable=self.port_var,
            values=[""],
            width=180,
        )
        self.port_menu.grid(row=0, column=1, padx=8, pady=12, sticky="w")

        self.refresh_ports_button = ctk.CTkButton(
            frame,
            text="Refresh",
            width=120,
            command=self.refresh_port_list,
        )
        self.refresh_ports_button.grid(row=0, column=2, padx=8, pady=12)

        self.connect_button = ctk.CTkButton(
            frame,
            text="Connect",
            width=120,
            command=self._on_connect,
        )
        self.connect_button.grid(row=0, column=3, padx=8, pady=12)

        self.disconnect_button = ctk.CTkButton(
            frame,
            text="Disconnect",
            width=120,
            command=self._on_disconnect,
            state="disabled",
        )
        self.disconnect_button.grid(row=0, column=4, padx=(8, 12), pady=12)

        self.auto_reconnect_var = ctk.BooleanVar(value=self.config.auto_reconnect)
        self.auto_reconnect_checkbox = ctk.CTkCheckBox(
            frame,
            text="Auto-Reconnect",
            variable=self.auto_reconnect_var,
            command=self._on_auto_reconnect_changed,
        )
        self.auto_reconnect_checkbox.grid(
            row=1, column=0, columnspan=2, padx=12, pady=(0, 12), sticky="w"
        )

        self.status_label = ctk.CTkLabel(
            frame,
            text="State: Disconnected",
            anchor="w",
        )
        self.status_label.grid(
            row=1, column=2, columnspan=3, padx=12, pady=(0, 8), sticky="w"
        )

        ctk.CTkLabel(frame, text="MIDI-Port").grid(
            row=2, column=0, padx=12, pady=(0, 12), sticky="w"
        )

        self.midi_port_var = ctk.StringVar(value="")
        self.midi_port_menu = ctk.CTkOptionMenu(
            frame,
            variable=self.midi_port_var,
            values=[""],
            width=180,
        )
        self.midi_port_menu.grid(row=2, column=1, padx=8, pady=(0, 12), sticky="w")

        self.refresh_midi_button = ctk.CTkButton(
            frame,
            text="Refresh",
            width=120,
            command=self.refresh_midi_list,
        )
        self.refresh_midi_button.grid(row=2, column=2, padx=8, pady=(0, 12))

        self.midi_connect_button = ctk.CTkButton(
            frame,
            text="Connect MIDI",
            width=120,
            command=self._on_midi_connect,
        )
        self.midi_connect_button.grid(row=2, column=3, padx=8, pady=(0, 12))

        self.midi_disconnect_button = ctk.CTkButton(
            frame,
            text="Disconnect MIDI",
            width=120,
            command=self._on_midi_disconnect,
            state="disabled",
        )
        self.midi_disconnect_button.grid(row=2, column=4, padx=(8, 12), pady=(0, 12))

        self.midi_status_label = ctk.CTkLabel(
            frame,
            text="MIDI: Disconnected",
            anchor="w",
        )
        self.midi_status_label.grid(
            row=3, column=0, columnspan=5, padx=12, pady=(0, 8), sticky="w"
        )

        self.local_audio_var = ctk.BooleanVar(value=self.config.local_audio_enabled)
        self.local_audio_checkbox = ctk.CTkCheckBox(
            frame,
            text="Audio playback on local device",
            variable=self.local_audio_var,
            command=self._on_local_audio_changed,
        )
        self.local_audio_checkbox.grid(
            row=4, column=0, columnspan=2, padx=12, pady=(0, 12), sticky="w"
        )

        self.local_audio_status_label = ctk.CTkLabel(
            frame,
            text="Local: —",
            anchor="w",
            text_color="gray70",
        )
        self.local_audio_status_label.grid(
            row=4, column=2, columnspan=3, padx=12, pady=(0, 12), sticky="w"
        )

    def _contribute_config(self, config: AppConfig) -> None:
        config.auto_reconnect = self.auto_reconnect_var.get()
        config.local_audio_enabled = self.local_audio_var.get()

    # ------------------------------------------------------------------
    # Start / stop
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Fill the port lists."""
        self.refresh_port_list()
        self.refresh_midi_list()

    def sync_local_audio_stream(self) -> None:
        """Open or close the local audio stream depending on checkbox and Teensy link."""
        self.router.sync_local_audio_stream()

    def start_watchdog(self) -> None:
        """Start the serial watchdog (auto-reconnect) and the event polling."""
        self.serial_client.set_auto_reconnect(self.auto_reconnect_var.get())
        self.serial_client.set_reconnect_target(
            self.config.last_port,
            self.config.last_port_serial,
        )
        self.serial_client.start_watchdog()
        self._poll_serial_events()

    def shutdown(self) -> None:
        """Stop MIDI input. Called when the window closes."""
        self.midi_handler.stop()

    # ------------------------------------------------------------------
    # Status display
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Update the connection status texts from the synth state."""
        if self.state.connected and self.state.port:
            self.status_label.configure(text=f"Status: Connected ({self.state.port})")
        elif self._connect_in_progress:
            self.status_label.configure(text="Status: Connecting...")
        else:
            self.status_label.configure(text="Status: Disconnected")
        self.refresh_local_audio_status()

    def refresh_local_audio_status(self) -> None:
        if self.serial_client.is_connected:
            text = "Local Playback: Standby (Teensy active)"
        elif self.local_audio_var.get() and self.audio_engine.is_available:
            text = "Local Playback: active"
        elif self.local_audio_var.get() and self.audio_engine.error_message:
            text = "Local Playback: not available"
        else:
            text = "Local: disabled"
        self.local_audio_status_label.configure(text=text)

    def show_send_error(self, exc: Exception) -> None:
        """The link broke while sending: disable the controls and show the error."""
        self._set_connection_controls(False)
        self.status_label.configure(text=f"Status: Send error ({exc})")

    # ------------------------------------------------------------------
    # Local audio
    # ------------------------------------------------------------------

    def _on_local_audio_changed(self) -> None:
        enabled = self.local_audio_var.get()
        self.router.local_audio_enabled = enabled
        self.controller.save_config()
        self.controller.log(f"Local playback {'enabled' if enabled else 'disabled'}")
        self.router.sync_local_audio_stream()

    # ------------------------------------------------------------------
    # Serial connection
    # ------------------------------------------------------------------

    def refresh_port_list(self) -> None:
        ports = list_serial_ports()
        values = ports if ports else ["No port found"]
        self.port_menu.configure(values=values)

        preferred = self.config.last_port
        if preferred and preferred in ports:
            self.port_var.set(preferred)
        elif ports:
            current = self.port_var.get()
            self.port_var.set(current if current in ports else ports[0])
        else:
            self.port_var.set(values[0])

    def _set_connection_controls(self, connected: bool) -> None:
        connect_state = (
            "disabled" if connected or self._connect_in_progress else "normal"
        )
        disconnect_state = "disabled" if not connected else "normal"
        port_state = "disabled" if connected or self._connect_in_progress else "normal"

        self.connect_button.configure(state=connect_state)
        self.disconnect_button.configure(state=disconnect_state)
        self.port_menu.configure(state=port_state)
        self.refresh_ports_button.configure(state=port_state)

    def _on_auto_reconnect_changed(self) -> None:
        self.serial_client.set_auto_reconnect(self.auto_reconnect_var.get())
        self.controller.save_config()
        state = "enabled" if self.auto_reconnect_var.get() else "disabled"
        self.controller.log(f"Auto-Reconnect {state}")

    def _on_connect(self) -> None:
        port = self.port_var.get()
        if not port or port == "No port found":
            self.status_label.configure(text="Status: No valid serial port selected")
            self.controller.log("Connection aborted: no valid serial port")
            return

        self._connect_in_progress = True
        self._set_connection_controls(False)
        self.status_label.configure(text=f"Status: Connecting to {port}...")
        self.controller.log(f"Connecting to {port}...")
        self.frame.update_idletasks()
        self.serial_client.connect(port)

    def _on_disconnect(self) -> None:
        port = self.state.port or self.port_var.get()
        self.router.disconnect_teensy()
        self._set_connection_controls(False)
        self.controller.log(f"Disconnected from {port}")
        self.controller.refresh_display()

    def _poll_serial_events(self) -> None:
        """Handle events of the serial client's background threads (every 200 ms)."""
        while True:
            event = self.serial_client.poll_event()
            if event is None:
                break
            kind = event[0]
            if kind == "lost":
                self._handle_connection_lost()
            elif kind == "attempt":
                self.controller.log(f"Auto-Reconnect: trying {event[1]}")
            elif kind == "reconnected":
                self._handle_auto_reconnected(
                    str(event[1]), _optional_event_text(event, 2)
                )
            elif kind == "failed":
                self.controller.log(f"Auto-Reconnect failed: {event[1]}")
            elif kind == "connected":
                self._handle_connect_success(
                    str(event[1]), _optional_event_text(event, 2)
                )
            elif kind == "connect_error":
                self._handle_connect_error(str(event[1]))
        try:
            self.frame.after(200, self._poll_serial_events)
        except TclError:
            return

    def _remember_serial_target(self, port: str, serial_number: str | None) -> None:
        self.config.last_port = port
        self.config.last_port_serial = serial_number
        self.serial_client.set_reconnect_target(port, serial_number)
        self.refresh_port_list()

    def _handle_connection_lost(self) -> None:
        self.router.teensy_lost()
        self._set_connection_controls(False)
        self.status_label.configure(text="Status: Connection lost")
        self.controller.log("Connection lost")
        self.router.sync_local_audio_stream()

    def _handle_auto_reconnected(self, port: str, serial_number: str | None) -> None:
        self._connect_in_progress = False
        self.router.teensy_connected_to(port)
        self._remember_serial_target(port, serial_number)
        self.controller.save_config()
        self._set_connection_controls(True)
        self.controller.log(f"Auto-Reconnect successful: {port}")
        self.controller.send_lfo_table()
        self.controller.send_lfo()
        self.controller.refresh_display()

    def _handle_connect_success(self, port: str, serial_number: str | None) -> None:
        self._connect_in_progress = False
        self.router.teensy_connected_to(port)
        self._remember_serial_target(port, serial_number)
        self.controller.save_config()
        self._set_connection_controls(True)
        self.controller.log(f"Connected to {port}")
        # Push the current global LFO table + filter state to the freshly connected Teensy
        self.controller.send_lfo_table()
        self.controller.send_lfo()
        self.controller.refresh_display()

    def _handle_connect_error(self, message: str) -> None:
        self._connect_in_progress = False
        self.router.teensy_connect_failed()
        self._set_connection_controls(False)
        self.status_label.configure(text=f"Status: Connection error ({message})")
        self.controller.log(f"Connection error: {message}")
        self.controller.refresh_display()

    # ------------------------------------------------------------------
    # MIDI connection
    # ------------------------------------------------------------------

    def refresh_midi_list(self) -> None:
        ports = list_midi_ports()
        values = ports if ports else ["No MIDI port found"]
        self.midi_port_menu.configure(values=values)

        preferred = self.config.last_midi_port
        if preferred and preferred in ports:
            self.midi_port_var.set(preferred)
        elif ports:
            current = self.midi_port_var.get()
            self.midi_port_var.set(current if current in ports else ports[0])
        else:
            self.midi_port_var.set(values[0])

    def _set_midi_controls(self, connected: bool) -> None:
        connect_state = (
            "disabled" if connected or self._midi_connect_in_progress else "normal"
        )
        disconnect_state = "disabled" if not connected else "normal"
        port_state = (
            "disabled" if connected or self._midi_connect_in_progress else "normal"
        )

        self.midi_connect_button.configure(state=connect_state)
        self.midi_disconnect_button.configure(state=disconnect_state)
        self.midi_port_menu.configure(state=port_state)
        self.refresh_midi_button.configure(state=port_state)

    def _on_midi_connect(self) -> None:
        port = self.midi_port_var.get()
        if not port or port == "No MIDI port found":
            self.midi_status_label.configure(text="MIDI: No valid port selected")
            self.controller.log("MIDI connection aborted: no valid port")
            return

        self._midi_connect_in_progress = True
        self._set_midi_controls(False)
        self.midi_status_label.configure(text=f"MIDI: Connecting to {port}...")
        self.controller.log(f"MIDI: Connecting to {port}...")

        # MIDI callbacks arrive on the MIDI thread: hand them over to the Tk thread.
        after = self.frame.after
        callbacks = MidiCallbacks(
            on_note_on=lambda note, freq: after(0, self._on_midi_note_on, note, freq),
            on_note_off=lambda note: after(0, self._on_midi_note_off, note),
            on_connected=lambda: after(0, self._handle_midi_connected, port),
            on_disconnected=lambda: after(0, self._handle_midi_disconnected),
            on_error=lambda message: after(0, self._handle_midi_error, message),
        )
        self.midi_handler.start(port, callbacks)

    def _handle_midi_connected(self, port: str) -> None:
        self._midi_connect_in_progress = False
        self.config.last_midi_port = port
        self.controller.save_config()
        self._set_midi_controls(True)
        self.midi_status_label.configure(text=f"MIDI: Connected ({port})")
        self.controller.log(f"MIDI connected: {port}")

    def _handle_midi_disconnected(self) -> None:
        self._midi_connect_in_progress = False
        self._set_midi_controls(False)
        self.midi_status_label.configure(text="MIDI: Disconnected")
        self.controller.log("MIDI disconnected")

    def _handle_midi_error(self, message: str) -> None:
        self._midi_connect_in_progress = False
        self.midi_handler.stop()
        self._set_midi_controls(False)
        self.midi_status_label.configure(text=f"MIDI: Error ({message})")
        self.controller.log(f"MIDI Error: {message}")

    def _on_midi_disconnect(self) -> None:
        port = self.midi_handler.port or self.midi_port_var.get()
        self.midi_handler.stop()
        self._set_midi_controls(False)
        self.midi_status_label.configure(text="MIDI: Disconnected")
        self.controller.log(f"MIDI disconnected from {port}")

    def _on_midi_note_on(self, note: int, frequency_hz: float) -> None:
        self.controller.note_on(f"midi:{note}", frequency_hz)

    def _on_midi_note_off(self, note: int) -> None:
        self.controller.note_off(f"midi:{note}")


def _optional_event_text(event: tuple, index: int) -> str | None:
    """Return one event field as text, or None when it is missing."""
    if len(event) <= index or event[index] is None:
        return None
    return str(event[index])
