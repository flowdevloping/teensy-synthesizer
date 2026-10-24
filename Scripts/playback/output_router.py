"""Route synth events to the Teensy audio module OR to the local audio engine.

The router is the single place which knows how a synth event (note on/off,
parameter update, LFO data) reaches the speaker:

- If the Teensy is connected, the event is sent as a serial packet.
- Otherwise, if local playback is enabled and available, the event is rendered
  by the local sounddevice engine.
- Otherwise, the event is only logged (display only).

The router has no GUI dependency. It reports back to the UI via callbacks.
"""

from typing import Callable

from playback.local.audio_engine import LocalAudioEngine
from playback.teensy.serial_client import SerialClient
from synth.lfo_waveform import table_to_int16
from synth.synth_state import SynthState


class OutputRouter:
    """Routes synth events either to the Teensy or to the local audio engine.

    Args:
        synth_state (SynthState): Shared synth state (voices, parameters, last packet).
        serial_client (SerialClient): Serial link to the Teensy.
        audio_engine (LocalAudioEngine): Local sounddevice playback.
        log (Callable[[str], None]): Receives human readable log messages.
        on_link_error (Callable[[Exception], None]): Called after a failed serial write.
            The router already marked the Teensy as disconnected at this point.
        release_voice (Callable[[str], None]): Called when the Teensy steals a voice slot
            from a voice which is still held. Expected to release that voice.

    Attributes:
        local_audio_enabled (bool): User setting "Audio playback on local device".
    """

    def __init__(
        self,
        synth_state: SynthState,
        serial_client: SerialClient,
        audio_engine: LocalAudioEngine,
        *,
        log: Callable[[str], None],
        on_link_error: Callable[[Exception], None],
        release_voice: Callable[[str], None],
    ) -> None:
        self.synth_state = synth_state
        self.serial_client = serial_client
        self.audio_engine = audio_engine
        self.local_audio_enabled = True
        self._log = log
        self._on_link_error = on_link_error
        self._release_voice = release_voice

    # ------------------------------------------------------------------
    # Routing state
    # ------------------------------------------------------------------

    @property
    def teensy_connected(self) -> bool:
        """True while the serial link to the Teensy is open."""
        return self.serial_client.is_connected

    @property
    def local_audio_active(self) -> bool:
        """True if local playback is enabled, available and the Teensy is NOT connected."""
        return (
            self.local_audio_enabled
            and self.audio_engine.is_available
            and not self.serial_client.is_connected
        )

    # ------------------------------------------------------------------
    # Note events
    # ------------------------------------------------------------------

    def voice_on(self, voice_id: str) -> None:
        """Start (or restart) a voice of the synth state on the active output."""
        voice = self.synth_state.active_voices.get(voice_id)
        if voice is None:
            return
        state = self.synth_state

        if self.serial_client.is_connected:
            self.audio_engine.all_notes_off()
            try:
                # stolen is the voice_id of the voice which previously used the slot, if any.
                slot, stolen = self.serial_client.alloc_slot(voice_id)
                if stolen is not None:
                    if stolen in state.active_voices:
                        self._release_voice(stolen)
                    self.serial_client.send_note_off(
                        state.modulator_hz,
                        state.volume_pct,
                        state.mod_depth_pct,
                        voice_id=slot,
                        carrier_waveform=state.carrier_waveform,
                    )
                    self._log(f"Teensy voice steal: slot {slot} from {stolen}")

                packet = self.serial_client.send(
                    voice.carrier_hz,
                    voice.modulator_hz,
                    state.volume_pct,
                    state.mod_depth_pct,
                    voice_id=slot,
                    carrier_waveform=state.carrier_waveform,
                )
                state.last_packet = packet
                self._log(f"Sent: {packet}")
            except Exception as exc:
                self._drop_link(exc, f"Send error: {exc}")
                # Fall back to the local device if it is available.
                if self.local_audio_active:
                    self._play_local_voice(voice_id)
            return

        if self.local_audio_active:
            self._play_local_voice(voice_id)
            return

        self._log(f"Note {voice.carrier_hz:.2f} Hz (no serial / local playback off)")

    def voice_off(self, voice_id: str) -> None:
        """Release a voice on the active output."""
        state = self.synth_state

        if self.serial_client.is_connected:
            self.audio_engine.all_notes_off()
            try:
                slot = self.serial_client.release_slot(voice_id)
                if slot is not None:
                    packet = self.serial_client.send_note_off(
                        state.modulator_hz,
                        state.volume_pct,
                        state.mod_depth_pct,
                        voice_id=slot,
                        carrier_waveform=state.carrier_waveform,
                    )
                    state.last_packet = packet
                    self._log(f"Note-Off sent: {packet}")
                else:
                    self._log(f"Note-Off: no Teensy slot for {voice_id}")
            except Exception as exc:
                self._drop_link(exc, f"Note-Off failed: {exc}")
            return

        if self.audio_engine.is_available and self.local_audio_enabled:
            self.audio_engine.note_off(voice_id)
            state.last_packet = f"local:note-off:{voice_id}"
            self._log(f"Note-Off local: {voice_id}")
        else:
            self._log(f"Note-Off (only display): {voice_id}")

    def all_notes_off(self) -> None:
        """Release every voice on the active output."""
        state = self.synth_state

        if self.serial_client.is_connected:
            self.audio_engine.all_notes_off()
            try:
                packet = self.serial_client.send_all_notes_off(state.volume_pct)
                state.last_packet = packet
                self._log(f"All-Notes-Off sent: {packet}")
            except Exception as exc:
                self._drop_link(exc, f"Note-Off failed: {exc}")
            return

        if self.audio_engine.is_available and self.local_audio_enabled:
            self.audio_engine.all_notes_off()
            state.last_packet = "local:all-notes-off"
            self._log("All-Notes-Off local")
        else:
            self._log("All-Notes-Off (display only)")

    def stop_local_voice(self, voice_id: str) -> None:
        """Silence one voice on the local engine only (e.g. after voice stealing)."""
        if self.local_audio_active:
            self.audio_engine.note_off(voice_id)

    # ------------------------------------------------------------------
    # Parameter updates
    # ------------------------------------------------------------------

    def param_update(self, quiet: bool = False) -> None:
        """Push the current synth parameters to all sounding voices."""
        state = self.synth_state
        if not state.is_playing:
            return

        if self.serial_client.is_connected:
            try:
                for voice in state.active_voices.values():
                    slot = self.serial_client.get_slot(voice.voice_id)
                    if slot is None:
                        slot, _stolen = self.serial_client.alloc_slot(voice.voice_id)
                    packet = self.serial_client.send(
                        voice.carrier_hz,
                        voice.modulator_hz,
                        state.volume_pct,
                        state.mod_depth_pct,
                        voice_id=slot,
                        carrier_waveform=state.carrier_waveform,
                    )
                    state.last_packet = packet
                if not quiet:
                    self._log(f"Teensy update: {len(state.active_voices)} voices")
            except Exception as exc:
                self._drop_link(exc, f"Send error: {exc}")
            return

        if self.local_audio_active:
            self.audio_engine.update_params(
                {**state.engine_params(), "voices": self._voice_tuples()}
            )
            state.last_packet = f"local:update:{len(state.active_voices)} voices"
            if not quiet:
                self._log(state.last_packet)

    # ------------------------------------------------------------------
    # LFO / filter (Teensy only)
    # ------------------------------------------------------------------

    def send_lfo(self) -> None:
        """Send LFO rate/depth and filter settings to the Teensy (no-op if not connected)."""
        if not self.serial_client.is_connected:
            return
        state = self.synth_state
        try:
            packet = self.serial_client.send_lfo(
                state.lfo_rate_hz,
                state.lfo_depth_pct,
                state.filter_cutoff_hz,
                state.filter_resonance,
            )
            state.last_packet = packet
            self._log(f"LFO sent: {packet}")
        except Exception as exc:
            self._drop_link(exc, f"LFO send error: {exc}")

    def send_lfo_table(self) -> None:
        """Send the LFO wavetable to the Teensy (no-op if not connected)."""
        if not self.serial_client.is_connected:
            return
        try:
            summary = self.serial_client.send_lfo_table(
                table_to_int16(self.synth_state.lfo_table)
            )
            self.synth_state.last_packet = summary
            self._log(f"LFO table sent: {summary}")
        except Exception as exc:
            self._drop_link(exc, f"LFO table send error: {exc}")

    # ------------------------------------------------------------------
    # Teensy link lifecycle
    # ------------------------------------------------------------------

    def teensy_connected_to(self, port: str) -> None:
        """Record a freshly established Teensy link and silence local playback."""
        self.synth_state.connected = True
        self.synth_state.port = port
        self.audio_engine.all_notes_off()

    def teensy_lost(self) -> None:
        """Record that the Teensy link vanished (port already closed by the client)."""
        self.synth_state.connected = False
        self.synth_state.port = None

    def teensy_connect_failed(self) -> None:
        """Record a failed connection attempt and make sure the port is closed."""
        self.synth_state.connected = False
        self.synth_state.port = None
        self.serial_client.disconnect()

    def disconnect_teensy(self) -> None:
        """Close the Teensy link on user request, releasing sounding notes first."""
        if self.synth_state.is_playing:
            try:
                self.serial_client.send_all_notes_off(self.synth_state.volume_pct)
            except Exception:
                pass
        self.serial_client.disconnect()
        self.synth_state.connected = False
        self.synth_state.port = None

    def shutdown(self) -> None:
        """Stop the serial watchdog, close the port and close the local engine."""
        self.serial_client.stop_watchdog()
        self.serial_client.disconnect()
        self.audio_engine.close()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _voice_tuples(self) -> list[tuple[str, float, float]]:
        return [
            (v.voice_id, v.carrier_hz, v.modulator_hz)
            for v in self.synth_state.active_voices.values()
        ]

    def _play_local_voice(self, voice_id: str) -> None:
        voice = self.synth_state.active_voices.get(voice_id)
        if voice is None:
            return
        params = self.synth_state.engine_params()
        params["modulator_hz"] = voice.modulator_hz
        self.audio_engine.note_on(voice.voice_id, voice.carrier_hz, params)
        packet = f"local:fm:{voice.voice_id}:{voice.carrier_hz:.2f}Hz"
        self.synth_state.last_packet = packet
        self._log(f"Played locally: {packet}")

    def _drop_link(self, exc: Exception, log_message: str) -> None:
        """Mark the Teensy as disconnected after a failed write and tell the UI."""
        self.synth_state.connected = False
        self.serial_client.disconnect()
        self._on_link_error(exc)
        self._log(log_message)
