"""Builds GUI and handles input.

This script provides the main components to either control the audio module or just play around with
sound creation on the local device (when not connected to the audio module).
It translates user inputs into events which are dispatched to the hardware communication layers.

Hardware Dependencies:
- (optional): Teensy 4.1 connected via USB + MAX98357A + Visaton FRWS 5 (4 Ohm)
    IMPORTANT: Make sure to use seperate power sources:
        - 5V USB for the Teensy
        - Lipo 1S for MAX98357A + Visaton FRWS 5, connected via the charging module.
- (optional): MIDI Keyboard connected via USB
"""

from datetime import datetime
from tkinter import Canvas, Entry, Text

import customtkinter as ctk  # Python UI library based on tkinter (standard Python GUI toolkit)
from audio_engine import LocalAudioEngine
from config_store import load_config, save_config
from conlang_lexicon import (
    LEXEME_ORDER,
    LEXEMES,
    UTTERANCE_ORDER,
    UTTERANCES,
    get_utterance,
    meanings_label,
)
from conlang_utterance_player import (
    CONLANG_VOICE_ID,
    UtterancePlayer,
    compile_utterance,
)
from fm_utils import compute_modulator_hz
from lfo_waveform import (
    LFO_PRESET_LABELS,
    LFO_PRESET_ORDER,
    LFO_WAVETABLE_SIZE,
    lfo_interp_from_label,
    lfo_interp_label,
    point_indices,
    table_to_int16,
)
from midi_input import MidiCallbacks, MidiInputHandler, list_midi_ports
from safety_limits import (
    DEFAULT_VOLUME_PCT,
    FILTER_MAX_CUTOFF_HZ,
    FILTER_MAX_Q,
    FILTER_MIN_CUTOFF_HZ,
    FILTER_MIN_Q,
    LFO_MAX_DEPTH_PCT,
    LFO_MAX_RATE_HZ,
    LFO_MIN_RATE_HZ,
    MAX_MOD_DEPTH_PCT,
    MAX_MODULATOR_HZ,
    MAX_MODULATOR_RATIO,
    MAX_VOLUME_PCT,
    MIN_MODULATOR_HZ,
    MIN_MODULATOR_RATIO,
    VOLUME_KEYBOARD_STEP,
    clamp_carrier_hz,
    clamp_filter_cutoff,
    clamp_filter_q,
    clamp_lfo_depth_pct,
    clamp_lfo_rate,
    clamp_mod_depth_pct,
    clamp_modulator_hz,
    clamp_modulator_ratio,
    clamp_volume_pct,
)
from serial_client import SerialClient, WatchdogCallbacks, list_com_ports
from setup_store import (
    SynthSetup,
    export_user_spec,
    list_setups,
    load_setup,
    save_setup,
)
from synth_mode_presets import FM_PRESETS, apply_preset
from synth_state import NOTE_MAPPING, PC_KEYBOARD_MAPPING, SynthState
from waveforms import (
    WAVETABLE_CARRIER_WAVEFORM,
    carrier_waveform_from_label,
    carrier_waveform_label,
    carrier_waveform_labels,
    is_wavetable_carrier,
)


class SynthApp(ctk.CTk):
    """Main class of customtkinter module to build GUI.

    Builds the GUI and translates user inputs (sliders, buttons, PC keyboard)
    into control events for the audio engine and the serial hardware client.

    Args:
        title (str): Title of the window.
        geometry (str): Width and height of the window in pixels.
        minsize (tuple[int, int]): Minimum width and height of the window in pixels.
        config (AppConfig): Configuration object.
        key_freqs (dict[str, float]): Frequencies mapped to the PC keyboard keys ('a', 's', 'd', 'f', 'g', 'h', 'j', 'k').
        synth_state (SynthState): Synth state object (see synth_state.py).
        serial_client (SerialClient): Serial client object (see serial_client.py).
        midi_handler (MidiInputHandler): Midi input handler object (see midi_input.py).
        audio_engine (LocalAudioEngine): Local audio engine object (see audio_engine.py).
    """

    def __init__(self) -> None:
        """Creates GUI window initially."""

        super().__init__()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("Sonic HRI Synth")
        self.geometry("800x820")
        self.minsize(600, 520)

        self.config = load_config()

        key_freqs = {
            key: clamp_carrier_hz(freq)
            for key, freq in {
                **PC_KEYBOARD_MAPPING,
                **self.config.key_frequencies,
            }.items()
        }

        self.synth_state = SynthState(
            key_frequencies=key_freqs,
            carrier_waveform=self.config.carrier_waveform,
            modulator_hz=self.config.modulator_hz,
            modulator_mode=self.config.modulator_mode,
            modulator_ratio=self.config.modulator_ratio,
            volume_pct=self.config.volume_pct,
            mod_depth_pct=self.config.mod_depth_pct,
            lfo_rate_hz=self.config.lfo_rate_hz,
            lfo_depth_pct=self.config.lfo_depth_pct,
            lfo_preset=self.config.lfo_preset,
            lfo_interp=self.config.lfo_interp,
            lfo_points=list(self.config.lfo_points),
            lfo_table=list(self.config.lfo_table),
            filter_cutoff_hz=self.config.filter_cutoff_hz,
            filter_resonance=self.config.filter_resonance,
            active_preset=self.config.active_preset,
        )
        self.serial_client = SerialClient()
        self.midi_handler = MidiInputHandler()
        self.audio_engine = LocalAudioEngine()
        self._connect_in_progress = False
        self._midi_connect_in_progress = False
        self._pressed_keys: set[str] = set()
        self._note_buttons: dict[str, ctk.CTkButton] = {}
        self._key_freq_entries: dict[str, ctk.CTkEntry] = {}
        self._note_button_default_color: str | tuple[str, str] | None = None
        self._lfo_drag_index: int | None = None
        self._lfo_table_send_after: object | None = None
        self._lfo_ui_syncing = False
        self._lfo_preset_buttons: dict[str, ctk.CTkButton] = {}
        self._utterance_player = UtterancePlayer(
            schedule=self._schedule_utterance_event,
            cancel=self._cancel_utterance_event,
            on_note_on=lambda freq: self._note_on(CONLANG_VOICE_ID, freq),
            on_retune=lambda freq: self._retune_voice(CONLANG_VOICE_ID, freq),
            on_note_off=lambda: self._note_off(CONLANG_VOICE_ID),
            on_finished=self._on_utterance_finished,
        )

        self._build_ui()
        self._disable_all_slider_scrolling()
        self._setup_keyboard_bindings()
        self._refresh_port_list()
        self._refresh_midi_list()
        self._refresh_display()
        self._log("Config loaded")
        self._start_local_audio()
        self._start_watchdog()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        """Build up the high level areas of the UI.

        Defines layout and builds up the connection, scroll and log panels.
        Calls functions to build remaining panels.
        """

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=0)

        connection_frame = ctk.CTkFrame(self)
        connection_frame.grid(row=0, column=0, padx=16, pady=(16, 8), sticky="ew")
        connection_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(connection_frame, text="COM-Port").grid(
            row=0, column=0, padx=12, pady=12, sticky="w"
        )

        self.port_var = ctk.StringVar(value="")
        self.port_menu = ctk.CTkOptionMenu(
            connection_frame,
            variable=self.port_var,
            values=[""],
            width=180,
        )
        self.port_menu.grid(row=0, column=1, padx=8, pady=12, sticky="w")

        self.refresh_ports_button = ctk.CTkButton(
            connection_frame,
            text="Refresh",
            width=120,
            command=self._refresh_port_list,
        )
        self.refresh_ports_button.grid(row=0, column=2, padx=8, pady=12)

        self.connect_button = ctk.CTkButton(
            connection_frame,
            text="Connect",
            width=120,
            command=self._on_connect,
        )
        self.connect_button.grid(row=0, column=3, padx=8, pady=12)

        self.disconnect_button = ctk.CTkButton(
            connection_frame,
            text="Disconnect",
            width=120,
            command=self._on_disconnect,
            state="disabled",
        )
        self.disconnect_button.grid(row=0, column=4, padx=(8, 12), pady=12)

        self.auto_reconnect_var = ctk.BooleanVar(value=self.config.auto_reconnect)
        self.auto_reconnect_checkbox = ctk.CTkCheckBox(
            connection_frame,
            text="Auto-Reconnect",
            variable=self.auto_reconnect_var,
            command=self._on_auto_reconnect_changed,
        )
        self.auto_reconnect_checkbox.grid(
            row=1, column=0, columnspan=2, padx=12, pady=(0, 12), sticky="w"
        )

        self.status_label = ctk.CTkLabel(
            connection_frame,
            text="State: Disconnected",
            anchor="w",
        )
        self.status_label.grid(
            row=1, column=2, columnspan=3, padx=12, pady=(0, 8), sticky="w"
        )

        ctk.CTkLabel(connection_frame, text="MIDI-Port").grid(
            row=2, column=0, padx=12, pady=(0, 12), sticky="w"
        )

        self.midi_port_var = ctk.StringVar(value="")
        self.midi_port_menu = ctk.CTkOptionMenu(
            connection_frame,
            variable=self.midi_port_var,
            values=[""],
            width=180,
        )
        self.midi_port_menu.grid(row=2, column=1, padx=8, pady=(0, 12), sticky="w")

        self.refresh_midi_button = ctk.CTkButton(
            connection_frame,
            text="Refresh",
            width=120,
            command=self._refresh_midi_list,
        )
        self.refresh_midi_button.grid(row=2, column=2, padx=8, pady=(0, 12))

        self.midi_connect_button = ctk.CTkButton(
            connection_frame,
            text="Connect MIDI",
            width=120,
            command=self._on_midi_connect,
        )
        self.midi_connect_button.grid(row=2, column=3, padx=8, pady=(0, 12))

        self.midi_disconnect_button = ctk.CTkButton(
            connection_frame,
            text="Disconnect MIDI",
            width=120,
            command=self._on_midi_disconnect,
            state="disabled",
        )
        self.midi_disconnect_button.grid(row=2, column=4, padx=(8, 12), pady=(0, 12))

        self.midi_status_label = ctk.CTkLabel(
            connection_frame,
            text="MIDI: Disconnected",
            anchor="w",
        )
        self.midi_status_label.grid(
            row=3, column=0, columnspan=5, padx=12, pady=(0, 8), sticky="w"
        )

        self.local_audio_var = ctk.BooleanVar(value=self.config.local_audio_enabled)
        self.local_audio_checkbox = ctk.CTkCheckBox(
            connection_frame,
            text="Audio playback on local device",
            variable=self.local_audio_var,
            command=self._on_local_audio_changed,
        )
        self.local_audio_checkbox.grid(
            row=4, column=0, columnspan=2, padx=12, pady=(0, 12), sticky="w"
        )

        self.local_audio_status_label = ctk.CTkLabel(
            connection_frame,
            text="Local: —",
            anchor="w",
            text_color="gray70",
        )
        self.local_audio_status_label.grid(
            row=4, column=2, columnspan=3, padx=12, pady=(0, 12), sticky="w"
        )

        scroll_frame = ctk.CTkScrollableFrame(self, label_text="")
        scroll_frame.grid(row=1, column=0, padx=16, pady=8, sticky="nsew")
        scroll_frame.grid_columnconfigure(0, weight=1)

        display_frame = ctk.CTkFrame(scroll_frame)
        display_frame.grid(row=0, column=0, pady=(0, 8), sticky="ew")
        for col in range(4):
            display_frame.grid_columnconfigure(col, weight=1)

        self.carrier_value_label = self._create_value_block(
            display_frame, 0, "Carrier-Frequency", "—"
        )
        self.modulator_value_label = self._create_value_block(
            display_frame, 1, "Modulator-Frequency", "20.0 Hz"
        )
        self.volume_value_label = self._create_value_block(
            display_frame, 2, "Volume", f"{DEFAULT_VOLUME_PCT} %"
        )
        self.mod_depth_value_label = self._create_value_block(
            display_frame, 3, "Modulator-Depth", "20 %"
        )

        self.packet_label = ctk.CTkLabel(
            scroll_frame,
            text="Last Package: —",
            anchor="w",
        )
        self.packet_label.grid(row=1, column=0, pady=(0, 8), sticky="ew")

        controls_frame = ctk.CTkFrame(scroll_frame)
        controls_frame.grid(row=2, column=0, pady=(0, 8), sticky="ew")
        controls_frame.grid_columnconfigure(0, weight=1)

        keyboard_header = ctk.CTkFrame(controls_frame, fg_color="transparent")
        keyboard_header.grid(row=0, column=0, padx=12, pady=(12, 8), sticky="ew")
        keyboard_header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(keyboard_header, text="Laptop Keyboard").grid(
            row=0, column=0, sticky="w"
        )
        self.stop_button = ctk.CTkButton(
            keyboard_header,
            text="Stop Sounds",
            width=100,
            fg_color="#8b0000",
            hover_color="#a40000",
            command=self._on_stop,
        )
        self.stop_button.grid(row=0, column=1, padx=(8, 0), sticky="e")

        keyboard_frame = ctk.CTkFrame(controls_frame, fg_color="transparent")
        keyboard_frame.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="ew")

        # Creating buttons for each key and frequency
        for index, (key, frequency_hz) in enumerate(
            self.synth_state.key_frequencies.items()
        ):
            key_label = key.upper()
            button = ctk.CTkButton(
                keyboard_frame,
                text=f"{key_label}\n{frequency_hz:.2f} Hz",
                width=72,
                # On button click, call the _note_on function with the key and frequency
                command=lambda k=key: self._note_on(
                    k, self.synth_state.key_frequencies[k]
                ),
            )
            button.grid(row=0, column=index, padx=4, pady=4)
            self._note_buttons[key] = button
            if self._note_button_default_color is None:
                self._note_button_default_color = button.cget("fg_color")

            entry = ctk.CTkEntry(keyboard_frame, width=72, justify="center")
            entry.insert(0, f"{frequency_hz:.2f}")
            entry.grid(row=1, column=index, padx=4, pady=(0, 4))
            entry.bind("<Return>", lambda _event, k=key: self._commit_key_frequency(k))
            entry.bind(
                "<FocusOut>", lambda _event, k=key: self._commit_key_frequency(k)
            )
            self._key_freq_entries[key] = entry

        key_count = len(self.synth_state.key_frequencies)
        ctk.CTkButton(
            keyboard_frame,
            text="Reset frequencies",
            width=120,
            fg_color="gray30",
            hover_color="gray40",
            command=self._reset_key_frequencies,
        ).grid(
            row=2,
            column=0,
            columnspan=max(key_count, 1),
            padx=4,
            pady=(4, 0),
            sticky="w",
        )

        ctk.CTkLabel(
            controls_frame,
            text="PC Keyboard: A S D F G H J K: hold, polyphonic | + / -: Volume | Spacebar: Stop Sounds",
            text_color="gray70",
        ).grid(row=2, column=0, padx=12, pady=(0, 8), sticky="w")

        self._build_conlang_panel(controls_frame)

        sound_frame = ctk.CTkFrame(controls_frame)
        sound_frame.grid(row=4, column=0, padx=0, pady=(0, 8), sticky="ew")
        sound_frame.grid_columnconfigure(0, weight=1)

        sound_header = ctk.CTkFrame(sound_frame, fg_color="transparent")
        sound_header.grid(row=0, column=0, padx=12, pady=(12, 8), sticky="ew")
        sound_header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            sound_header,
            text="Sound Synthesis Configuration",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).grid(row=0, column=0, sticky="w")

        self.volume_label = ctk.CTkLabel(
            sound_frame, text=f"Volume: {self.synth_state.volume_pct} %"
        )
        self.volume_label.grid(row=1, column=0, padx=12, pady=(0, 4), sticky="w")
        volume_controls = ctk.CTkFrame(sound_frame, fg_color="transparent")
        volume_controls.grid(row=2, column=0, padx=12, pady=(0, 8), sticky="ew")
        volume_controls.grid_columnconfigure(0, weight=1)
        self.volume_slider = ctk.CTkSlider(
            volume_controls,
            from_=0,
            to=MAX_VOLUME_PCT,
            number_of_steps=MAX_VOLUME_PCT,
        )
        self.volume_slider.set(self.synth_state.volume_pct)
        self.volume_slider.grid(row=0, column=0, sticky="ew")
        self.volume_entry = ctk.CTkEntry(volume_controls, width=70)
        self.volume_entry.grid(row=0, column=1, padx=(8, 0), sticky="e")
        self._wire_slider_entry(
            self.volume_slider,
            self.volume_entry,
            0,
            MAX_VOLUME_PCT,
            self._on_volume_changed,
            decimals=0,
        )

        preset_row = ctk.CTkFrame(sound_frame, fg_color="transparent")
        preset_row.grid(row=3, column=0, padx=12, pady=(0, 8), sticky="w")
        ctk.CTkLabel(preset_row, text="Presets:").grid(
            row=0, column=0, padx=(0, 8), sticky="w"
        )
        preset_names = list(FM_PRESETS)
        active_preset = self.synth_state.active_preset
        self.preset_var = ctk.StringVar(
            value=active_preset if active_preset in FM_PRESETS else "Custom"
        )
        self.preset_menu = ctk.CTkOptionMenu(
            preset_row,
            variable=self.preset_var,
            values=preset_names or ["No presets"],
            command=self._on_preset_selected,
            width=140,
        )
        self.preset_menu.grid(row=0, column=1, sticky="w")
        self._sync_preset_menu()

        self.fm_panel_frame = ctk.CTkFrame(sound_frame, fg_color="transparent")
        self.fm_panel_frame.grid(row=5, column=0, padx=12, pady=(0, 8), sticky="ew")
        self.fm_panel_frame.grid_columnconfigure(0, weight=1)
        self._build_fm_panel()

        self.lfo_panel_frame = ctk.CTkFrame(sound_frame, fg_color="transparent")
        self.lfo_panel_frame.grid(row=6, column=0, padx=12, pady=(0, 8), sticky="ew")
        self.lfo_panel_frame.grid_columnconfigure(0, weight=1)
        self._build_lfo_panel()

        self.filter_panel_frame = ctk.CTkFrame(sound_frame, fg_color="transparent")
        self.filter_panel_frame.grid(row=7, column=0, padx=12, pady=(0, 8), sticky="ew")
        self.filter_panel_frame.grid_columnconfigure(0, weight=1)
        self._build_filter_panel()

        setup_frame = ctk.CTkFrame(controls_frame)
        setup_frame.grid(row=5, column=0, pady=(0, 8), sticky="ew")
        setup_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            setup_frame,
            text="Save/Load Setups",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).grid(row=0, column=0, columnspan=3, padx=12, pady=(12, 6), sticky="w")
        ctk.CTkLabel(setup_frame, text="Load").grid(
            row=1, column=0, padx=12, pady=6, sticky="w"
        )
        self.setup_load_var = ctk.StringVar(value="")
        self.setup_load_menu = ctk.CTkOptionMenu(
            setup_frame, variable=self.setup_load_var, values=["No setups"]
        )
        self.setup_load_menu.grid(row=1, column=1, padx=6, pady=6, sticky="ew")
        ctk.CTkButton(
            setup_frame, text="Load", width=90, command=self._load_setup
        ).grid(row=1, column=2, padx=(6, 12), pady=6)
        ctk.CTkLabel(setup_frame, text="Name").grid(
            row=2, column=0, padx=12, pady=6, sticky="w"
        )
        self.setup_name_var = ctk.StringVar(value=self.config.last_setup_name)
        self.setup_name_entry = ctk.CTkEntry(
            setup_frame, textvariable=self.setup_name_var, placeholder_text="Setup name"
        )
        self.setup_name_entry.grid(row=2, column=1, padx=6, pady=6, sticky="ew")
        ctk.CTkButton(
            setup_frame, text="Save", width=90, command=self._save_setup
        ).grid(row=2, column=2, padx=(6, 12), pady=6)
        ctk.CTkLabel(setup_frame, text="Notes").grid(
            row=3, column=0, padx=12, pady=(6, 12), sticky="nw"
        )
        self.setup_notes_entry = ctk.CTkEntry(
            setup_frame, placeholder_text="Optional notes"
        )
        self.setup_notes_entry.grid(row=3, column=1, padx=6, pady=(6, 12), sticky="ew")
        ctk.CTkButton(
            setup_frame, text="Export spec", width=110, command=self._export_setup_spec
        ).grid(row=3, column=2, padx=(6, 12), pady=(6, 12))
        self._refresh_setup_list()

        ctk.CTkLabel(
            sound_frame,
            text=(
                "Control elements are partially limited to safety values. "
                "Defined in safety_limits.py."
            ),
            text_color="gray60",
            anchor="w",
        ).grid(row=8, column=0, padx=12, pady=(0, 12), sticky="ew")

        log_frame = ctk.CTkFrame(self)
        log_frame.grid(row=2, column=0, padx=16, pady=(0, 16), sticky="ew")
        log_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(log_frame, text="Event log", anchor="w").grid(
            row=0, column=0, padx=12, pady=(12, 4), sticky="w"
        )

        self.log_text = ctk.CTkTextbox(log_frame, height=90, state="disabled")
        self.log_text.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="ew")

    def _build_conlang_panel(self, parent: ctk.CTkFrame) -> None:
        conlang_frame = ctk.CTkFrame(parent)
        conlang_frame.grid(row=3, column=0, padx=0, pady=(0, 8), sticky="ew")
        conlang_frame.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(conlang_frame, fg_color="transparent")
        header.grid(row=0, column=0, padx=12, pady=(12, 6), sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header,
            text="Conlang Functionality",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).grid(row=0, column=0, sticky="w")

        play_row = ctk.CTkFrame(conlang_frame, fg_color="transparent")
        play_row.grid(row=1, column=0, padx=12, pady=(0, 6), sticky="ew")
        play_row.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(play_row, text="Utterance").grid(
            row=0, column=0, padx=(0, 8), sticky="w"
        )
        utterance_labels = [UTTERANCES[uid].label for uid in UTTERANCE_ORDER]
        self.conlang_utterance_var = ctk.StringVar(value=utterance_labels[0])
        self.conlang_utterance_menu = ctk.CTkOptionMenu(
            play_row,
            variable=self.conlang_utterance_var,
            values=utterance_labels,
            width=180,
        )
        self.conlang_utterance_menu.grid(row=0, column=1, padx=(0, 8), sticky="w")
        ctk.CTkButton(
            play_row, text="Play", width=80, command=self._on_conlang_play
        ).grid(row=0, column=2, padx=(0, 8))
        ctk.CTkButton(
            play_row,
            text="Stop",
            width=80,
            fg_color="#8b0000",
            hover_color="#a40000",
            command=self._on_stop,
        ).grid(row=0, column=3)

        lexeme_row = ctk.CTkFrame(conlang_frame, fg_color="transparent")
        lexeme_row.grid(row=2, column=0, padx=12, pady=(0, 6), sticky="ew")
        ctk.CTkLabel(lexeme_row, text="Words").grid(
            row=0, column=0, padx=(0, 8), sticky="w"
        )
        for index, lexeme_id in enumerate(LEXEME_ORDER):
            lexeme = LEXEMES[lexeme_id]
            ctk.CTkButton(
                lexeme_row,
                text=lexeme.meaning,
                width=88,
                command=lambda item=lexeme_id: self.speak([item]),
            ).grid(row=0, column=index + 1, padx=2, pady=2)

        self.conlang_status_label = ctk.CTkLabel(
            conlang_frame, text="Speaking: —", anchor="w"
        )
        self.conlang_status_label.grid(
            row=3, column=0, padx=12, pady=(0, 4), sticky="w"
        )

    def _build_fm_panel(self) -> None:
        fm = self.fm_panel_frame
        fm.grid_columnconfigure(0, weight=1)

        carrier_waveform_row = ctk.CTkFrame(fm, fg_color="transparent")
        carrier_waveform_row.grid(
            row=0, column=0, columnspan=2, pady=(0, 6), sticky="w"
        )
        ctk.CTkLabel(carrier_waveform_row, text="Carrier waveform").grid(
            row=0, column=0, padx=(0, 8), sticky="w"
        )
        self.carrier_waveform_var = ctk.StringVar(
            value=carrier_waveform_label(self.synth_state.carrier_waveform)
        )
        self.carrier_waveform_switch = ctk.CTkSegmentedButton(
            carrier_waveform_row,
            values=carrier_waveform_labels(),
            variable=self.carrier_waveform_var,
            command=self._on_carrier_waveform_changed,
        )
        self.carrier_waveform_switch.grid(row=0, column=1, sticky="w")

        self.wavetable_button = ctk.CTkButton(
            carrier_waveform_row,
            text=carrier_waveform_label(WAVETABLE_CARRIER_WAVEFORM),
            width=150,
            command=self._on_wavetable_carrier_selected,
        )
        self.wavetable_button.grid(row=0, column=2, padx=(8, 0), sticky="w")
        self._sync_carrier_waveform_ui()

        modulator_mode_row = ctk.CTkFrame(fm, fg_color="transparent")
        modulator_mode_row.grid(row=1, column=0, columnspan=2, sticky="w")
        ctk.CTkLabel(modulator_mode_row, text="Modulator mode").grid(
            row=0, column=0, padx=(0, 8), sticky="w"
        )
        self.modulator_mode_var = ctk.StringVar(
            value="Ratio" if self.synth_state.modulator_mode == "ratio" else "Fix Hz"
        )
        self.modulator_mode_switch = ctk.CTkSegmentedButton(
            modulator_mode_row,
            values=["Fix Hz", "Ratio"],
            variable=self.modulator_mode_var,
            command=self._on_modulator_mode_changed,
        )
        self.modulator_mode_switch.grid(row=0, column=1, sticky="w")

        self.modulator_hz_frame = ctk.CTkFrame(fm, fg_color="transparent")
        self.modulator_hz_frame.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.modulator_hz_frame.grid_columnconfigure(0, weight=1)
        self.ratio_frame = ctk.CTkFrame(fm, fg_color="transparent")
        self.ratio_frame.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.ratio_frame.grid_columnconfigure(0, weight=1)

        self.modulator_label = ctk.CTkLabel(
            self.modulator_hz_frame,
            text=f"Modulator: {self.synth_state.modulator_hz:.1f} Hz",
        )
        self.modulator_slider = ctk.CTkSlider(
            self.modulator_hz_frame,
            from_=MIN_MODULATOR_HZ,
            to=MAX_MODULATOR_HZ,
            number_of_steps=int(MAX_MODULATOR_HZ - MIN_MODULATOR_HZ),
        )
        self.modulator_slider.set(self.synth_state.modulator_hz)
        self.modulator_entry = ctk.CTkEntry(self.modulator_hz_frame, width=70)
        self.ratio_label = ctk.CTkLabel(
            self.ratio_frame,
            text=f"Ratio (Modulator Frequency / Carrier Frequency): {self.synth_state.modulator_ratio:.2f}x",
        )
        self.ratio_slider = ctk.CTkSlider(
            self.ratio_frame,
            from_=MIN_MODULATOR_RATIO,
            to=MAX_MODULATOR_RATIO,
            number_of_steps=int((MAX_MODULATOR_RATIO - MIN_MODULATOR_RATIO) * 100),
        )
        self.ratio_slider.set(self.synth_state.modulator_ratio)
        self.ratio_entry = ctk.CTkEntry(self.ratio_frame, width=70)
        self.mod_depth_label = ctk.CTkLabel(
            fm,
            text=self._mod_depth_slider_label_text(),
        )
        self.mod_depth_slider = ctk.CTkSlider(
            fm,
            from_=0,
            to=MAX_MOD_DEPTH_PCT,
            number_of_steps=MAX_MOD_DEPTH_PCT,
        )
        self.mod_depth_slider.set(self.synth_state.mod_depth_pct)
        self.mod_depth_entry = ctk.CTkEntry(fm, width=70)
        self._add_labeled_slider(
            self.modulator_hz_frame,
            0,
            self.modulator_label,
            self.modulator_slider,
            self.modulator_entry,
        )
        self._add_labeled_slider(
            self.ratio_frame,
            0,
            self.ratio_label,
            self.ratio_slider,
            self.ratio_entry,
        )
        self._add_labeled_slider(
            fm, 1, self.mod_depth_label, self.mod_depth_slider, self.mod_depth_entry
        )
        self._wire_slider_entry(
            self.modulator_slider,
            self.modulator_entry,
            MIN_MODULATOR_HZ,
            MAX_MODULATOR_HZ,
            self._on_modulator_changed,
            decimals=1,
        )
        self._wire_slider_entry(
            self.ratio_slider,
            self.ratio_entry,
            MIN_MODULATOR_RATIO,
            MAX_MODULATOR_RATIO,
            self._on_ratio_changed,
            decimals=2,
        )
        self._wire_slider_entry(
            self.mod_depth_slider,
            self.mod_depth_entry,
            0,
            MAX_MOD_DEPTH_PCT,
            self._on_mod_depth_changed,
            decimals=0,
        )
        self._set_modulator_mode_ui()

    def _build_lfo_panel(self) -> None:
        lfo = self.lfo_panel_frame
        lfo.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(lfo, fg_color="transparent")
        header.grid(row=0, column=0, columnspan=2, pady=(4, 4), sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header,
            text="LFO",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, sticky="w")
        self._add_teensy_only_hint(header, "LFO", row=1)

        shape_row = ctk.CTkFrame(lfo, fg_color="transparent")
        shape_row.grid(row=1, column=0, columnspan=2, pady=(0, 6), sticky="ew")
        shape_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(shape_row, text="LFO shape").grid(
            row=0, column=0, padx=(0, 8), sticky="w"
        )

        preset_row = ctk.CTkFrame(shape_row, fg_color="transparent")
        preset_row.grid(row=0, column=1, sticky="w")
        self._lfo_preset_buttons = {}
        for column, name in enumerate(LFO_PRESET_ORDER):
            button = ctk.CTkButton(
                preset_row,
                text=LFO_PRESET_LABELS[name],
                width=64,
                command=lambda preset=name: self._on_lfo_preset_clicked(preset),
            )
            button.grid(row=0, column=column, padx=(0, 6), sticky="w")
            self._lfo_preset_buttons[name] = button

        self.lfo_interp_var = ctk.StringVar(
            value=lfo_interp_label(self.synth_state.lfo_interp)
        )
        self.lfo_interp_switch = ctk.CTkSegmentedButton(
            shape_row,
            values=["Linear", "Step"],
            variable=self.lfo_interp_var,
            command=self._on_lfo_interp_changed,
            width=140,
        )
        self.lfo_interp_switch.grid(row=0, column=2, padx=(8, 0), sticky="e")

        canvas_host = ctk.CTkFrame(lfo, fg_color="gray17", corner_radius=6)
        canvas_host.grid(row=2, column=0, columnspan=2, pady=(0, 4), sticky="ew")
        canvas_host.grid_columnconfigure(0, weight=1)
        self.lfo_canvas = Canvas(
            canvas_host,
            height=90,
            bg="#1a1a1a",
            highlightthickness=0,
            bd=0,
        )
        self.lfo_canvas.grid(row=0, column=0, padx=4, pady=4, sticky="ew")
        self.lfo_canvas.bind("<Configure>", self._on_lfo_canvas_configure)
        self.lfo_canvas.bind("<ButtonPress-1>", self._on_lfo_canvas_press)
        self.lfo_canvas.bind("<B1-Motion>", self._on_lfo_canvas_motion)
        self.lfo_canvas.bind("<ButtonRelease-1>", self._on_lfo_canvas_release)
        self.lfo_canvas.after(1, self._draw_lfo_canvas)
        self._sync_lfo_waveform_ui()

        self.lfo_rate_label = ctk.CTkLabel(
            lfo, text=f"LFO rate: {self.synth_state.lfo_rate_hz:.2f} Hz"
        )
        self.lfo_rate_slider = ctk.CTkSlider(
            lfo, from_=LFO_MIN_RATE_HZ, to=LFO_MAX_RATE_HZ
        )
        self.lfo_rate_slider.set(self.synth_state.lfo_rate_hz)
        self.lfo_rate_entry = ctk.CTkEntry(lfo, width=70)

        self.lfo_depth_label = ctk.CTkLabel(
            lfo, text=f"LFO depth: {self.synth_state.lfo_depth_pct} %"
        )
        self.lfo_depth_slider = ctk.CTkSlider(
            lfo, from_=0, to=LFO_MAX_DEPTH_PCT, number_of_steps=LFO_MAX_DEPTH_PCT
        )
        self.lfo_depth_slider.set(self.synth_state.lfo_depth_pct)
        self.lfo_depth_entry = ctk.CTkEntry(lfo, width=70)

        self._add_labeled_slider(
            lfo, 1, self.lfo_rate_label, self.lfo_rate_slider, self.lfo_rate_entry
        )
        self._add_labeled_slider(
            lfo, 2, self.lfo_depth_label, self.lfo_depth_slider, self.lfo_depth_entry
        )

        self._wire_slider_entry(
            self.lfo_rate_slider,
            self.lfo_rate_entry,
            LFO_MIN_RATE_HZ,
            LFO_MAX_RATE_HZ,
            self._on_lfo_rate_changed,
            decimals=2,
        )
        self._wire_slider_entry(
            self.lfo_depth_slider,
            self.lfo_depth_entry,
            0,
            LFO_MAX_DEPTH_PCT,
            self._on_lfo_depth_changed,
            decimals=0,
        )

    def _build_filter_panel(self) -> None:
        panel = self.filter_panel_frame
        panel.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(panel, fg_color="transparent")
        header.grid(row=0, column=0, columnspan=2, pady=(4, 4), sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header,
            text="Filter Cutoff",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, sticky="w")
        self._add_teensy_only_hint(header, "Filter Cutoff", row=1)

        self.filter_cutoff_label = ctk.CTkLabel(
            panel, text=f"Filter cutoff: {self.synth_state.filter_cutoff_hz:.0f} Hz"
        )
        self.filter_cutoff_slider = ctk.CTkSlider(
            panel, from_=FILTER_MIN_CUTOFF_HZ, to=FILTER_MAX_CUTOFF_HZ
        )
        self.filter_cutoff_slider.set(self.synth_state.filter_cutoff_hz)
        self.filter_cutoff_entry = ctk.CTkEntry(panel, width=70)

        self.filter_resonance_label = ctk.CTkLabel(
            panel, text=f"Filter resonance (Q): {self.synth_state.filter_resonance:.2f}"
        )
        self.filter_resonance_slider = ctk.CTkSlider(
            panel,
            from_=FILTER_MIN_Q,
            to=FILTER_MAX_Q,
            number_of_steps=int((FILTER_MAX_Q - FILTER_MIN_Q) * 100),
        )
        self.filter_resonance_slider.set(self.synth_state.filter_resonance)
        self.filter_resonance_entry = ctk.CTkEntry(panel, width=70)

        self._add_labeled_slider(
            panel,
            0,
            self.filter_cutoff_label,
            self.filter_cutoff_slider,
            self.filter_cutoff_entry,
        )
        self._add_labeled_slider(
            panel,
            1,
            self.filter_resonance_label,
            self.filter_resonance_slider,
            self.filter_resonance_entry,
        )

        self._wire_slider_entry(
            self.filter_cutoff_slider,
            self.filter_cutoff_entry,
            FILTER_MIN_CUTOFF_HZ,
            FILTER_MAX_CUTOFF_HZ,
            self._on_filter_cutoff_changed,
            decimals=0,
        )
        self._wire_slider_entry(
            self.filter_resonance_slider,
            self.filter_resonance_entry,
            FILTER_MIN_Q,
            FILTER_MAX_Q,
            self._on_filter_resonance_changed,
            decimals=2,
        )

    def _add_teensy_only_hint(
        self, parent: ctk.CTkFrame, feature: str, row: int
    ) -> None:
        ctk.CTkLabel(
            parent,
            text=(
                f"{feature} only works while connected to Teensy and through "
                "the audio modules speaker. Without connection to the audio module "
                "a fallback option with pythons sounddevice library is used as synth, "
                "to enable playing around with sounds on the local device."
            ),
            text_color="gray70",
            anchor="w",
            justify="left",
            wraplength=720,
        ).grid(row=row, column=0, pady=(3, 0), sticky="ew")

    def _add_labeled_slider(
        self,
        parent: ctk.CTkFrame,
        row: int,
        label: ctk.CTkLabel,
        slider: ctk.CTkSlider,
        entry: ctk.CTkEntry | None = None,
    ) -> None:

        label_row = row * 2 + 1
        control_row = row * 2 + 2
        label.grid(
            row=label_row, column=0, columnspan=2, padx=0, pady=(6, 2), sticky="w"
        )
        parent.grid_columnconfigure(0, weight=1)
        slider.grid(row=control_row, column=0, padx=0, pady=(0, 4), sticky="ew")
        if entry is not None:
            entry.grid(row=control_row, column=1, padx=(8, 0), pady=(0, 4), sticky="e")

    def _format_param_value(self, value: float, decimals: int) -> str:
        if decimals <= 0:
            return str(int(round(value)))
        return f"{value:.{decimals}f}"

    def _set_entry_text(self, entry: ctk.CTkEntry, value: float, decimals: int) -> None:
        text = self._format_param_value(value, decimals)
        if entry.get() != text:
            entry.delete(0, "end")
            entry.insert(0, text)

    def _wire_slider_entry(
        self,
        slider: ctk.CTkSlider,
        entry: ctk.CTkEntry,
        minimum: float,
        maximum: float,
        on_value,
        decimals: int = 2,
    ) -> None:
        self._set_entry_text(entry, float(slider.get()), decimals)

        def on_slider(value: float) -> None:
            self._set_entry_text(entry, float(value), decimals)
            on_value(float(value))

        def commit(_event: object = None) -> None:
            raw = entry.get().strip().replace(",", ".")
            try:
                parsed = float(raw)
            except ValueError:
                self._set_entry_text(entry, float(slider.get()), decimals)
                return
            clamped = max(minimum, min(maximum, parsed))
            slider.set(clamped)
            actual = float(slider.get())
            self._set_entry_text(entry, actual, decimals)
            on_value(actual)
            return "break"

        slider.configure(command=on_slider)
        internal = getattr(entry, "_entry", None)
        for sequence in ("<Return>", "<Key-Return>", "<FocusOut>"):
            entry.bind(sequence, commit)
            if internal is not None:
                internal.bind(sequence, commit, add="+")
        entry._numeric_commit = commit  # type: ignore[attr-defined]

    # Disables all slider scrolling
    def _disable_all_slider_scrolling(self) -> None:
        def walk(widget) -> None:
            for child in widget.winfo_children():
                if isinstance(child, ctk.CTkSlider):
                    self._disable_slider_scroll(child)
                walk(child)

        walk(self)

    def _disable_slider_scroll(self, slider: ctk.CTkSlider) -> None:
        canvas = getattr(slider, "_canvas", None)
        if canvas is None:
            return
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            canvas.bind(sequence, lambda _event: "break")

    def _sync_preset_menu(self) -> None:
        names = list(FM_PRESETS)
        if not names:
            self.preset_menu.configure(values=["No presets"], state="disabled")
            self.preset_var.set("No presets")
            return
        active = self.synth_state.active_preset
        values = list(names)
        if active not in FM_PRESETS:
            values.append("Custom")
            active = "Custom"
        self.preset_menu.configure(values=values, state="normal")
        self.preset_var.set(active)

    def _on_preset_selected(self, name: str) -> None:
        if name == "Custom" or name not in FM_PRESETS:
            self._sync_preset_menu()
            return
        self._apply_preset(name)

    def _refresh_setup_list(self) -> None:
        setups = list_setups()
        values = setups or ["No setups"]
        self.setup_load_menu.configure(values=values)
        preferred = self.config.last_setup_name
        self.setup_load_var.set(preferred if preferred in setups else values[0])

    def _current_setup(self) -> SynthSetup:
        name = (
            self.setup_name_var.get().strip()
            or self.config.last_setup_name
            or "Untitled"
        )
        return SynthSetup(
            name=name,
            params=self.synth_state.setup_params_dict(),
            notes=self.setup_notes_entry.get().strip(),
        )

    def _save_setup(self) -> None:
        setup = self._current_setup()
        path = save_setup(setup)
        self.setup_name_var.set(setup.name)
        self.config.last_setup_name = setup.name
        self._save_config()
        self._refresh_setup_list()
        self._log(f"Setup saved: {path.name}")

    def _load_setup(self) -> None:
        name = self.setup_load_var.get()
        setup = load_setup(name)
        if setup is None:
            self._log(f"Setup not found: {name}")
            return
        self._on_stop()
        self.synth_state.apply_setup_params(setup.params)
        self.synth_state.setup_name = setup.name
        self.setup_name_var.set(setup.name)
        self.setup_notes_entry.delete(0, "end")
        self.setup_notes_entry.insert(0, setup.notes)
        self.config.last_setup_name = setup.name
        self._sync_mode_controls()
        self._save_config()
        self._refresh_display()
        self._send_lfo_table()
        self._send_lfo()
        self._log(f"Setup loaded: {setup.name}")

    def _export_setup_spec(self) -> None:
        setup = self._current_setup()
        path = export_user_spec(setup)
        self._log(f"Spec exported: {path.name}")

    def _create_value_block(
        self, parent: ctk.CTkFrame, column: int, title: str, initial_value: str
    ) -> ctk.CTkLabel:
        block = ctk.CTkFrame(parent)
        block.grid(row=0, column=column, padx=8, pady=12, sticky="nsew")

        ctk.CTkLabel(block, text=title, font=ctk.CTkFont(size=14)).pack(
            padx=12, pady=(12, 4)
        )
        value_label = ctk.CTkLabel(
            block,
            text=initial_value,
            font=ctk.CTkFont(size=22, weight="bold"),
        )
        value_label.pack(padx=12, pady=(0, 12))
        return value_label

    def _setup_keyboard_bindings(self) -> None:
        self.bind_all("<KeyPress>", self._on_key_press, add="+")
        self.bind_all("<KeyRelease>", self._on_key_release, add="+")
        self.focus_set()
        self._log("Laptop keyboard active: A S D F G H J K")

    def _should_ignore_keyboard(self, event: object) -> bool:
        widget = getattr(event, "widget", None)
        if widget is None:
            widget = self.focus_get()
        current = widget
        while current is not None:
            if isinstance(current, (ctk.CTkTextbox, ctk.CTkEntry, Entry, Text)):
                return True
            try:
                if current.winfo_class() in ("Entry", "Text", "TEntry"):
                    return True
            except Exception:
                pass
            current = getattr(current, "master", None)
        return False

    def _normalize_key(self, event: object) -> str | None:
        char = getattr(event, "char", "") or ""
        keysym = getattr(event, "keysym", "") or ""
        if len(char) == 1 and char.isprintable():
            normalized = char.lower()
            if normalized in PC_KEYBOARD_MAPPING:
                return normalized
        keysym_lower = keysym.lower()
        if keysym_lower in PC_KEYBOARD_MAPPING:
            return keysym_lower
        return None

    def _set_note_button_pressed(self, key: str, pressed: bool) -> None:
        button = self._note_buttons.get(key)
        if button is None:
            return
        if pressed:
            button.configure(fg_color="#1f6aa5")
        elif self._note_button_default_color is not None:
            button.configure(fg_color=self._note_button_default_color)

    # Applies a manually edited frequency for a keyboard key
    def _commit_key_frequency(self, key: str) -> None:
        entry = self._key_freq_entries[key]
        raw = entry.get().strip().replace(",", ".")
        try:
            value = float(raw)
        except ValueError:
            self._set_entry_text(entry, self.synth_state.key_frequencies[key], 2)
            return
        value = clamp_carrier_hz(value)
        self.synth_state.key_frequencies[key] = value
        self._set_entry_text(entry, value, 2)
        self._note_buttons[key].configure(text=f"{key.upper()}\n{value:.2f} Hz")
        self._save_config()

    def _reset_key_frequencies(self) -> None:
        self.synth_state.key_frequencies = {
            key: clamp_carrier_hz(freq) for key, freq in PC_KEYBOARD_MAPPING.items()
        }
        for key, freq in self.synth_state.key_frequencies.items():
            entry = self._key_freq_entries.get(key)
            if entry is not None:
                self._set_entry_text(entry, freq, 2)
            button = self._note_buttons.get(key)
            if button is not None:
                button.configure(text=f"{key.upper()}\n{freq:.2f} Hz")
        self._save_config()
        self._log("Keyboard frequencies reset to default")

    def _adjust_volume(self, delta: int) -> None:
        new_volume = clamp_volume_pct(self.synth_state.volume_pct + delta)
        self.volume_slider.set(new_volume)
        self._on_volume_changed(new_volume)

    def _on_key_press(self, event: object) -> None:
        if self._should_ignore_keyboard(event):
            return

        key = self._normalize_key(event)
        if key is not None:
            if key in self._pressed_keys:
                return
            self._pressed_keys.add(key)
            self._set_note_button_pressed(key, True)
            self._note_on(key, self.synth_state.key_frequencies[key])
            return

        keysym = getattr(event, "keysym", "")
        char = getattr(event, "char", "") or ""

        if keysym in ("plus", "equal", "KP_Add") or char == "+":
            self._adjust_volume(VOLUME_KEYBOARD_STEP)
        elif keysym in ("minus", "underscore", "KP_Subtract") or char == "-":
            self._adjust_volume(-VOLUME_KEYBOARD_STEP)
        elif keysym == "space":
            self._on_stop()
            return

        if keysym in ("1", "2", "3", "4", "5", "6"):
            preset_names = list(FM_PRESETS)
            index = int(keysym) - 1
            if index < len(preset_names):
                self._apply_preset(preset_names[index])

    def _on_key_release(self, event: object) -> None:
        if self._should_ignore_keyboard(event):
            return

        key = self._normalize_key(event)
        if key is None or key not in self._pressed_keys:
            return

        self._pressed_keys.discard(key)
        self._set_note_button_pressed(key, False)
        self._note_off(key)

    def _log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}\n"
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _save_config(self) -> None:
        self.config.key_frequencies = dict(self.synth_state.key_frequencies)
        self.config.carrier_waveform = self.synth_state.carrier_waveform
        self.config.modulator_hz = self.synth_state.modulator_hz
        self.config.modulator_mode = self.synth_state.modulator_mode
        self.config.modulator_ratio = self.synth_state.modulator_ratio
        self.config.volume_pct = self.synth_state.volume_pct
        self.config.mod_depth_pct = self.synth_state.mod_depth_pct
        self.config.lfo_rate_hz = self.synth_state.lfo_rate_hz
        self.config.lfo_depth_pct = self.synth_state.lfo_depth_pct
        self.config.lfo_preset = self.synth_state.lfo_preset
        self.config.lfo_interp = self.synth_state.lfo_interp
        self.config.lfo_points = list(self.synth_state.lfo_points)
        self.config.lfo_table = list(self.synth_state.lfo_table)
        self.config.filter_cutoff_hz = self.synth_state.filter_cutoff_hz
        self.config.filter_resonance = self.synth_state.filter_resonance
        self.config.active_preset = self.synth_state.active_preset
        self.config.auto_reconnect = self.auto_reconnect_var.get()
        self.config.local_audio_enabled = self.local_audio_var.get()
        self.config.last_setup_name = self.setup_name_var.get().strip()
        save_config(self.config)

    def _refresh_midi_list(self) -> None:
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
            self._log("MIDI connection aborted: no valid port")
            return

        self._midi_connect_in_progress = True
        self._set_midi_controls(False)
        self.midi_status_label.configure(text=f"MIDI: Connecting to {port}...")
        self._log(f"MIDI: Connecting to {port}...")

        callbacks = MidiCallbacks(
            on_note_on=lambda note, freq: self.after(
                0, self._on_midi_note_on, note, freq
            ),
            on_note_off=lambda note: self.after(0, self._on_midi_note_off, note),
            on_connected=lambda: self.after(0, self._handle_midi_connected, port),
            on_disconnected=lambda: self.after(0, self._handle_midi_disconnected),
            on_error=lambda message: self.after(0, self._handle_midi_error, message),
        )
        self.midi_handler.start(port, callbacks)

    def _handle_midi_connected(self, port: str) -> None:
        self._midi_connect_in_progress = False
        self.config.last_midi_port = port
        self._save_config()
        self._set_midi_controls(True)
        self.midi_status_label.configure(text=f"MIDI: Connected ({port})")
        self._log(f"MIDI connected: {port}")

    def _handle_midi_disconnected(self) -> None:
        self._midi_connect_in_progress = False
        self._set_midi_controls(False)
        self.midi_status_label.configure(text="MIDI: Disconnected")
        self._log("MIDI disconnected")

    def _handle_midi_error(self, message: str) -> None:
        self._midi_connect_in_progress = False
        self.midi_handler.stop()
        self._set_midi_controls(False)
        self.midi_status_label.configure(text=f"MIDI: Error ({message})")
        self._log(f"MIDI Error: {message}")

    def _on_midi_disconnect(self) -> None:
        port = self.midi_handler.port or self.midi_port_var.get()
        self.midi_handler.stop()
        self._set_midi_controls(False)
        self.midi_status_label.configure(text="MIDI: Disconnected")
        self._log(f"MIDI disconnected from {port}")

    def _on_midi_note_on(self, note: int, frequency_hz: float) -> None:
        self._note_on(f"midi:{note}", frequency_hz)

    def _on_midi_note_off(self, note: int) -> None:
        self._note_off(f"midi:{note}")

    def _start_local_audio(self) -> None:
        if self.audio_engine.start():
            self._log("Local audio engine started")
        else:
            message = self.audio_engine.error_message or "unknown"
            self._log(f"Local audio engine unavailable: {message}")
        self._refresh_local_audio_status()

    # Returns true if checkbox checked and audio engine is available
    def _local_audio_active(self) -> bool:
        return (
            self.local_audio_var.get()
            and self.audio_engine.is_available
            and not self.serial_client.is_connected
        )

    def _refresh_local_audio_status(self) -> None:
        if not hasattr(self, "local_audio_status_label"):
            return
        if not self.audio_engine.is_available:
            text = "Local Playback: not available"
        elif self.serial_client.is_connected:
            text = "Local Playback: Standby (Teensy active)"
        elif self.local_audio_var.get():
            text = "Local Playback: active"
        else:
            text = "Local: disabled"
        self.local_audio_status_label.configure(text=text)

    def _on_local_audio_changed(self) -> None:
        self._save_config()
        enabled = self.local_audio_var.get()
        self._log(f"Local playback {'enabled' if enabled else 'disabled'}")
        if not enabled:
            self.audio_engine.all_notes_off()
        self._refresh_local_audio_status()

    def _set_modulator_mode_ui(self) -> None:
        is_ratio = self.synth_state.modulator_mode == "ratio"
        if is_ratio:
            self.modulator_hz_frame.grid_remove()
            self.ratio_frame.grid()
        else:
            self.ratio_frame.grid_remove()
            self.modulator_hz_frame.grid()

    def _mark_custom_preset(self) -> None:
        self.synth_state.active_preset = "Custom"
        self._sync_preset_menu()

    def _apply_preset(self, preset_name: str) -> None:
        preset = FM_PRESETS.get(preset_name)
        if preset is None:
            return
        apply_preset(self.synth_state, preset_name)
        self._sync_mode_controls()
        self._save_config()
        self._refresh_display()
        self._log(f"Preset '{preset_name}': {preset.description}")

        if self.synth_state.is_playing:
            self._recompute_all_voice_modulators()
            self._dispatch_param_update()

    def _sync_mode_controls(self) -> None:
        self.modulator_slider.set(self.synth_state.modulator_hz)
        self.ratio_slider.set(self.synth_state.modulator_ratio)
        self.mod_depth_slider.set(self.synth_state.mod_depth_pct)
        self.volume_slider.set(self.synth_state.volume_pct)
        self.lfo_rate_slider.set(self.synth_state.lfo_rate_hz)
        self.lfo_depth_slider.set(self.synth_state.lfo_depth_pct)
        self.filter_cutoff_slider.set(self.synth_state.filter_cutoff_hz)
        self.filter_resonance_slider.set(self.synth_state.filter_resonance)
        self._sync_lfo_waveform_ui()
        self.modulator_mode_var.set(
            "Ratio" if self.synth_state.modulator_mode == "ratio" else "Fix Hz"
        )
        self._sync_carrier_waveform_ui()
        self._sync_param_entries()
        self._set_modulator_mode_ui()
        self._sync_preset_menu()

    def _sync_param_entries(self) -> None:
        self._set_entry_text(self.volume_entry, float(self.synth_state.volume_pct), 0)
        self._set_entry_text(
            self.modulator_entry, float(self.synth_state.modulator_hz), 1
        )
        self._set_entry_text(
            self.ratio_entry, float(self.synth_state.modulator_ratio), 2
        )
        self._set_entry_text(
            self.mod_depth_entry, float(self.synth_state.mod_depth_pct), 0
        )
        self._set_entry_text(
            self.lfo_rate_entry, float(self.synth_state.lfo_rate_hz), 2
        )
        self._set_entry_text(
            self.lfo_depth_entry, float(self.synth_state.lfo_depth_pct), 0
        )
        self._set_entry_text(
            self.filter_cutoff_entry, float(self.synth_state.filter_cutoff_hz), 0
        )
        self._set_entry_text(
            self.filter_resonance_entry, float(self.synth_state.filter_resonance), 2
        )

    # Shows the active carrier: Either one of the basic waveforms or the Teensy wavetable
    def _sync_carrier_waveform_ui(self) -> None:
        if not hasattr(self, "wavetable_button"):
            return
        if is_wavetable_carrier(self.synth_state.carrier_waveform):
            # An empty value deselects every segment of the segmented button
            self.carrier_waveform_var.set("")
            self.wavetable_button.configure(fg_color="#1f6aa5", hover_color="#144870")
        else:
            self.carrier_waveform_var.set(
                carrier_waveform_label(self.synth_state.carrier_waveform)
            )
            self.wavetable_button.configure(fg_color="gray30", hover_color="gray40")

    def _on_carrier_waveform_changed(self, value: str) -> None:
        self.synth_state.carrier_waveform = carrier_waveform_from_label(value)
        self._sync_carrier_waveform_ui()
        self._mark_custom_preset()
        self._save_config()
        self._refresh_display()
        self._log(f"Carrier waveform: {self.synth_state.carrier_waveform_display()}")

        if self.synth_state.is_playing:
            self._dispatch_param_update()

    def _on_wavetable_carrier_selected(self) -> None:
        if is_wavetable_carrier(self.synth_state.carrier_waveform):
            return

        self.synth_state.carrier_waveform = WAVETABLE_CARRIER_WAVEFORM
        self._sync_carrier_waveform_ui()
        self._mark_custom_preset()
        self._save_config()
        self._refresh_display()
        self._log(f"Carrier waveform: {self.synth_state.carrier_waveform_display()}")
        if not self.serial_client.is_connected:
            self._log(
                "Wavetable only exists on the Teensy, local playback falls back to sine"
            )

        if self.synth_state.is_playing:
            self._dispatch_param_update()

    def _on_modulator_mode_changed(self, value: str) -> None:
        self.synth_state.modulator_mode = "ratio" if value == "Ratio" else "fixed"
        if (
            self.synth_state.modulator_mode == "ratio"
            and self.synth_state.carrier_hz is not None
        ):
            self.synth_state.modulator_hz = compute_modulator_hz(
                self.synth_state.carrier_hz,
                "ratio",
                self.synth_state.modulator_hz,
                self.synth_state.modulator_ratio,
            )

        self._mark_custom_preset()
        self._set_modulator_mode_ui()
        self._save_config()
        self._refresh_display()
        self._log(f"Modulator mode: {value}")

        if self.synth_state.is_playing:
            self._recompute_all_voice_modulators()
            self._dispatch_param_update()

    def _on_ratio_changed(self, value: float) -> None:
        self.synth_state.modulator_ratio = clamp_modulator_ratio(value)
        if self.synth_state.carrier_hz is not None:
            self.synth_state.modulator_hz = compute_modulator_hz(
                self.synth_state.carrier_hz,
                "ratio",
                self.synth_state.modulator_hz,
                self.synth_state.modulator_ratio,
            )

        self._mark_custom_preset()
        self._save_config()
        self._refresh_display()
        if self.synth_state.is_playing:
            self._recompute_all_voice_modulators()
            self._dispatch_param_update()

    # Starts the watchdog timer for auto-reconnect
    def _start_watchdog(self) -> None:
        callbacks = WatchdogCallbacks(
            on_lost=lambda: self.after(0, self._handle_connection_lost),
            on_reconnect_attempt=lambda port: self.after(
                0, self._log, f"Auto-Reconnect: trying {port}"
            ),
            on_reconnected=lambda port: self.after(
                0, self._handle_auto_reconnected, port
            ),
            on_reconnect_failed=lambda message: self.after(
                0, self._log, f"Auto-Reconnect failed: {message}"
            ),
            should_auto_reconnect=lambda: self.auto_reconnect_var.get(),
            get_last_port=lambda: self.config.last_port,
        )
        self.serial_client.start_watchdog(callbacks)

    def _handle_connection_lost(self) -> None:
        self.synth_state.connected = False
        self.synth_state.port = None
        self._set_connection_controls(False)
        self.status_label.configure(text="Status: Connection lost")
        self._log("Connection lost")
        self._refresh_local_audio_status()

    def _handle_auto_reconnected(self, port: str) -> None:
        self._connect_in_progress = False
        self.synth_state.connected = True
        self.synth_state.port = port
        self.config.last_port = port
        self.audio_engine.all_notes_off()
        self._save_config()
        self._set_connection_controls(True)
        self._log(f"Auto-Reconnect successful: {port}")
        self._send_lfo_table()
        self._send_lfo()
        self._refresh_display()

    def _refresh_port_list(self) -> None:
        ports = list_com_ports()
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

    # Slider caption: Morph for the Teensy wavetable, otherwise FM modulator depth
    def _mod_depth_slider_label_text(self) -> str:
        pct = self.synth_state.mod_depth_pct
        if is_wavetable_carrier(self.synth_state.carrier_waveform):
            return f"Morph: {pct} %"
        return f"Modulator depth (FM intensity): {pct} %"

    def _refresh_display(self) -> None:
        self.carrier_value_label.configure(text=self.synth_state.carrier_display())
        self.modulator_value_label.configure(text=self.synth_state.modulator_display())
        self.volume_value_label.configure(text=self.synth_state.volume_display())
        self.mod_depth_value_label.configure(text=self.synth_state.mod_depth_display())
        self.modulator_label.configure(
            text=f"Modulator: {self.synth_state.modulator_display()}"
        )
        self.ratio_label.configure(
            text=f"Ratio to note: {self.synth_state.modulator_ratio:.2f}x → {self.synth_state.modulator_hz:.1f} Hz"
            if self.synth_state.carrier_hz is not None
            else f"Ratio to note: {self.synth_state.modulator_ratio:.2f}x"
        )
        self.volume_label.configure(text=f"Volume: {self.synth_state.volume_pct} %")
        self.mod_depth_label.configure(text=self._mod_depth_slider_label_text())
        self.lfo_rate_label.configure(
            text=f"LFO rate: {self.synth_state.lfo_rate_hz:.2f} Hz"
        )
        self.lfo_depth_label.configure(
            text=f"LFO depth: {self.synth_state.lfo_depth_pct} %"
        )
        self.filter_cutoff_label.configure(
            text=f"Filter cutoff: {self.synth_state.filter_cutoff_hz:.0f} Hz"
        )
        self.filter_resonance_label.configure(
            text=f"Filter resonance (Q): {self.synth_state.filter_resonance:.2f}"
        )
        self._sync_param_entries()

        if self.synth_state.connected and self.synth_state.port:
            self.status_label.configure(
                text=f"Status: Connected ({self.synth_state.port})"
            )
        elif self._connect_in_progress:
            self.status_label.configure(text="Status: Connecting...")
        else:
            self.status_label.configure(text="Status: Disconnected")

        packet_text = self.synth_state.last_packet or "—"
        self.packet_label.configure(text=f"Last package: {packet_text}")
        self._refresh_local_audio_status()

    # Computes the modulator frequency for a carrier frequency
    def _modulator_for_carrier(self, carrier_hz: float) -> float:
        return compute_modulator_hz(
            carrier_hz,
            self.synth_state.modulator_mode,
            self.synth_state.modulator_hz,
            self.synth_state.modulator_ratio,
        )

    def _recompute_all_voice_modulators(self) -> None:
        self.synth_state.update_voice_modulators(self._modulator_for_carrier)

    def _voice_tuples(self) -> list[tuple[str, float, float]]:
        return [
            (v.voice_id, v.carrier_hz, v.modulator_hz)
            for v in self.synth_state.active_voices.values()
        ]

    # Dispatch functions:
    # Routing functions to EITHER play sound on audio module OR on local device.
    def _dispatch_voice_on(self, voice_id: str) -> None:
        voice = self.synth_state.active_voices.get(voice_id)
        if voice is None:
            return

        # If Teensy is connected, send 'play sound' message to Teensy
        if self.serial_client.is_connected:
            self.audio_engine.all_notes_off()
            # Try to play sound on Teensy (sending 'play sound' message to Teensy)
            try:
                slot, stolen = self.serial_client.alloc_slot(voice_id)
                if stolen is not None:
                    if stolen in self.synth_state.active_voices:
                        self._note_off(stolen)
                    self.serial_client.send_note_off(
                        self.synth_state.modulator_hz,
                        self.synth_state.volume_pct,
                        self.synth_state.mod_depth_pct,
                        voice_id=slot,
                        carrier_waveform=self.synth_state.carrier_waveform,
                    )
                    self._log(f"Teensy voice steal: slot {slot} from {stolen}")

                # Sending 'play sound' message to Teensy
                packet = self.serial_client.send(
                    voice.carrier_hz,
                    voice.modulator_hz,
                    self.synth_state.volume_pct,
                    self.synth_state.mod_depth_pct,
                    voice_id=slot,
                    carrier_waveform=self.synth_state.carrier_waveform,
                )
                self.synth_state.last_packet = packet
                self._log(f"Sent: {packet}")

            except Exception as exc:
                self.synth_state.connected = False
                self.serial_client.disconnect()
                self._set_connection_controls(False)
                self.status_label.configure(text=f"Status: Send error ({exc})")
                self._log(f"Send error: {exc}")
                # If local audio is active, play the voice on the local device
                if self._local_audio_active():
                    self._play_local_voice(voice_id)
            self._refresh_display()
            return

        # If local audio is active AND Teensy is NOT connected, play the voice on the local device
        if self._local_audio_active():
            self._play_local_voice(voice_id)
            self._refresh_display()
            return

        self.status_label.configure(text="Status: Not connected – display only")
        self._log(f"Note {voice.carrier_hz:.2f} Hz (no serial / local playback off)")
        self._refresh_display()

    def _dispatch_voice_off(self, voice_id: str) -> None:
        if self.serial_client.is_connected:
            self.audio_engine.all_notes_off()
            try:
                slot = self.serial_client.release_slot(voice_id)
                if slot is not None:
                    packet = self.serial_client.send_note_off(
                        self.synth_state.modulator_hz,
                        self.synth_state.volume_pct,
                        self.synth_state.mod_depth_pct,
                        voice_id=slot,
                        carrier_waveform=self.synth_state.carrier_waveform,
                    )
                    self.synth_state.last_packet = packet
                    self._log(f"Note-Off sent: {packet}")
                else:
                    self._log(f"Note-Off: no Teensy slot for {voice_id}")
            except Exception as exc:
                self.synth_state.connected = False
                self.serial_client.disconnect()
                self._set_connection_controls(False)
                self.status_label.configure(text=f"Status: Send error ({exc})")
                self._log(f"Note-Off failed: {exc}")
            return

        if self.audio_engine.is_available and self.local_audio_var.get():
            self.audio_engine.note_off(voice_id)
            self.synth_state.last_packet = f"local:note-off:{voice_id}"
            self._log(f"Note-Off local: {voice_id}")
        else:
            self._log(f"Note-Off (only display): {voice_id}")

    def _dispatch_all_notes_off(self) -> None:
        if self.serial_client.is_connected:
            self.audio_engine.all_notes_off()
            try:
                packet = self.serial_client.send_all_notes_off(
                    self.synth_state.volume_pct
                )
                self.synth_state.last_packet = packet
                self._log(f"All-Notes-Off sent: {packet}")
            except Exception as exc:
                self.synth_state.connected = False
                self.serial_client.disconnect()
                self._set_connection_controls(False)
                self.status_label.configure(text=f"Status: Send error ({exc})")
                self._log(f"Note-Off failed: {exc}")
            return

        if self.audio_engine.is_available and self.local_audio_var.get():
            self.audio_engine.all_notes_off()
            self.synth_state.last_packet = "local:all-notes-off"
            self._log("All-Notes-Off local")
        else:
            self._log("All-Notes-Off (display only)")

    def _dispatch_param_update(self, quiet: bool = False) -> None:
        if not self.synth_state.is_playing:
            return

        if self.serial_client.is_connected:
            try:
                for voice in self.synth_state.active_voices.values():
                    slot = self.serial_client.get_slot(voice.voice_id)
                    if slot is None:
                        slot, _stolen = self.serial_client.alloc_slot(voice.voice_id)
                    packet = self.serial_client.send(
                        voice.carrier_hz,
                        voice.modulator_hz,
                        self.synth_state.volume_pct,
                        self.synth_state.mod_depth_pct,
                        voice_id=slot,
                        carrier_waveform=self.synth_state.carrier_waveform,
                    )
                    self.synth_state.last_packet = packet
                if not quiet:
                    self._log(
                        f"Teensy update: {len(self.synth_state.active_voices)} voices"
                    )
            except Exception as exc:
                self.synth_state.connected = False
                self.serial_client.disconnect()
                self._set_connection_controls(False)
                self.status_label.configure(text=f"Status: Send error ({exc})")
                self._log(f"Send error: {exc}")
            self._refresh_display()
            return

        # If Teensy is not connected AND local audio is activated, do parameter update on local device
        if self._local_audio_active():
            self.audio_engine.update_params(
                {**self.synth_state.engine_params(), "voices": self._voice_tuples()}
            )
            self.synth_state.last_packet = (
                f"local:update:{len(self.synth_state.active_voices)} voices"
            )
            if not quiet:
                self._log(self.synth_state.last_packet)
            self._refresh_display()

    # Function to play sound on local device
    def _play_local_voice(self, voice_id: str) -> None:
        voice = self.synth_state.active_voices.get(voice_id)
        if voice is None:
            return
        params = self.synth_state.engine_params()
        params["modulator_hz"] = voice.modulator_hz
        self.audio_engine.note_on(
            voice.voice_id,
            voice.carrier_hz,
            params,
        )
        packet = f"local:fm:{voice.voice_id}:{voice.carrier_hz:.2f}Hz"
        self.synth_state.last_packet = packet
        self._log(f"Played locally: {packet}")

    # Initially initiate playing a sound
    def _note_on(self, voice_id: str, frequency_hz: float) -> None:
        frequency_hz = clamp_carrier_hz(frequency_hz)
        modulator = self._modulator_for_carrier(frequency_hz)
        stolen = self.synth_state.note_on(voice_id, frequency_hz, modulator)
        if stolen and self._local_audio_active():
            self.audio_engine.note_off(stolen)
        self._refresh_display()
        self._dispatch_voice_on(voice_id)

    # Sound resumes playing, frequency changes on the go.
    def _retune_voice(self, voice_id: str, frequency_hz: float) -> None:
        frequency_hz = clamp_carrier_hz(frequency_hz)
        modulator = self._modulator_for_carrier(frequency_hz)
        if not self.synth_state.retune(voice_id, frequency_hz, modulator):
            self._note_on(voice_id, frequency_hz)
            return
        self._dispatch_param_update(quiet=True)

    # Play a conlang utterance
    def speak(self, lexeme_ids: list[str]) -> None:
        try:
            events = compile_utterance(lexeme_ids)
            label = meanings_label(lexeme_ids)
        except ValueError as exc:
            self._log(f"Conlang speak failed: {exc}")
            return
        self._stop_utterance(release=True)
        self.conlang_status_label.configure(text=f"Speaking: {label}")
        self._utterance_player.play(events)
        self._log(f"Conlang speak: {label}")

    def _on_conlang_play(self) -> None:
        label = self.conlang_utterance_var.get()
        utterance_id = next(
            (uid for uid in UTTERANCE_ORDER if UTTERANCES[uid].label == label),
            None,
        )
        if utterance_id is None:
            self._log(f"Unknown utterance: {label}")
            return
        utterance = get_utterance(utterance_id)
        self.speak(list(utterance.lexeme_ids))

    def _schedule_utterance_event(self, delay_ms: int, callback) -> object:
        return self.after(max(0, int(delay_ms)), callback)

    def _cancel_utterance_event(self, token: object) -> None:
        self.after_cancel(token)

    def _stop_utterance(self, release: bool = True) -> None:
        self._utterance_player.stop()
        if release:
            self._note_off(CONLANG_VOICE_ID)

    def _on_utterance_finished(self) -> None:
        self.conlang_status_label.configure(text="Speaking: —")
        self._log("Conlang utterance finished")

    # Mute sound on local device
    # e.g. Called when a note is released on the PC's keyboard
    def _note_off(self, voice_id: str) -> None:
        if not self.synth_state.note_off(voice_id):
            return
        self._dispatch_voice_off(voice_id)
        self._refresh_display()

    def _send_current_state(self) -> None:
        self._dispatch_param_update()

    def _on_note_pressed(self, frequency_hz: float) -> None:
        # Legacy helper: treat as anonymous button note by frequency
        note_name = next(
            (
                name
                for name, (_, freq) in NOTE_MAPPING.items()
                if abs(freq - frequency_hz) < 0.01
            ),
            f"freq:{frequency_hz:.2f}",
        )
        self._note_on(note_name, frequency_hz)

    def _on_stop(self) -> None:
        self._stop_utterance(release=False)
        self._pressed_keys.clear()
        for key in list(self._note_buttons):
            self._set_note_button_pressed(key, False)
        self.synth_state.all_notes_off()
        self._dispatch_all_notes_off()
        self.conlang_status_label.configure(text="Speaking: —")
        self._refresh_display()

    def _on_modulator_changed(self, value: float) -> None:
        self.synth_state.modulator_hz = clamp_modulator_hz(value)
        self._mark_custom_preset()
        self._save_config()
        self._refresh_display()
        if self.synth_state.is_playing:
            self._recompute_all_voice_modulators()
            self._dispatch_param_update()

    def _on_volume_changed(self, value: float) -> None:
        self.synth_state.volume_pct = clamp_volume_pct(value)
        self._mark_custom_preset()
        self._save_config()
        self._refresh_display()
        if self.synth_state.is_playing:
            self._dispatch_param_update()

    def _on_mod_depth_changed(self, value: float) -> None:
        self.synth_state.mod_depth_pct = clamp_mod_depth_pct(value)
        self._mark_custom_preset()
        self._save_config()
        self._refresh_display()
        if self.synth_state.is_playing:
            self._dispatch_param_update()

    def _send_lfo(self) -> None:
        if self.serial_client.is_connected:
            try:
                packet = self.serial_client.send_lfo(
                    self.synth_state.lfo_rate_hz,
                    self.synth_state.lfo_depth_pct,
                    self.synth_state.filter_cutoff_hz,
                    self.synth_state.filter_resonance,
                )
                self.synth_state.last_packet = packet
                self._log(f"LFO sent: {packet}")
            except Exception as exc:
                self.synth_state.connected = False
                self.serial_client.disconnect()
                self._set_connection_controls(False)
                self.status_label.configure(text=f"Status: Send error ({exc})")
                self._log(f"LFO send error: {exc}")
        self._refresh_display()

    def _send_lfo_table(self) -> None:
        if not self.serial_client.is_connected:
            return
        try:
            summary = self.serial_client.send_lfo_table(
                table_to_int16(self.synth_state.lfo_table)
            )
            self.synth_state.last_packet = summary
            self._log(f"LFO table sent: {summary}")
        except Exception as exc:
            self.synth_state.connected = False
            self.serial_client.disconnect()
            self._set_connection_controls(False)
            self.status_label.configure(text=f"Status: Send error ({exc})")
            self._log(f"LFO table send error: {exc}")

    def _schedule_lfo_table_send(self, delay_ms: int = 80) -> None:
        if self._lfo_table_send_after is not None:
            self.after_cancel(self._lfo_table_send_after)
        self._lfo_table_send_after = self.after(delay_ms, self._flush_lfo_table_send)

    def _flush_lfo_table_send(self) -> None:
        self._lfo_table_send_after = None
        self._send_lfo_table()

    def _cancel_lfo_table_send(self) -> None:
        if self._lfo_table_send_after is not None:
            self.after_cancel(self._lfo_table_send_after)
            self._lfo_table_send_after = None

    def _on_lfo_rate_changed(self, value: float) -> None:
        self.synth_state.lfo_rate_hz = clamp_lfo_rate(value)
        self._save_config()
        self._send_lfo()

    def _on_lfo_depth_changed(self, value: float) -> None:
        self.synth_state.lfo_depth_pct = clamp_lfo_depth_pct(value)
        self._save_config()
        self._send_lfo()

    def _on_filter_cutoff_changed(self, value: float) -> None:
        self.synth_state.filter_cutoff_hz = clamp_filter_cutoff(value)
        self._save_config()
        self._send_lfo()

    def _on_filter_resonance_changed(self, value: float) -> None:
        self.synth_state.filter_resonance = clamp_filter_q(value)
        self._save_config()
        self._send_lfo()

    def _on_lfo_preset_clicked(self, preset: str) -> None:
        self.synth_state.set_lfo_preset(preset)
        self._sync_lfo_waveform_ui()
        self._save_config()
        self._send_lfo_table()

    def _on_lfo_interp_changed(self, value: str) -> None:
        if self._lfo_ui_syncing:
            return
        self.synth_state.lfo_interp = lfo_interp_from_label(value)
        self.synth_state.rebuild_lfo_from_points(mark_custom=True)
        self._sync_lfo_waveform_ui()
        self._save_config()
        self._send_lfo_table()

    def _sync_lfo_waveform_ui(self) -> None:
        if not hasattr(self, "lfo_canvas"):
            return
        self._lfo_ui_syncing = True
        active = self.synth_state.lfo_preset
        for name, button in self._lfo_preset_buttons.items():
            if name == active:
                button.configure(fg_color="#1f6aa5", hover_color="#144870")
            else:
                button.configure(fg_color="gray30", hover_color="gray40")
        self.lfo_interp_var.set(lfo_interp_label(self.synth_state.lfo_interp))
        self._draw_lfo_canvas()
        self._lfo_ui_syncing = False

    # Return the width, height, and padding of the LFO canvas
    def _lfo_canvas_metrics(self) -> tuple[int, int, int, int]:
        width = max(self.lfo_canvas.winfo_width(), 2)
        height = max(self.lfo_canvas.winfo_height(), 2)
        return width, height, 12, 10

    # Convert sample index and value to x, y coordinates in canvas
    def _lfo_canvas_xy(self, sample_index: float, value: float) -> tuple[float, float]:
        width, height, pad_x, pad_y = self._lfo_canvas_metrics()
        inner_w = max(1, width - 2 * pad_x)
        inner_h = max(1, height - 2 * pad_y)
        x = pad_x + (sample_index / LFO_WAVETABLE_SIZE) * inner_w
        y = pad_y + (1.0 - (value + 1.0) / 2.0) * inner_h
        return x, y

    # Convert y coordinate in canvas to value (-1.0 to 1.0)
    def _lfo_canvas_y_to_value(self, y: float) -> float:
        _width, height, _pad_x, pad_y = self._lfo_canvas_metrics()
        inner_h = max(1, height - 2 * pad_y)
        value = 1.0 - 2.0 * (y - pad_y) / inner_h
        return max(-1.0, min(1.0, value))

    def _draw_lfo_canvas(self) -> None:
        if not hasattr(self, "lfo_canvas"):
            return
        canvas = self.lfo_canvas
        canvas.delete("all")
        width, height, _pad_x, _pad_y = self._lfo_canvas_metrics()
        if width < 20 or height < 20:
            return

        zero_left = self._lfo_canvas_xy(0, 0.0)
        zero_right = self._lfo_canvas_xy(LFO_WAVETABLE_SIZE, 0.0)
        canvas.create_line(
            zero_left[0], zero_left[1], zero_right[0], zero_right[1], fill="#3a3a3a"
        )

        table = self.synth_state.lfo_table
        polyline: list[float] = []
        for index, sample in enumerate(table):
            x, y = self._lfo_canvas_xy(index, sample)
            polyline.extend((x, y))
        end_x, end_y = self._lfo_canvas_xy(LFO_WAVETABLE_SIZE, table[0])
        polyline.extend((end_x, end_y))
        canvas.create_line(*polyline, fill="#3b8ed0", width=2)

        for i, sample_index in enumerate(point_indices()):
            x, y = self._lfo_canvas_xy(
                int(sample_index), self.synth_state.lfo_points[i]
            )
            radius = 5
            canvas.create_oval(
                x - radius,
                y - radius,
                x + radius,
                y + radius,
                fill="#ffffff",
                outline="#1f6aa5",
                width=1,
            )

    def _on_lfo_canvas_configure(self, _event) -> None:
        self._draw_lfo_canvas()

    def _lfo_hit_handle(self, x: float, y: float) -> int | None:
        best_index: int | None = None
        best_dist = 14.0**2
        for i, sample_index in enumerate(point_indices()):
            hx, hy = self._lfo_canvas_xy(
                int(sample_index), self.synth_state.lfo_points[i]
            )
            dist = (x - hx) ** 2 + (y - hy) ** 2
            if dist < best_dist:
                best_dist = dist
                best_index = i
        return best_index

    def _apply_lfo_point_drag(self, y: float) -> None:
        if self._lfo_drag_index is None:
            return
        points = list(self.synth_state.lfo_points)
        points[self._lfo_drag_index] = self._lfo_canvas_y_to_value(y)
        self.synth_state.lfo_points = points
        self.synth_state.rebuild_lfo_from_points(mark_custom=True)
        self._sync_lfo_waveform_ui()
        self._schedule_lfo_table_send()

    def _on_lfo_canvas_press(self, event) -> None:
        self._lfo_drag_index = self._lfo_hit_handle(event.x, event.y)
        if self._lfo_drag_index is not None:
            self._apply_lfo_point_drag(event.y)

    def _on_lfo_canvas_motion(self, event) -> None:
        if self._lfo_drag_index is None:
            return
        self._apply_lfo_point_drag(event.y)

    def _on_lfo_canvas_release(self, _event) -> None:
        if self._lfo_drag_index is None:
            return
        self._lfo_drag_index = None
        self._cancel_lfo_table_send()
        self._save_config()
        self._send_lfo_table()

    def _on_auto_reconnect_changed(self) -> None:
        self._save_config()
        state = "enabled" if self.auto_reconnect_var.get() else "disabled"
        self._log(f"Auto-Reconnect {state}")

    def _on_connect(self) -> None:
        port = self.port_var.get()
        if not port or port == "No port found":
            self.status_label.configure(text="Status: No valid COM port selected")
            self._log("Connection aborted: no valid COM port")
            return

        self._connect_in_progress = True
        self._set_connection_controls(False)
        self.status_label.configure(text=f"Status: Connecting to {port}...")
        self._log(f"Connecting to {port}...")
        self.update_idletasks()

        def on_success() -> None:
            self.after(0, self._handle_connect_success, port)

        def on_error(message: str) -> None:
            self.after(0, self._handle_connect_error, message)

        self.serial_client.connect(port, on_success=on_success, on_error=on_error)

    # Function to handle the connect success event
    def _handle_connect_success(self, port: str) -> None:
        self._connect_in_progress = False
        self.synth_state.connected = True
        self.synth_state.port = port
        self.config.last_port = port
        self.audio_engine.all_notes_off()
        self._save_config()
        self._set_connection_controls(True)
        self._log(f"Connected to {port}")
        # Push the current global LFO table + filter state to the freshly connected Teensy
        self._send_lfo_table()
        self._send_lfo()
        self._refresh_display()

    def _handle_connect_error(self, message: str) -> None:
        self._connect_in_progress = False
        self.synth_state.connected = False
        self.synth_state.port = None
        self.serial_client.disconnect()
        self._set_connection_controls(False)
        self.status_label.configure(text=f"Status: Connection error ({message})")
        self._log(f"Connection error: {message}")
        self._refresh_display()

    def _on_disconnect(self) -> None:
        port = self.synth_state.port or self.port_var.get()
        if self.synth_state.is_playing:
            try:
                self.serial_client.send_all_notes_off(self.synth_state.volume_pct)
            except Exception:
                pass
        self.serial_client.disconnect()
        self.synth_state.connected = False
        self.synth_state.port = None
        self._set_connection_controls(False)
        self._log(f"Disconnected from {port}")
        self._refresh_display()

    def _on_close(self) -> None:
        self._on_stop()
        self.unbind_all("<KeyPress>")
        self.unbind_all("<KeyRelease>")
        self.midi_handler.stop()
        self.serial_client.stop_watchdog()
        self.serial_client.disconnect()
        self.audio_engine.close()
        self._save_config()
        self.destroy()


# Entry point of customTkinter app
def run_app() -> None:
    # Create main window of GUI
    app = SynthApp()
    # Keep window opened
    app.mainloop()
