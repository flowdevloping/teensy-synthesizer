"""Manage MIDI input handler lifecycle, handle MIDI inputs and convert them into frequencies.

Utilizes python library 'mido' to do that.

Hardware Dependencies:
    - MIDI Keyboard connected via USB
"""

import threading
from collections.abc import Callable
from dataclasses import dataclass

import mido
from synth.safety_limits import clamp_carrier_hz


# @dataclass creates automatically __init__ and __repr__, therefore we don't need to define them manually.
@dataclass
class MidiCallbacks:
    """Contains callbacks for MIDI input handler to handle MIDI events.

    Attributes:
        on_note_on: Callback function for note on event.
        on_note_off: Callback function for note off event.
        on_connected: Callback function for connected event.
        on_disconnected: Callback function for disconnected event.
        on_error: Callback function for error event.
    """

    on_note_on: Callable[[int, float], None] | None = (
        None  # Means that on_note_on can be either a function ('Callable') that takes two arguments (int and float) and returns None or None.
    )
    on_note_off: Callable[[int], None] | None = None
    on_connected: Callable[[], None] | None = None
    on_disconnected: Callable[[], None] | None = None
    on_error: Callable[[str], None] | None = None


def list_midi_ports() -> list[str]:
    """List all MIDI input ports."""
    try:
        return list(mido.get_input_names())
    except (OSError, RuntimeError) as e:
        # Catch backend failures, missing drivers, or permission issues
        print(f"Hardware I/O Error scanning MIDI ports: {e}")
        return []
    except ValueError as e:
        # Catch malformed port names from the operating system
        print(f"Data error reading MIDI ports: {e}")
        return []


def midi_note_to_hz(note: int) -> float:
    """Convert MIDI note to frequency value in Hz using standard table (A4 = 440Hz, ...)."""
    frequency = 440.0 * (2.0 ** ((note - 69) / 12.0))
    return clamp_carrier_hz(frequency)


class MidiInputHandler:
    """Read MIDI messages and call callbacks based on incoming MIDI messages.

    Attributes:
        port (str | None): Name of the MIDI input port.
        is_running (bool): Flag indicating if the MIDI input handler is running.

    Functions:
        start(port_name: str, callbacks: MidiCallbacks) -> None: Start the MIDI input handler.
        stop() -> None: Stop the MIDI input handler.
    """

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()  # self._lock is a threading.Lock() instance used to synchronize access to shared resources (like self._active_notes) to prevent race conditions in a multithreaded environment.
        self._active_notes: set[int] = set()
        self.port: str | None = None
        self.is_running = False

    def start(self, port_name: str, callbacks: MidiCallbacks) -> None:
        """Start the MIDI input handler."""
        # Stop the MIDI input handler if it is already running
        self.stop()
        self._stop.clear()
        self.port = port_name

        # Run the MIDI input handler
        def _run() -> None:
            connected = False
            try:
                with mido.open_input(port_name) as port:
                    self.is_running = True
                    connected = True
                    if callbacks.on_connected:
                        callbacks.on_connected()
                    for message in port:
                        if self._stop.is_set():
                            break
                        try:
                            self._handle_message(message, callbacks)
                        except Exception as e:
                            print(f"Error handling MIDI message: {e}")
            except (OSError, RuntimeError, ValueError) as e:
                if callbacks.on_error:
                    callbacks.on_error(str(e))
            except Exception:
                print("Unexpected MIDI handler error")
                if callbacks.on_error:
                    callbacks.on_error("Unexpected MIDI handler error")
            finally:
                with self._lock:
                    self._active_notes.clear()
                self.is_running = False
                self.port = None
                if connected and callbacks.on_disconnected:
                    callbacks.on_disconnected()

        # Create a new thread to run the MIDI input handler
        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the MIDI input handler."""
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None
        with self._lock:
            self._active_notes.clear()
        self.is_running = False
        self.port = None

    def _handle_message(self, message: object, callbacks: MidiCallbacks) -> None:
        msg_type = getattr(message, "type", "")
        if msg_type == "note_on":
            velocity = getattr(message, "velocity", 0)
            note = getattr(message, "note", 0)
            if velocity == 0:
                self._handle_note_off(note, callbacks)
            else:
                self._handle_note_on(note, callbacks)
        elif msg_type == "note_off":
            note = getattr(message, "note", 0)
            self._handle_note_off(note, callbacks)

    def _handle_note_on(self, note: int, callbacks: MidiCallbacks) -> None:
        with self._lock:
            self._active_notes.add(note)
        if callbacks.on_note_on:
            callbacks.on_note_on(note, midi_note_to_hz(note))

    def _handle_note_off(self, note: int, callbacks: MidiCallbacks) -> None:
        with self._lock:
            self._active_notes.discard(note)
        if callbacks.on_note_off:
            callbacks.on_note_off(note)
