"""Handles serial connection to Teensy, voice slots allocation and release, packet sending, and watchdog functionality."""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import serial
from protocol import (
    build_all_notes_off,
    build_lfo_packet,
    build_lfo_waveform_packets,
    build_note_off,
    build_note_on,
)
from serial.tools import list_ports

BAUDRATE = 115200
SERIAL_TIMEOUT = 0.1
CONNECT_DELAY_S = 2.0
WATCHDOG_INTERVAL_S = 2.0

TEENSY_MAX_VOICES = 8


def list_com_ports() -> list[str]:
    """List all available COM ports."""
    return [port.device for port in list_ports.comports()]


@dataclass
class WatchdogCallbacks:
    """Callbacks for the watchdog functionality."""

    on_lost: Callable[[], None] | None = None
    on_reconnect_attempt: Callable[[str], None] | None = None
    on_reconnected: Callable[[str], None] | None = None
    on_reconnect_failed: Callable[[str], None] | None = None
    should_auto_reconnect: Callable[[], bool] | None = None
    get_last_port: Callable[[], str | None] | None = None


class SerialClient:
    """Handles serial connection to Teensy, voice slots allocation and release, packet sending, and watchdog functionality.

    Attributes:
        port (str | None): Current COM port
    """

    def __init__(self) -> None:
        self._ser: serial.Serial | None = None
        self.port: str | None = None
        self._connect_thread: threading.Thread | None = None
        self._watchdog_thread: threading.Thread | None = None
        self._watchdog_stop = threading.Event()
        self._watchdog_callbacks = WatchdogCallbacks()
        self._connect_lock = threading.Lock()
        # Map host voice_id -> Teensy slot 0..TEENSY_MAX_VOICES-1
        self._slot_by_voice: dict[str, int] = {}
        self._voice_by_slot: dict[int, str] = {}
        self._slot_order: list[str] = []

    @property
    def is_connected(self) -> bool:
        """Check if the serial connection is established."""
        return self._ser is not None and self._ser.is_open

    # Clears all voice slots
    def clear_voice_slots(self) -> None:
        """Clear all voice slots."""
        self._slot_by_voice.clear()
        self._voice_by_slot.clear()
        self._slot_order.clear()

    def alloc_slot(self, voice_id: str) -> tuple[int, str | None]:
        """Allocate a Teensy voice slot for a voice.

        Returns:
            tuple[int, str | None]: The slot and the voice_id that was stolen if the slot was full.
            If the slot was not full, the voice_id is None.
        """
        if voice_id in self._slot_by_voice:
            if voice_id in self._slot_order:
                self._slot_order.remove(voice_id)
            self._slot_order.append(voice_id)
            return self._slot_by_voice[voice_id], None

        stolen: str | None = None
        if len(self._slot_by_voice) >= TEENSY_MAX_VOICES:
            stolen = self._slot_order.pop(0)
            old_slot = self._slot_by_voice.pop(stolen)
            self._voice_by_slot.pop(old_slot, None)
            slot = old_slot
        else:
            used = set(self._slot_by_voice.values())
            slot = next(i for i in range(TEENSY_MAX_VOICES) if i not in used)

        self._slot_by_voice[voice_id] = slot
        self._voice_by_slot[slot] = voice_id
        self._slot_order.append(voice_id)
        return slot, stolen

    def get_slot(self, voice_id: str) -> int | None:
        """Get the slot for a voice."""
        return self._slot_by_voice.get(voice_id)

    def release_slot(self, voice_id: str) -> int | None:
        """Release a voice slot."""
        slot = self._slot_by_voice.pop(voice_id, None)
        if slot is None:
            return None
        self._voice_by_slot.pop(slot, None)
        if voice_id in self._slot_order:
            self._slot_order.remove(voice_id)
        return slot

    def check_connection(self) -> bool:
        """Check if the serial connection is established."""
        if not self.is_connected or self._ser is None:
            return False

        try:
            return self._ser.is_open and self.port in list_com_ports()
        except Exception:
            return False

    def connect(
        self,
        port: str,
        on_success: Callable[[], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        """Connect to a serial port."""

        def _connect() -> None:
            with self._connect_lock:
                if self.is_connected:
                    if on_success:
                        on_success()
                    return

                try:
                    ser = serial.Serial(port, BAUDRATE, timeout=SERIAL_TIMEOUT)
                    time.sleep(CONNECT_DELAY_S)
                    self._ser = ser
                    self.port = port
                    self.clear_voice_slots()
                    if on_success:
                        on_success()
                except Exception as exc:
                    self._ser = None
                    self.port = None
                    if on_error:
                        on_error(str(exc))

        if self._connect_thread and self._connect_thread.is_alive():
            return

        self._connect_thread = threading.Thread(target=_connect, daemon=True)
        self._connect_thread.start()

    def disconnect(self) -> None:
        """Disconnect from the serial port."""
        if self._ser is not None:
            try:
                if self._ser.is_open:
                    self._ser.close()
            finally:
                self._ser = None
                self.port = None
        self.clear_voice_slots()

    def send(
        self,
        carrier_hz: float,
        modulator_hz: float,
        volume_pct: int,
        mod_depth_pct: int,
        voice_id: int = 0,
        carrier_waveform: str | None = None,
    ) -> str:
        """Send a note on packet to the Teensy."""
        packet = build_note_on(
            carrier_hz,
            modulator_hz,
            volume_pct,
            mod_depth_pct,
            voice_id=voice_id,
            carrier_waveform=carrier_waveform,
        )
        # Writes the packet to the Teensy
        self._write_packet(packet)
        return packet.strip()

    def send_note_off(
        self,
        modulator_hz: float,
        volume_pct: int,
        mod_depth_pct: int,
        voice_id: int = 0,
        carrier_waveform: str | None = None,
    ) -> str:
        """Send a note off packet to the Teensy."""
        packet = build_note_off(
            modulator_hz,
            volume_pct,
            mod_depth_pct,
            voice_id=voice_id,
            carrier_waveform=carrier_waveform,
        )
        # Writes the packet to the Teensy
        self._write_packet(packet)
        return packet.strip()

    def send_all_notes_off(self, volume_pct: int) -> str:
        """Send a all notes off packet to the Teensy."""
        packet = build_all_notes_off(volume_pct)
        self._write_packet(packet)
        self.clear_voice_slots()
        return packet.strip()

    # Sends a global LFO + filter packet to the Teensy
    def send_lfo(
        self,
        rate_hz: float,
        depth_pct: int,
        cutoff_hz: float,
        resonance: float,
    ) -> str:
        """Send a LFO ("L"-)packet to the Teensy."""
        packet = build_lfo_packet(rate_hz, depth_pct, cutoff_hz, resonance)
        self._write_packet(packet)
        return packet.strip()

    def send_lfo_table(self, samples: list[int]) -> str:
        """Send a LFO waveform ("W"-)packet to the Teensy."""
        packets = build_lfo_waveform_packets(samples)
        for packet in packets:
            self._write_packet(packet)
        return f"W,{len(packets)} chunks"

    def _write_packet(self, packet: str) -> None:
        """Write a packet to the Teensy."""
        if not self.is_connected or self._ser is None:
            raise RuntimeError("Not connected with Teensy.")

        try:
            self._ser.write(packet.encode("utf-8"))
        except Exception as exc:
            self.disconnect()
            raise RuntimeError(str(exc)) from exc

    def start_watchdog(self, callbacks: WatchdogCallbacks) -> None:
        """Start the watchdog thread.

        Watch the serial connection and reconnect if it is lost.
        """
        self._watchdog_callbacks = callbacks
        if self._watchdog_thread and self._watchdog_thread.is_alive():
            return

        self._watchdog_stop.clear()

        def _watch() -> None:
            while not self._watchdog_stop.wait(WATCHDOG_INTERVAL_S):
                if self.is_connected and not self.check_connection():
                    self.disconnect()
                    if self._watchdog_callbacks.on_lost:
                        self._watchdog_callbacks.on_lost()
                    continue

                if self.is_connected:
                    continue

                should_reconnect = (
                    self._watchdog_callbacks.should_auto_reconnect
                    and self._watchdog_callbacks.should_auto_reconnect()
                )
                get_last_port = self._watchdog_callbacks.get_last_port
                if not should_reconnect or not get_last_port:
                    continue

                last_port = get_last_port()
                if not last_port or last_port not in list_com_ports():
                    continue

                if self._watchdog_callbacks.on_reconnect_attempt:
                    self._watchdog_callbacks.on_reconnect_attempt(last_port)

                def on_success() -> None:
                    if self._watchdog_callbacks.on_reconnected:
                        self._watchdog_callbacks.on_reconnected(last_port)

                def on_error(message: str) -> None:
                    if self._watchdog_callbacks.on_reconnect_failed:
                        self._watchdog_callbacks.on_reconnect_failed(message)

                self.connect(last_port, on_success=on_success, on_error=on_error)

        self._watchdog_thread = threading.Thread(target=_watch, daemon=True)
        self._watchdog_thread.start()

    def stop_watchdog(self) -> None:
        """Stop the watchdog thread."""
        self._watchdog_stop.set()
