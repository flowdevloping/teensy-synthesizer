"""
Contains class SerialClient:
- Handles serial connection to Teensy
- Handles voice slots allocation and release
- Handles packet sending
- Handles watchdog functionality
"""

import threading
import time
from dataclasses import dataclass
from typing import Callable

import serial
from serial.tools import list_ports

from protocol import (
    build_all_notes_off,
    build_lfo_packet,
    build_lfo_wavetable_packets,
    build_note_off,
    build_packet,
)


BAUDRATE = 115200
SERIAL_TIMEOUT = 0.1
CONNECT_DELAY_S = 2.0
WATCHDOG_INTERVAL_S = 2.0

TEENSY_MAX_VOICES = 8


def list_com_ports() -> list[str]:
    return [port.device for port in list_ports.comports()]


@dataclass
class WatchdogCallbacks:
    on_lost: Callable[[], None] | None = None
    on_reconnect_attempt: Callable[[str], None] | None = None
    on_reconnected: Callable[[str], None] | None = None
    on_reconnect_failed: Callable[[str], None] | None = None
    should_auto_reconnect: Callable[[], bool] | None = None
    get_last_port: Callable[[], str | None] | None = None


class SerialClient:
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
        return self._ser is not None and self._ser.is_open

    # Clears all voice slots
    def clear_voice_slots(self) -> None:
        self._slot_by_voice.clear()
        self._voice_by_slot.clear()
        self._slot_order.clear()

    # Allocates a Teensy voice slot for a voice
    # Returns (slot, stolen_voice_id_ or _None)
    def alloc_slot(self, voice_id: str) -> tuple[int, str | None]:
        """
        Allocate a Teensy voice slot for voice_id.
        Returns (slot, stolen_voice_id_ or _None).
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

    # Returns the slot for a voice
    def get_slot(self, voice_id: str) -> int | None:
        return self._slot_by_voice.get(voice_id)

    # Releases a voice slot
    def release_slot(self, voice_id: str) -> int | None:
        slot = self._slot_by_voice.pop(voice_id, None)
        if slot is None:
            return None
        self._voice_by_slot.pop(slot, None)
        if voice_id in self._slot_order:
            self._slot_order.remove(voice_id)
        return slot

    # Checks if the serial connection is established
    def check_connection(self) -> bool:
        if not self.is_connected or self._ser is None:
            return False

        try:
            return self._ser.is_open and self.port in list_com_ports()
        except Exception:
            return False

    # Connects to a serial port
    def connect(
        self,
        port: str,
        on_success: Callable[[], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
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

    # Disconnects from the serial port
    def disconnect(self) -> None:
        if self._ser is not None:
            try:
                if self._ser.is_open:
                    self._ser.close()
            finally:
                self._ser = None
                self.port = None
        self.clear_voice_slots()

    # Sends a packet to the Teensy
    def send(
        self,
        carrier_hz: float,
        modulator_hz: float,
        volume_pct: int,
        mod_depth_pct: int,
        pure_sine: bool = False,
        voice_id: int = 0,
        carrier_waveform: str | None = None,
    ) -> str:
        packet = build_packet(
            carrier_hz,
            modulator_hz,
            volume_pct,
            mod_depth_pct,
            pure_sine=pure_sine,
            voice_id=voice_id,
            carrier_waveform=carrier_waveform,
        )
        # Writes the packet to the Teensy
        self._write_packet(packet)
        return packet.strip()

    # Sends a note off packet to the Teensy
    def send_note_off(
        self,
        modulator_hz: float,
        volume_pct: int,
        mod_depth_pct: int,
        pure_sine: bool = False,
        voice_id: int = 0,
        carrier_waveform: str | None = None,
    ) -> str:
        packet = build_note_off(
            modulator_hz,
            volume_pct,
            mod_depth_pct,
            pure_sine=pure_sine,
            voice_id=voice_id,
            carrier_waveform=carrier_waveform,
        )
        # Writes the packet to the Teensy
        self._write_packet(packet)
        return packet.strip()

    # Sends a all notes off packet to the Teensy
    def send_all_notes_off(self, volume_pct: int = 0) -> str:
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
        packet = build_lfo_packet(rate_hz, depth_pct, cutoff_hz, resonance)
        self._write_packet(packet)
        return packet.strip()

    # Function to send the LFO wavetable packets ('W' packets)
    def send_lfo_table(self, samples: list[int]) -> str:
        packets = build_lfo_wavetable_packets(samples)
        for packet in packets:
            self._write_packet(packet)
        return f"W,{len(packets)} chunks"

    # Function to write a packet to the Teensy
    def _write_packet(self, packet: str) -> None:
        if not self.is_connected or self._ser is None:
            raise RuntimeError("Not connected with Teensy.")

        try:
            self._ser.write(packet.encode("utf-8"))
        except Exception as exc:
            self.disconnect()
            raise RuntimeError(str(exc)) from exc

    # Watches the serial connection and reconnects if it is lost
    def start_watchdog(self, callbacks: WatchdogCallbacks) -> None:
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

    # Stops the watchdog thread
    def stop_watchdog(self) -> None:
        self._watchdog_stop.set()
