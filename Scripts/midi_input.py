"""
Contains:

- list_midi_ports(): Lists all MIDI input ports 
- midi_note_to_hz(): Converts MIDI notes to frequencies

- class MidiInputHandler: Handles MIDI input and calls callbacks based on incoming MIDI messages
"""

import threading
from dataclasses import dataclass
from typing import Callable

from safety_limits import clamp_carrier_hz

# Data class for MIDI callbacks
""" 
    Notes: 
    Callable is a type hint from the typing module indicating that on_note_on should be a function (or other callable)
    that takes two arguments: an int and a float, and returns nothing (None). 
    This helps with code clarity and type checking.
"""
@dataclass
class MidiCallbacks:
    on_note_on: Callable[[int, float], None] | None = None
    on_note_off: Callable[[int], None] | None = None
    on_connected: Callable[[], None] | None = None
    on_disconnected: Callable[[], None] | None = None
    on_error: Callable[[str], None] | None = None

# Lists all MIDI input ports
def list_midi_ports() -> list[str]:
    try:
        import mido

        return list(mido.get_input_names())
    except Exception:
        return []

# Converting MIDI-Keyboard inputs (notes) to frequencies using standart table (A4 = 440Hz, ...)
def midi_note_to_hz(note: int) -> float:
    frequency = 440.0 * (2.0 ** ((note - 69) / 12.0))
    return clamp_carrier_hz(frequency)

# Reads MIDI messages and calls callbacks based on incoming MIDI messages
class MidiInputHandler:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._active_notes: set[int] = set()
        self.port: str | None = None
        self.is_running = False

    # Starts the MIDI input handler
    def start(self, port_name: str, callbacks: MidiCallbacks) -> None:
        self.stop()
        self._stop.clear()
        self.port = port_name

        # Internal function to run the MIDI input handler
        def _run() -> None:
            try:
                import mido

                with mido.open_input(port_name) as port:
                    self.is_running = True
                    if callbacks.on_connected:
                        callbacks.on_connected()

                    for message in port:
                        if self._stop.is_set():
                            break
                        self._handle_message(message, callbacks)
            except Exception as exc:
                if callbacks.on_error:
                    callbacks.on_error(str(exc))
            finally:
                with self._lock:
                    self._active_notes.clear()
                self.is_running = False
                self.port = None
                if callbacks.on_disconnected:
                    callbacks.on_disconnected()

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    # Stops the MIDI input handler
    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None
        with self._lock:
            self._active_notes.clear()
        self.is_running = False
        self.port = None

    # Handles the incoming MIDI messages
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

    # Handles the note on event
    def _handle_note_on(self, note: int, callbacks: MidiCallbacks) -> None:
        with self._lock:
            self._active_notes.add(note)

        if callbacks.on_note_on:
            callbacks.on_note_on(note, midi_note_to_hz(note))

    # Handles the note off event
    def _handle_note_off(self, note: int, callbacks: MidiCallbacks) -> None:
        with self._lock:
            self._active_notes.discard(note)

        if callbacks.on_note_off:
            callbacks.on_note_off(note)
