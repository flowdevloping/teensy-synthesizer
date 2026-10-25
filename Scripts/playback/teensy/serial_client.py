"""Handles serial connection to Teensy, voice slots allocation and release, packet sending, and watchdog functionality."""

import queue
import threading
import time
from dataclasses import dataclass

import serial
from serial.tools import list_ports

from playback.teensy.protocol import (
    build_all_notes_off,
    build_lfo_packet,
    build_lfo_waveform_packets,
    build_note_off,
    build_note_on,
)

BAUDRATE = 115200
SERIAL_TIMEOUT = 0.1
# PJRC / Teensy USB vendor ID. Device paths (COM6, /dev/ttyACM0) are not stable.
TEENSY_VID = 0x16C0
PROBE_SETTLE_S = 0.25
REOPEN_SETTLE_S = 0.3
CONNECT_WAIT_S = 4.0
WATCHDOG_INTERVAL_S = 2.0

TEENSY_MAX_VOICES = 8

SerialEvent = tuple[str | None, ...]


@dataclass(frozen=True)
class SerialPortInfo:
    """One currently visible serial device.

    Attributes:
        device (str): OS path, for example 'COM6' or '/dev/ttyACM0'.
        serial_number (str | None): USB serial number, stable across replug.
        vid (int | None): USB vendor ID.
        pid (int | None): USB product ID.
    """

    device: str
    serial_number: str | None
    vid: int | None
    pid: int | None


def list_port_infos() -> list[SerialPortInfo]:
    """List visible serial devices, including USB identity."""
    ports: list[SerialPortInfo] = []
    for port in list_ports.comports():
        serial_number = port.serial_number or None
        ports.append(
            SerialPortInfo(
                device=port.device,
                serial_number=serial_number,
                vid=port.vid,
                pid=port.pid,
            )
        )
    return ports


def list_serial_ports() -> list[str]:
    """List device paths of all visible serial ports."""
    return [port.device for port in list_port_infos()]


def resolve_teensy_port(
    ports: list[SerialPortInfo],
    *,
    serial_number: str | None,
    last_device: str | None,
) -> SerialPortInfo | None:
    """Pick the current path of the same Teensy.

    A known USB serial number only matches that device. Without one, the saved
    path is used, then a single Teensy vendor ID. Several candidates are left
    unresolved.
    """
    if serial_number:
        matches = [port for port in ports if port.serial_number == serial_number]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            for port in matches:
                if port.device == last_device:
                    return port
            return None
        if last_device:
            for port in ports:
                if port.device == last_device and port.serial_number in (
                    None,
                    serial_number,
                ):
                    return port
        return None

    if last_device:
        for port in ports:
            if port.device == last_device:
                return port

    teensy_ports = [port for port in ports if port.vid == TEENSY_VID]
    if len(teensy_ports) == 1:
        return teensy_ports[0]
    return None


def _open_port(device: str) -> serial.Serial:
    """Open a serial port without asserting DTR or RTS."""
    ser = serial.Serial()
    ser.port = device
    ser.baudrate = BAUDRATE
    ser.timeout = SERIAL_TIMEOUT
    ser.dtr = False
    ser.rts = False
    ser.open()
    return ser


def _probe(ser: serial.Serial) -> bool:
    """Return whether the handle still talks to a device."""
    try:
        if not ser.is_open:
            return False
        _ = ser.in_waiting
        return True
    except (OSError, serial.SerialException):
        return False


def _close_quietly(ser: serial.Serial | None) -> None:
    """Close a serial handle, ignoring errors."""
    if ser is None:
        return
    try:
        if ser.is_open:
            ser.close()
    except (OSError, serial.SerialException):
        return


class SerialClient:
    """Handles serial connection to Teensy, voice slots allocation and release, packet sending, and watchdog functionality.

    Attributes:
        port (str | None): Current serial device path.
    """

    def __init__(self) -> None:
        self._ser: serial.Serial | None = None
        self.port: str | None = None
        self._connect_thread: threading.Thread | None = None
        self._watchdog_thread: threading.Thread | None = None
        self._watchdog_stop = threading.Event()
        self._connect_lock = threading.Lock()
        self._target_lock = threading.Lock()
        self._reconnect_enabled = False
        self._target_device: str | None = None
        self._target_serial: str | None = None
        self._events: queue.Queue[SerialEvent] = queue.Queue()
        # Map host voice_id -> Teensy slot 0..TEENSY_MAX_VOICES-1
        self._slot_by_voice: dict[str, int] = {}
        self._voice_by_slot: dict[int, str] = {}
        self._slot_order: list[str] = []

    @property
    def is_connected(self) -> bool:
        """Check if the serial connection is established."""
        return self._ser is not None and self._ser.is_open

    def set_auto_reconnect(self, enabled: bool) -> None:
        """Store whether the watchdog may reconnect. Called from the GUI thread."""
        with self._target_lock:
            self._reconnect_enabled = enabled

    def set_reconnect_target(
        self,
        device: str | None,
        serial_number: str | None,
    ) -> None:
        """Store the Teensy the watchdog should find again. Called from the GUI thread."""
        with self._target_lock:
            self._target_device = device
            self._target_serial = serial_number

    def poll_event(self) -> SerialEvent | None:
        """Return the next watchdog or connect event, if one is waiting."""
        try:
            return self._events.get_nowait()
        except queue.Empty:
            return None

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
        """Check whether the open handle still reaches the same device."""
        if not self.is_connected or self._ser is None or self.port is None:
            return False
        if not _probe(self._ser):
            return False
        with self._target_lock:
            serial_number = self._target_serial
        resolved = resolve_teensy_port(
            list_port_infos(),
            serial_number=serial_number,
            last_device=self.port,
        )
        return resolved is not None and resolved.device == self.port

    def connect(
        self,
        port: str,
        *,
        source: str = "manual",
        serial_number: str | None = None,
    ) -> None:
        """Connect to a serial port.

        Args:
            port (str): Requested device path. The opened path may differ after
                the Teensy re-enumerates.
            source (str): 'manual' or 'watchdog'. Selects the result event.
            serial_number (str | None): USB serial number to follow. Manual
                connects read it from the selected port.
        """

        def _connect() -> None:
            with self._connect_lock:
                if self.is_connected:
                    event = "reconnected" if source == "watchdog" else "connected"
                    self._events.put((event, self.port or port, self._target_serial))
                    return

                try:
                    hint_serial = serial_number
                    if source == "manual":
                        hint_serial = _serial_for_device(port)
                    ser, device, found_serial = _open_settled(port, hint_serial)
                    self._ser = ser
                    self.port = device
                    with self._target_lock:
                        self._target_device = device
                        self._target_serial = found_serial
                    self.clear_voice_slots()
                    event = "reconnected" if source == "watchdog" else "connected"
                    self._events.put((event, device, found_serial))
                except Exception as exc:
                    _close_quietly(self._ser)
                    self._ser = None
                    self.port = None
                    event = "failed" if source == "watchdog" else "connect_error"
                    self._events.put((event, str(exc)))

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

    def start_watchdog(self) -> None:
        """Start the watchdog thread.

        Watch the serial connection and reconnect if it is lost.
        Results are queued for the GUI thread via poll_event().
        """
        if self._watchdog_thread and self._watchdog_thread.is_alive():
            return

        self._watchdog_stop.clear()

        def _watch() -> None:
            while not self._watchdog_stop.wait(WATCHDOG_INTERVAL_S):
                try:
                    self._watch_once()
                except Exception as exc:
                    self._events.put(("failed", str(exc)))

        self._watchdog_thread = threading.Thread(target=_watch, daemon=True)
        self._watchdog_thread.start()

    def stop_watchdog(self) -> None:
        """Stop the watchdog thread."""
        self._watchdog_stop.set()

    def _watch_once(self) -> None:
        """Drop a dead handle, then open the same Teensy again when allowed."""
        if self.is_connected and not self.check_connection():
            self.disconnect()
            self._events.put(("lost",))
            return

        if self.is_connected:
            return

        if self._connect_thread and self._connect_thread.is_alive():
            return

        with self._target_lock:
            enabled = self._reconnect_enabled
            device = self._target_device
            serial_number = self._target_serial
        if not enabled or (not device and not serial_number):
            return

        resolved = resolve_teensy_port(
            list_port_infos(),
            serial_number=serial_number,
            last_device=device,
        )
        if resolved is None:
            return

        self._events.put(("attempt", resolved.device))
        self.connect(
            resolved.device,
            source="watchdog",
            serial_number=resolved.serial_number or serial_number,
        )


def _serial_for_device(device: str) -> str | None:
    """Return the USB serial number currently reported for a device path."""
    for info in list_port_infos():
        if info.device == device:
            return info.serial_number
    return None


def _open_settled(
    hint_device: str,
    hint_serial: str | None,
) -> tuple[serial.Serial, str, str | None]:
    """Open the Teensy and, if that handle dies, reopen the new path once."""
    info = resolve_teensy_port(
        list_port_infos(),
        serial_number=hint_serial,
        last_device=hint_device,
    )
    if info is None:
        raise RuntimeError(f"Serial port not available: {hint_device}")

    serial_number = info.serial_number or hint_serial
    ser = _open_port(info.device)
    time.sleep(PROBE_SETTLE_S)
    if _handle_matches(ser, info.device, serial_number):
        return ser, info.device, serial_number

    _close_quietly(ser)
    reappeared = _wait_for_port(serial_number, hint_device)
    time.sleep(REOPEN_SETTLE_S)
    ser = _open_port(reappeared.device)
    time.sleep(PROBE_SETTLE_S)
    found_serial = reappeared.serial_number or serial_number
    if _probe(ser):
        return ser, reappeared.device, found_serial

    _close_quietly(ser)
    raise RuntimeError(f"Serial port did not respond: {reappeared.device}")


def _handle_matches(
    ser: serial.Serial,
    device: str,
    serial_number: str | None,
) -> bool:
    """Return whether the handle is alive and still bound to the same path."""
    if not _probe(ser):
        return False
    resolved = resolve_teensy_port(
        list_port_infos(),
        serial_number=serial_number,
        last_device=device,
    )
    return resolved is not None and resolved.device == device


def _wait_for_port(
    serial_number: str | None,
    last_device: str | None,
) -> SerialPortInfo:
    """Poll until the same Teensy is visible again."""
    deadline = time.time() + CONNECT_WAIT_S
    while time.time() < deadline:
        resolved = resolve_teensy_port(
            list_port_infos(),
            serial_number=serial_number,
            last_device=last_device,
        )
        if resolved is not None:
            return resolved
        time.sleep(0.1)
    raise RuntimeError("Teensy port did not reappear")
