"""
Contains main logic of CustomTkinter GUI application

Overview of important functions: 
-------------------------------------------------------
Building up GUI window:
- _build_ui:
-> Builds up the GUI window

PC Keyboard input handling:
- _on_key_press, _on_key_release:
-> PC Keyboard input handling 

MIDI input handling:
- _on_midi_connect, _on_midi_disconnect:
-> MIDI input handling

Callback functions for state changes:
- _on_note_pressed, _on_stop, _on_modulator_changed, _on_volume_changed, _on_mod_depth_changed, _on_auto_reconnect_changed:
-> Callbacks for changing states, i. e. volume is changed and should be applied
-> Changing the respecive state, updating GUI, sending package to Teensy

Connection logic functions:
- _on_connect, _on_disconnect: 
-> For Teensy communication
- _on_midi_connect, _on_midi_disconnect:
-> For MIDI-Keyboard connection

Routing functions:
- _dispatch_voice_on, _dispatch_voice_off, _dispatch_all_notes_off, _dispatch_param_update:
-> Routing functions to EITHER play sound on audio module OR on local device
- _play_local_voice:
-> Function to play sound on local device
- _note_on, _note_off:
-> Functions to handle the note pressed and released events
- _send_current_state:
-> Function to send the current state to the audio module

Config loading and saving:
- load_config, save_config:
-> Loads and saves the configuration from/to the config.json file
-------------------------------------------------------

"""

from datetime import datetime
from tkinter import Entry, Text

import customtkinter as ctk # Python UI library based tkinter (standart python GUI toolkit)

from audio_engine import LocalSynthRouter
from config_store import AppConfig, load_config, save_config
from engines.base import MODE_LABELS, SYNTH_MODES

from safety_limits import (
    DEFAULT_VOLUME_PCT,
    MAX_MOD_DEPTH_PCT,
    MAX_MODULATOR_HZ,
    MAX_MODULATOR_RATIO,
    MAX_VOLUME_PCT,
    MIN_MODULATOR_HZ,
    MIN_MODULATOR_RATIO,
    VOLUME_KEYBOARD_STEP,
    ENVELOPE_ATTACK_MS,
    ENVELOPE_RELEASE_MS,
    MODULATOR_FADE_MS,
    clamp_mod_depth_pct,
    clamp_modulator_hz,
    clamp_modulator_ratio,
    clamp_volume_pct,
)
from midi_input import MidiCallbacks, MidiInputHandler, list_midi_ports
from serial_client import SerialClient, WatchdogCallbacks, list_com_ports
from synth_mode_presets import MODE_PRESETS, apply_mode_preset
from setup_store import SynthSetup, export_hiwi_spec, list_setups, load_setup, save_setup
from fm_utils import compute_modulator_hz
from synth_state import KEYBOARD_MAPPING, KEYBOARD_NOTE_KEYS, NOTE_MAPPING, SynthState

# Class object for GUI application based on customtkinter
class SynthApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("HIL Audio Synthesizer")
        self.geometry("800x700")
        self.minsize(600, 480)

        self.config = load_config()
        initial_mode = self.config.synth_mode if self.config.synth_mode in SYNTH_MODES else "fm"
        # Migrate legacy checkbox flag to dedicated Pure Sine mode
        if initial_mode == "fm" and self.config.pure_sine_test:
            initial_mode = "pure_sine"
        self.synth_state = SynthState(
            synth_mode=initial_mode,
            modulator_hz=self.config.modulator_hz,
            modulator_mode=self.config.modulator_mode,
            modulator_ratio=self.config.modulator_ratio,
            volume_pct=self.config.volume_pct,
            mod_depth_pct=self.config.mod_depth_pct,
            active_preset=self.config.active_preset,
            pure_sine_test=initial_mode == "pure_sine",
        )
        self.serial_client = SerialClient()
        self.midi_handler = MidiInputHandler()
        self.audio_engine = LocalSynthRouter()
        self._connect_in_progress = False
        self._midi_connect_in_progress = False
        self._pressed_keys: set[str] = set()
        self._note_buttons: dict[str, ctk.CTkButton] = {}
        self._note_button_default_color: str | tuple[str, str] | None = None

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

    # Function to build up GUI window (COM-Port/MIDI Selection, buttons, slider, ...)
    def _build_ui(self) -> None:
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

        for index, (note_name, (_, frequency_hz)) in enumerate(NOTE_MAPPING.items()):
            key_label = KEYBOARD_NOTE_KEYS[index].upper()
            button = ctk.CTkButton(
                keyboard_frame,
                text=f"{key_label}\n{note_name}\n{frequency_hz:.2f} Hz",
                width=72,
                command=lambda nid=note_name, freq=frequency_hz: self._note_on(
                    nid, freq
                ),
            )
            button.grid(row=0, column=index, padx=4, pady=4)
            self._note_buttons[KEYBOARD_NOTE_KEYS[index]] = button
            if self._note_button_default_color is None:
                self._note_button_default_color = button.cget("fg_color")

        ctk.CTkLabel(
            controls_frame,
            text="PC Keyboard: A S D F G H J K: hold, polyphonic | + / -: Volume | Spacebar: Stop Sounds",
            text_color="gray70",
        ).grid(row=2, column=0, padx=12, pady=(0, 8), sticky="w")

        sound_frame = ctk.CTkFrame(controls_frame)
        sound_frame.grid(row=3, column=0, padx=0, pady=(0, 8), sticky="ew")
        sound_frame.grid_columnconfigure(0, weight=1)

        sound_header = ctk.CTkFrame(sound_frame, fg_color="transparent")
        sound_header.grid(row=0, column=0, padx=12, pady=(12, 8), sticky="ew")
        sound_header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(sound_header, text="Sound Synthesis", font=ctk.CTkFont(size=15, weight="bold")).grid(
            row=0, column=0, sticky="w"
        )
        self.preset_value_label = ctk.CTkLabel(
            sound_header,
            text=f"Preset: {self.synth_state.active_preset}",
            text_color="gray70",
        )
        self.preset_value_label.grid(row=0, column=1, sticky="e")

        self.preset_description_label = ctk.CTkLabel(
            sound_frame,
            text="Choose synthesis mode",
            text_color="gray70",
            anchor="w",
        )
        self.preset_description_label.grid(row=1, column=0, padx=12, pady=(0, 8), sticky="ew")

        mode_frame = ctk.CTkFrame(sound_frame, fg_color="transparent")
        mode_frame.grid(row=2, column=0, padx=12, pady=(0, 8), sticky="ew")
        ctk.CTkLabel(mode_frame, text="Synthesis Mode").grid(row=0, column=0, padx=(0, 8), sticky="w")
        self.synth_mode_var = ctk.StringVar(value=MODE_LABELS[self.synth_state.synth_mode])
        self.synth_mode_switch = ctk.CTkSegmentedButton(
            mode_frame,
            values=[MODE_LABELS[mode] for mode in SYNTH_MODES],
            variable=self.synth_mode_var,
            command=self._on_synth_mode_changed,
        )
        self.synth_mode_switch.grid(row=0, column=1, sticky="w")

        self.mode_preset_buttons_frame = ctk.CTkFrame(sound_frame, fg_color="transparent")
        self.mode_preset_buttons_frame.grid(row=3, column=0, padx=12, pady=(0, 4), sticky="ew")
        self.mode_panels_frame = ctk.CTkFrame(sound_frame, fg_color="transparent")
        self.mode_panels_frame.grid(row=4, column=0, padx=12, pady=(0, 8), sticky="ew")
        self.mode_panels_frame.grid_columnconfigure(0, weight=1)
        self.mode_panels: dict[str, ctk.CTkFrame] = {}
        self._build_mode_panels()

        self.volume_label = ctk.CTkLabel(
            sound_frame, text=f"Volume: {self.synth_state.volume_pct} %"
        )
        self.volume_label.grid(row=5, column=0, padx=12, pady=(8, 4), sticky="w")
        volume_controls = ctk.CTkFrame(sound_frame, fg_color="transparent")
        volume_controls.grid(row=6, column=0, padx=12, pady=(0, 8), sticky="ew")
        volume_controls.grid_columnconfigure(0, weight=1)
        self.volume_slider = ctk.CTkSlider(
            volume_controls, from_=0, to=MAX_VOLUME_PCT, number_of_steps=MAX_VOLUME_PCT,
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
        self._show_mode_panel()
        self._style_experimental_modes()

        setup_frame = ctk.CTkFrame(controls_frame)
        setup_frame.grid(row=4, column=0, pady=(0, 8), sticky="ew")
        setup_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(setup_frame, text="Setups", font=ctk.CTkFont(size=15, weight="bold")).grid(
            row=0, column=0, columnspan=3, padx=12, pady=(12, 6), sticky="w"
        )
        ctk.CTkLabel(setup_frame, text="Load").grid(row=1, column=0, padx=12, pady=6, sticky="w")
        self.setup_load_var = ctk.StringVar(value="")
        self.setup_load_menu = ctk.CTkOptionMenu(setup_frame, variable=self.setup_load_var, values=["No setups"])
        self.setup_load_menu.grid(row=1, column=1, padx=6, pady=6, sticky="ew")
        ctk.CTkButton(setup_frame, text="Load", width=90, command=self._load_setup).grid(
            row=1, column=2, padx=(6, 12), pady=6
        )
        ctk.CTkLabel(setup_frame, text="Name").grid(row=2, column=0, padx=12, pady=6, sticky="w")
        self.setup_name_var = ctk.StringVar(value=self.config.last_setup_name)
        self.setup_name_entry = ctk.CTkEntry(setup_frame, textvariable=self.setup_name_var, placeholder_text="Setup name")
        self.setup_name_entry.grid(row=2, column=1, padx=6, pady=6, sticky="ew")
        ctk.CTkButton(setup_frame, text="Save", width=90, command=self._save_setup).grid(
            row=2, column=2, padx=(6, 12), pady=6
        )
        ctk.CTkLabel(setup_frame, text="Notes").grid(row=3, column=0, padx=12, pady=(6, 12), sticky="nw")
        self.setup_notes_entry = ctk.CTkEntry(setup_frame, placeholder_text="Optional notes")
        self.setup_notes_entry.grid(row=3, column=1, padx=6, pady=(6, 12), sticky="ew")
        ctk.CTkButton(setup_frame, text="Export spec", width=110, command=self._export_setup_spec).grid(
            row=3, column=2, padx=(6, 12), pady=(6, 12)
        )
        self._refresh_setup_list()

        ctk.CTkLabel(
            sound_frame,
            text=f"Safety limits: Volume max. {MAX_VOLUME_PCT} %",
            text_color="gray60", anchor="w",
        ).grid(row=7, column=0, padx=12, pady=(0, 12), sticky="ew")

        log_frame = ctk.CTkFrame(self)
        log_frame.grid(row=2, column=0, padx=16, pady=(0, 16), sticky="ew")
        log_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(log_frame, text="Event log", anchor="w").grid(
            row=0, column=0, padx=12, pady=(12, 4), sticky="w"
        )

        self.log_text = ctk.CTkTextbox(log_frame, height=90, state="disabled")
        self.log_text.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="ew")

    # Builds the mode panels in the GUI
    def _build_mode_panels(self) -> None:
        self._param_labels: dict[str, tuple[ctk.CTkLabel, str]] = {}
        self._param_entries: dict[str, tuple[ctk.CTkEntry, int]] = {}
        self.partial_entries: list[ctk.CTkEntry] = []

        fm = ctk.CTkFrame(self.mode_panels_frame, fg_color="transparent")
        fm.grid_columnconfigure(0, weight=1)
        self.mode_panels["fm"] = fm
        ctk.CTkLabel(fm, text="Modulator mode").grid(row=0, column=0, padx=(0, 8), sticky="w")
        self.modulator_mode_var = ctk.StringVar(
            value="Ratio" if self.synth_state.modulator_mode == "ratio" else "Fix Hz"
        )
        self.modulator_mode_switch = ctk.CTkSegmentedButton(
            fm,
            values=["Fix Hz", "Ratio"],
            variable=self.modulator_mode_var,
            command=self._on_modulator_mode_changed,
        )
        self.modulator_mode_switch.grid(row=0, column=1, sticky="w")
        self.modulator_label = ctk.CTkLabel(
            fm,
            text=f"Modulator: {self.synth_state.modulator_hz:.1f} Hz",
        )
        self.modulator_slider = ctk.CTkSlider(
            fm,
            from_=MIN_MODULATOR_HZ,
            to=MAX_MODULATOR_HZ,
            number_of_steps=int(MAX_MODULATOR_HZ - MIN_MODULATOR_HZ),
        )
        self.modulator_slider.set(self.synth_state.modulator_hz)
        self.modulator_entry = ctk.CTkEntry(fm, width=70)
        self.ratio_label = ctk.CTkLabel(
            fm,
            text=f"Ratio to note: {self.synth_state.modulator_ratio:.2f}x",
        )
        self.ratio_slider = ctk.CTkSlider(
            fm,
            from_=MIN_MODULATOR_RATIO,
            to=MAX_MODULATOR_RATIO,
            number_of_steps=int((MAX_MODULATOR_RATIO - MIN_MODULATOR_RATIO) * 100),
        )
        self.ratio_slider.set(self.synth_state.modulator_ratio)
        self.ratio_entry = ctk.CTkEntry(fm, width=70)
        self.mod_depth_label = ctk.CTkLabel(
            fm,
            text=f"Modulator depth (FM intensity): {self.synth_state.mod_depth_pct} %",
        )
        self.mod_depth_slider = ctk.CTkSlider(
            fm,
            from_=0,
            to=MAX_MOD_DEPTH_PCT,
            number_of_steps=MAX_MOD_DEPTH_PCT,
        )
        self.mod_depth_slider.set(self.synth_state.mod_depth_pct)
        self.mod_depth_entry = ctk.CTkEntry(fm, width=70)
        self._add_labeled_slider(fm, 1, self.modulator_label, self.modulator_slider, self.modulator_entry)
        self._add_labeled_slider(fm, 2, self.ratio_label, self.ratio_slider, self.ratio_entry)
        self._add_labeled_slider(fm, 3, self.mod_depth_label, self.mod_depth_slider, self.mod_depth_entry)
        self._wire_slider_entry(
            self.modulator_slider, self.modulator_entry,
            MIN_MODULATOR_HZ, MAX_MODULATOR_HZ, self._on_modulator_changed, decimals=1,
        )
        self._wire_slider_entry(
            self.ratio_slider, self.ratio_entry,
            MIN_MODULATOR_RATIO, MAX_MODULATOR_RATIO, self._on_ratio_changed, decimals=2,
        )
        self._wire_slider_entry(
            self.mod_depth_slider, self.mod_depth_entry,
            0, MAX_MOD_DEPTH_PCT, self._on_mod_depth_changed, decimals=0,
        )

        pure_sine = ctk.CTkFrame(self.mode_panels_frame, fg_color="transparent")
        self.mode_panels["pure_sine"] = pure_sine
        ctk.CTkLabel(
            pure_sine,
            text="Pure carrier sine without FM modulation (approved on Teensy).",
            text_color="gray70",
            anchor="w",
            wraplength=720,
        ).grid(row=0, column=0, sticky="ew", pady=(4, 4))

        additive = ctk.CTkFrame(self.mode_panels_frame, fg_color="transparent")
        additive.grid_columnconfigure(0, weight=1)
        self.mode_panels["additive"] = additive
        self.partial_sliders: list[ctk.CTkSlider] = []
        self.partial_labels: list[ctk.CTkLabel] = []
        for index in range(4):
            label = ctk.CTkLabel(additive, text=f"H{index + 1}: {self.synth_state.partials[index]:.2f}")
            slider = ctk.CTkSlider(additive, from_=0, to=1, number_of_steps=100)
            slider.set(self.synth_state.partials[index])
            entry = ctk.CTkEntry(additive, width=70)
            self.partial_sliders.append(slider)
            self.partial_labels.append(label)
            self.partial_entries.append(entry)
            self._add_labeled_slider(additive, index, label, slider, entry)
            self._wire_slider_entry(
                slider, entry, 0, 1,
                lambda value, i=index: self._on_partial_changed(i, value),
                decimals=2,
            )

        subtractive = ctk.CTkFrame(self.mode_panels_frame, fg_color="transparent")
        subtractive.grid_columnconfigure(0, weight=1)
        self.mode_panels["subtractive"] = subtractive
        self.waveform_var = ctk.StringVar(value=self.synth_state.waveform)
        self._add_option(subtractive, 0, "Waveform", self.waveform_var, ["sine", "triangle", "saw", "pulse"], self._on_waveform_changed)
        self.cutoff_label, self.cutoff_slider, self.cutoff_entry = self._new_slider(
            subtractive, 1, "Cutoff", 100, 8000, self.synth_state.cutoff_hz, self._on_cutoff_changed, attr="cutoff_hz", decimals=0
        )
        self.pulse_width_label, self.pulse_width_slider, self.pulse_width_entry = self._new_slider(
            subtractive, 2, "Pulse width", 0.05, 0.95, self.synth_state.pulse_width, self._on_pulse_width_changed, attr="pulse_width", decimals=2
        )

        wavetable = ctk.CTkFrame(self.mode_panels_frame, fg_color="transparent")
        wavetable.grid_columnconfigure(0, weight=1)
        self.mode_panels["wavetable"] = wavetable
        self.table_a_var = ctk.StringVar(value=self.synth_state.table_a)
        self.table_b_var = ctk.StringVar(value=self.synth_state.table_b)
        self._add_option(wavetable, 0, "Table A", self.table_a_var, ["sine", "triangle", "saw", "pulse"], self._on_table_a_changed)
        self._add_option(wavetable, 1, "Table B", self.table_b_var, ["sine", "triangle", "saw", "pulse"], self._on_table_b_changed)
        self.morph_label, self.morph_slider, self.morph_entry = self._new_slider(
            wavetable, 2, "Morph", 0, 1, self.synth_state.morph, self._on_morph_changed, attr="morph", decimals=2
        )
        self.detune_label, self.detune_slider, self.detune_entry = self._new_slider(
            wavetable, 3, "Detune (Cent)", -50, 50, self.synth_state.detune_cents, self._on_detune_changed, attr="detune_cents", decimals=1
        )

        granular = ctk.CTkFrame(self.mode_panels_frame, fg_color="transparent")
        granular.grid_columnconfigure(0, weight=1)
        self.mode_panels["granular"] = granular
        self.grain_ms_label, self.grain_ms_slider, self.grain_ms_entry = self._new_slider(
            granular, 0, "Grain length (ms)", 5, 200, self.synth_state.grain_ms, self._on_grain_ms_changed, attr="grain_ms", decimals=1
        )
        self.density_label, self.density_slider, self.density_entry = self._new_slider(
            granular, 1, "Density", 1, 40, self.synth_state.density, self._on_density_changed, attr="density", decimals=1
        )
        self.position_label, self.position_slider, self.position_entry = self._new_slider(
            granular, 2, "Position", 0, 1, self.synth_state.grain_position, self._on_position_changed, attr="grain_position", decimals=2
        )
        self.spray_label, self.spray_slider, self.spray_entry = self._new_slider(
            granular, 3, "Spray", 0, 1, self.synth_state.spray, self._on_spray_changed, attr="spray", decimals=2
        )
        self.pitch_ratio_label, self.pitch_ratio_slider, self.pitch_ratio_entry = self._new_slider(
            granular, 4, "Pitch-Ratio", 0.25, 2, self.synth_state.pitch_ratio, self._on_pitch_ratio_changed, attr="pitch_ratio", decimals=2
        )
        self._set_modulator_mode_ui()

    # Adds a labeled slider (+ optional numeric entry) to the UI
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
        label.grid(row=label_row, column=0, columnspan=2, padx=0, pady=(6, 2), sticky="w")
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

    # Disables slider change on scroll
    def _disable_slider_scroll(self, slider: ctk.CTkSlider) -> None:
        canvas = getattr(slider, "_canvas", None)
        if canvas is None:
            return
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            canvas.bind(sequence, lambda _event: "break")

    # Creates a new slider with numeric entry
    def _new_slider(
        self,
        parent: ctk.CTkFrame,
        row: int,
        title: str,
        minimum: float,
        maximum: float,
        value: float,
        callback,
        attr: str | None = None,
        decimals: int = 2,
    ) -> tuple[ctk.CTkLabel, ctk.CTkSlider, ctk.CTkEntry]:
        label = ctk.CTkLabel(parent, text=f"{title}: {self._format_param_value(value, decimals)}")
        slider = ctk.CTkSlider(parent, from_=minimum, to=maximum, number_of_steps=100)
        slider.set(value)
        entry = ctk.CTkEntry(parent, width=70)
        self._add_labeled_slider(parent, row, label, slider, entry)
        self._wire_slider_entry(slider, entry, minimum, maximum, callback, decimals=decimals)
        if attr is not None:
            self._param_labels[attr] = (label, title)
            self._param_entries[attr] = (entry, decimals)
        return label, slider, entry

    # Adds an option to the UI
    def _add_option(self, parent: ctk.CTkFrame, row: int, title: str, variable: ctk.StringVar,
                    values: list[str], callback) -> None:
        ctk.CTkLabel(parent, text=title).grid(row=row, column=0, padx=(0, 8), pady=4, sticky="w")
        ctk.CTkOptionMenu(parent, variable=variable, values=values, command=callback).grid(
            row=row, column=1, pady=4, sticky="w"
        )

    # Shows the synthesis mode panel
    def _show_mode_panel(self) -> None:
        for mode, panel in self.mode_panels.items():
            if mode == self.synth_state.synth_mode:
                panel.grid(row=0, column=0, sticky="ew")
            else:
                panel.grid_remove()
        presets = MODE_PRESETS.get(self.synth_state.synth_mode, {})
        active = presets.get(self.synth_state.active_preset)
        self.preset_value_label.configure(text=f"Preset: {self.synth_state.active_preset}")
        self.preset_description_label.configure(
            text=active.description if active else "Manually adjusted sound"
        )
        for child in self.mode_preset_buttons_frame.winfo_children():
            child.destroy()
        for index, preset_name in enumerate(presets):
            ctk.CTkButton(
                self.mode_preset_buttons_frame, text=preset_name, width=90,
                command=lambda name=preset_name: self._apply_preset(name),
            ).grid(row=index // 3, column=index % 3, padx=3, pady=2, sticky="ew")
        for column in range(3):
            self.mode_preset_buttons_frame.grid_columnconfigure(column, weight=1)

    # Refreshes the setup list in the UI
    def _refresh_setup_list(self) -> None:
        setups = list_setups()
        values = setups or ["No setups"]
        self.setup_load_menu.configure(values=values)
        preferred = self.config.last_setup_name
        self.setup_load_var.set(preferred if preferred in setups else values[0])

    # Gets the current setup 
    def _current_setup(self) -> SynthSetup:
        name = self.setup_name_var.get().strip() or self.config.last_setup_name or "Untitled"
        return SynthSetup(
            name=name, synth_mode=self.synth_state.synth_mode,
            params=self.synth_state.setup_params_dict(), notes=self.setup_notes_entry.get().strip(),
        )

    # Saves the current setup to the file system
    def _save_setup(self) -> None:
        setup = self._current_setup()
        path = save_setup(setup)
        self.setup_name_var.set(setup.name)
        self.config.last_setup_name = setup.name
        self._save_config()
        self._refresh_setup_list()
        self._log(f"Setup saved: {path.name}")

    # Loads a setup from the file system and applies it to the synth state
    def _load_setup(self) -> None:
        name = self.setup_load_var.get()
        setup = load_setup(name)
        if setup is None:
            self._log(f"Setup not found: {name}")
            return
        self._on_stop()
        self.synth_state.synth_mode = setup.synth_mode if setup.synth_mode in SYNTH_MODES else "fm"
        self.synth_state.apply_setup_params(setup.params)
        self.synth_state.pure_sine_test = self.synth_state.synth_mode == "pure_sine"
        self.synth_state.setup_name = setup.name
        self.setup_name_var.set(setup.name)
        self.setup_notes_entry.delete(0, "end")
        self.setup_notes_entry.insert(0, setup.notes)
        self.config.last_setup_name = setup.name
        self.audio_engine.set_mode(self.synth_state.synth_mode)
        self._sync_mode_controls()
        self._save_config()
        self._refresh_display()
        self._log(f"Setup loaded: {setup.name}")

    # Exports the current setup to a specification file
    def _export_setup_spec(self) -> None:
        setup = self._current_setup()
        path = export_hiwi_spec(setup)
        self._log(f"Spec exported: {path.name}")

    # Creates a value block
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

    # Sets up the keyboard bindings
    def _setup_keyboard_bindings(self) -> None:
        self.bind_all("<KeyPress>", self._on_key_press, add="+")
        self.bind_all("<KeyRelease>", self._on_key_release, add="+")
        self.focus_set()
        self._log("Laptop keyboard active: A S D F G H J K")

    # Checks if the keyboard event should be ignored (text fields have exclusive focus)
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

    # Normalizes the keyboard event
    def _normalize_key(self, event: object) -> str | None:
        char = getattr(event, "char", "") or ""
        keysym = getattr(event, "keysym", "") or ""
        if len(char) == 1 and char.isprintable():
            normalized = char.lower()
            if normalized in KEYBOARD_MAPPING:
                return normalized
        keysym_lower = keysym.lower()
        if keysym_lower in KEYBOARD_MAPPING:
            return keysym_lower
        return None

    # Sets the note button pressed state
    def _set_note_button_pressed(self, key: str, pressed: bool) -> None:
        button = self._note_buttons.get(key)
        if button is None:
            return
        if pressed:
            button.configure(fg_color="#1f6aa5")
        elif self._note_button_default_color is not None:
            button.configure(fg_color=self._note_button_default_color)

    # Adjusts the volume
    def _adjust_volume(self, delta: int) -> None:
        new_volume = clamp_volume_pct(self.synth_state.volume_pct + delta)
        self.volume_slider.set(new_volume)
        self._on_volume_changed(new_volume)

    # Handles the key press event
    def _on_key_press(self, event: object) -> None:
        if self._should_ignore_keyboard(event):
            return

        key = self._normalize_key(event)
        if key is not None:
            if key in self._pressed_keys:
                return
            self._pressed_keys.add(key)
            self._set_note_button_pressed(key, True)
            self._note_on(key, KEYBOARD_MAPPING[key])
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
            preset_names = list(MODE_PRESETS.get(self.synth_state.synth_mode, {}))
            index = int(keysym) - 1
            if index < len(preset_names):
                self._apply_preset(preset_names[index])

    # Handles the key release event
    def _on_key_release(self, event: object) -> None:
        if self._should_ignore_keyboard(event):
            return

        key = self._normalize_key(event)
        if key is None or key not in self._pressed_keys:
            return

        self._pressed_keys.discard(key)
        self._set_note_button_pressed(key, False)
        self._note_off(key)

    # Logs a message
    def _log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}\n"
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    # Saves the configuration
    def _save_config(self) -> None:
        self.config.modulator_hz = self.synth_state.modulator_hz
        self.config.modulator_mode = self.synth_state.modulator_mode
        self.config.modulator_ratio = self.synth_state.modulator_ratio
        self.config.volume_pct = self.synth_state.volume_pct
        self.config.mod_depth_pct = self.synth_state.mod_depth_pct
        self.config.active_preset = self.synth_state.active_preset
        self.config.pure_sine_test = self.synth_state.pure_sine_test
        self.config.auto_reconnect = self.auto_reconnect_var.get()
        self.config.local_audio_enabled = self.local_audio_var.get()
        self.config.synth_mode = self.synth_state.synth_mode
        self.config.last_setup_name = self.setup_name_var.get().strip()
        save_config(self.config)

    # Refreshes the MIDI list
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

    # Sets the MIDI controls
    def _set_midi_controls(self, connected: bool) -> None:
        connect_state = "disabled" if connected or self._midi_connect_in_progress else "normal"
        disconnect_state = "disabled" if not connected else "normal"
        port_state = "disabled" if connected or self._midi_connect_in_progress else "normal"

        self.midi_connect_button.configure(state=connect_state)
        self.midi_disconnect_button.configure(state=disconnect_state)
        self.midi_port_menu.configure(state=port_state)
        self.refresh_midi_button.configure(state=port_state)

    # Handles the MIDI connect event
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
            on_note_on=lambda note, freq: self.after(0, self._on_midi_note_on, note, freq),
            on_note_off=lambda note: self.after(0, self._on_midi_note_off, note),
            on_connected=lambda: self.after(0, self._handle_midi_connected, port),
            on_disconnected=lambda: self.after(0, self._handle_midi_disconnected),
            on_error=lambda message: self.after(0, self._handle_midi_error, message),
        )
        self.midi_handler.start(port, callbacks)

    # Handles the MIDI connected event
    def _handle_midi_connected(self, port: str) -> None:
        self._midi_connect_in_progress = False
        self.config.last_midi_port = port
        self._save_config()
        self._set_midi_controls(True)
        self.midi_status_label.configure(text=f"MIDI: Connected ({port})")
        self._log(f"MIDI connected: {port}")

    # Handles the MIDI disconnected event
    def _handle_midi_disconnected(self) -> None:
        self._midi_connect_in_progress = False
        self._set_midi_controls(False)
        self.midi_status_label.configure(text="MIDI: Disconnected")
        self._log("MIDI disconnected")

    # Handles the MIDI error event
    def _handle_midi_error(self, message: str) -> None:
        self._midi_connect_in_progress = False
        self.midi_handler.stop()
        self._set_midi_controls(False)
        self.midi_status_label.configure(text=f"MIDI: Error ({message})")
        self._log(f"MIDI Error: {message}")

    # Handles the MIDI disconnect event
    def _on_midi_disconnect(self) -> None:
        port = self.midi_handler.port or self.midi_port_var.get()
        self.midi_handler.stop()
        self._set_midi_controls(False)
        self.midi_status_label.configure(text="MIDI: Disconnected")
        self._log(f"MIDI disconnected from {port}")

    # Handles the MIDI note on event
    def _on_midi_note_on(self, note: int, frequency_hz: float) -> None:
        self._note_on(f"midi:{note}", frequency_hz)

    # Handles the MIDI note off event
    def _on_midi_note_off(self, note: int) -> None:
        self._note_off(f"midi:{note}")

    # Handles the pure sine test changed event (legacy; mode switch owns this now)
    def _on_pure_sine_changed(self) -> None:
        self.synth_state.pure_sine_test = self.synth_state.synth_mode == "pure_sine"
        self._save_config()
        if self.synth_state.is_playing:
            self._dispatch_param_update()

    # Starts the local audio engine
    def _start_local_audio(self) -> None:
        self.audio_engine.set_mode(self.synth_state.synth_mode)
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
            and (not self.serial_client.is_connected or not self.synth_state.serial_allowed)
        )

    # Refreshes the local audio status
    def _refresh_local_audio_status(self) -> None:
        if not hasattr(self, "local_audio_status_label"):
            return
        if not self.audio_engine.is_available:
            text = "Local Playback: not available"
        elif self.serial_client.is_connected and self.synth_state.serial_allowed:
            text = "Local Playback: Standby (Teensy active)"
        elif self.local_audio_var.get():
            text = "Local Playback: active"
        else:
            text = "Local: disabled"
        self.local_audio_status_label.configure(text=text)

    # Handles the local audio changed event
    def _on_local_audio_changed(self) -> None:
        self._save_config()
        enabled = self.local_audio_var.get()
        self._log(f"Local playback {'enabled' if enabled else 'disabled'}")
        if not enabled:
            self.audio_engine.all_notes_off()
        self._refresh_local_audio_status()

    # Sets the modulator mode UI
    def _set_modulator_mode_ui(self) -> None:
        is_ratio = self.synth_state.modulator_mode == "ratio"
        if is_ratio:
            self.modulator_label.grid_remove()
            self.modulator_slider.grid_remove()
            self.modulator_entry.grid_remove()
            self.ratio_label.grid()
            self.ratio_slider.grid()
            self.ratio_entry.grid()
        else:
            self.ratio_label.grid_remove()
            self.ratio_slider.grid_remove()
            self.ratio_entry.grid_remove()
            self.modulator_label.grid()
            self.modulator_slider.grid()
            self.modulator_entry.grid()

    # Marks the custom preset
    def _mark_custom_preset(self) -> None:
        self.synth_state.active_preset = "Custom"

    # Applies a preset
    def _apply_preset(self, preset_name: str) -> None:
        preset = MODE_PRESETS.get(self.synth_state.synth_mode, {}).get(preset_name)
        if preset is None:
            return
        apply_mode_preset(self.synth_state, self.synth_state.synth_mode, preset_name)
        self._sync_mode_controls()
        self._save_config()
        self._refresh_display()
        self._log(f"Preset '{preset_name}': {preset.description}")

        if self.synth_state.is_playing:
            self._recompute_all_voice_modulators()
            self._dispatch_param_update()

    # Syncs the mode controls
    def _sync_mode_controls(self) -> None:
        self.synth_mode_var.set(MODE_LABELS[self.synth_state.synth_mode])
        self.modulator_slider.set(self.synth_state.modulator_hz)
        self.ratio_slider.set(self.synth_state.modulator_ratio)
        self.mod_depth_slider.set(self.synth_state.mod_depth_pct)
        self.volume_slider.set(self.synth_state.volume_pct)
        self.modulator_mode_var.set("Ratio" if self.synth_state.modulator_mode == "ratio" else "Fix Hz")
        for index, slider in enumerate(self.partial_sliders):
            slider.set(self.synth_state.partials[index])
        self.waveform_var.set(self.synth_state.waveform)
        self.cutoff_slider.set(self.synth_state.cutoff_hz)
        self.pulse_width_slider.set(self.synth_state.pulse_width)
        self.table_a_var.set(self.synth_state.table_a)
        self.table_b_var.set(self.synth_state.table_b)
        self.morph_slider.set(self.synth_state.morph)
        self.detune_slider.set(self.synth_state.detune_cents)
        self.grain_ms_slider.set(self.synth_state.grain_ms)
        self.density_slider.set(self.synth_state.density)
        self.position_slider.set(self.synth_state.grain_position)
        self.spray_slider.set(self.synth_state.spray)
        self.pitch_ratio_slider.set(self.synth_state.pitch_ratio)
        self._refresh_mode_labels()
        self._sync_param_entries()
        self._set_modulator_mode_ui()
        self._show_mode_panel()
        self._style_experimental_modes()

    def _sync_param_entries(self) -> None:
        self._set_entry_text(self.volume_entry, float(self.synth_state.volume_pct), 0)
        self._set_entry_text(self.modulator_entry, float(self.synth_state.modulator_hz), 1)
        self._set_entry_text(self.ratio_entry, float(self.synth_state.modulator_ratio), 2)
        self._set_entry_text(self.mod_depth_entry, float(self.synth_state.mod_depth_pct), 0)
        for index, entry in enumerate(self.partial_entries):
            self._set_entry_text(entry, float(self.synth_state.partials[index]), 2)
        for attr, (entry, decimals) in self._param_entries.items():
            self._set_entry_text(entry, float(getattr(self.synth_state, attr)), decimals)

    # Applies grey background to experimental mode segments (approved: FM + Pure Sine)
    def _style_experimental_modes(self) -> None:
        buttons = getattr(self.synth_mode_switch, "_buttons_dict", None)
        if not buttons:
            return
        selected = self.synth_mode_switch.get()
        unselected_color = self.synth_mode_switch.cget("unselected_color")
        unselected_hover = self.synth_mode_switch.cget("unselected_hover_color")
        experimental_color = ("gray70", "gray30")
        experimental_hover = ("gray60", "gray40")
        approved = {"fm", "pure_sine"}
        for mode in SYNTH_MODES:
            label = MODE_LABELS[mode]
            button = buttons.get(label)
            if button is None or label == selected:
                continue
            if mode in approved:
                button.configure(fg_color=unselected_color, hover_color=unselected_hover)
            else:
                button.configure(fg_color=experimental_color, hover_color=experimental_hover)

    # Handles the synth mode changed event
    def _on_synth_mode_changed(self, label: str) -> None:
        mode = next((key for key, value in MODE_LABELS.items() if value == label), "fm")
        if mode == self.synth_state.synth_mode:
            return
        self._on_stop()
        self.synth_state.synth_mode = mode
        self.synth_state.pure_sine_test = mode == "pure_sine"
        self.synth_state.active_preset = "Custom"
        self.audio_engine.set_mode(mode)
        self._sync_mode_controls()
        self._save_config()
        self._refresh_display()
        if self.serial_client.is_connected and not self.synth_state.serial_allowed:
            self._log(f"Mode {MODE_LABELS[mode]} local only")
        self._log(f"Synthesis mode: {MODE_LABELS[mode]}")
        self._style_experimental_modes()

    # Updates the text labels of the currently registered mode sliders
    def _refresh_mode_labels(self) -> None:
        for attr, (label, title) in self._param_labels.items():
            value = getattr(self.synth_state, attr)
            decimals = self._param_entries.get(attr, (None, 2))[1]
            label.configure(text=f"{title}: {self._format_param_value(float(value), decimals)}")
        for index, label in enumerate(self.partial_labels):
            label.configure(text=f"H{index + 1}: {self.synth_state.partials[index]:.2f}")

    # Updates a mode parameter
    def _update_mode_param(self, attr: str, value: float) -> None:
        setattr(self.synth_state, attr, value)
        self._mark_custom_preset()
        self._save_config()
        self._refresh_display()
        self._refresh_mode_labels()
        if self.synth_state.is_playing:
            self._dispatch_param_update()

    def _on_partial_changed(self, index: int, value: float) -> None:
        self.synth_state.partials[index] = float(value)
        self._mark_custom_preset()
        self._save_config()
        self._refresh_display()
        self._refresh_mode_labels()
        if self.synth_state.is_playing:
            self._dispatch_param_update()

    # Handles change events for mode parameters
    def _on_waveform_changed(self, value: str) -> None: self._update_mode_param("waveform", value)
    def _on_cutoff_changed(self, value: float) -> None: self._update_mode_param("cutoff_hz", float(value))
    def _on_pulse_width_changed(self, value: float) -> None: self._update_mode_param("pulse_width", float(value))
    def _on_table_a_changed(self, value: str) -> None: self._update_mode_param("table_a", value)
    def _on_table_b_changed(self, value: str) -> None: self._update_mode_param("table_b", value)
    def _on_morph_changed(self, value: float) -> None: self._update_mode_param("morph", float(value))
    def _on_detune_changed(self, value: float) -> None: self._update_mode_param("detune_cents", float(value))
    def _on_grain_ms_changed(self, value: float) -> None: self._update_mode_param("grain_ms", float(value))
    def _on_density_changed(self, value: float) -> None: self._update_mode_param("density", float(value))
    def _on_position_changed(self, value: float) -> None: self._update_mode_param("grain_position", float(value))
    def _on_spray_changed(self, value: float) -> None: self._update_mode_param("spray", float(value))
    def _on_pitch_ratio_changed(self, value: float) -> None: self._update_mode_param("pitch_ratio", float(value))

    # Handles the modulator mode changed event
    def _on_modulator_mode_changed(self, value: str) -> None:
        self.synth_state.modulator_mode = "ratio" if value == "Ratio" else "fixed"
        if self.synth_state.modulator_mode == "ratio" and self.synth_state.carrier_hz is not None:
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

    # Handles the ratio changed event
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
            on_reconnected=lambda port: self.after(0, self._handle_auto_reconnected, port),
            on_reconnect_failed=lambda message: self.after(
                0, self._log, f"Auto-Reconnect failed: {message}"
            ),
            should_auto_reconnect=lambda: self.auto_reconnect_var.get(),
            get_last_port=lambda: self.config.last_port,
        )
        self.serial_client.start_watchdog(callbacks)

    # Handles the connection lost event
    def _handle_connection_lost(self) -> None:
        self.synth_state.connected = False
        self.synth_state.port = None
        self._set_connection_controls(False)
        self.status_label.configure(text="Status: Connection lost")
        self._log("Connection lost")
        self._refresh_local_audio_status()

    # Handles the auto-reconnected event
    def _handle_auto_reconnected(self, port: str) -> None:
        self._connect_in_progress = False
        self.synth_state.connected = True
        self.synth_state.port = port
        self.config.last_port = port
        self.audio_engine.all_notes_off()
        self._save_config()
        self._set_connection_controls(True)
        self._log(f"Auto-Reconnect successful: {port}")
        self._refresh_display()

    # Refreshes the port list
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

    # Sets the connection controls
    def _set_connection_controls(self, connected: bool) -> None:
        connect_state = "disabled" if connected or self._connect_in_progress else "normal"
        disconnect_state = "disabled" if not connected else "normal"
        port_state = "disabled" if connected or self._connect_in_progress else "normal"

        self.connect_button.configure(state=connect_state)
        self.disconnect_button.configure(state=disconnect_state)
        self.port_menu.configure(state=port_state)
        self.refresh_ports_button.configure(state=port_state)

    # Refreshes the UI displays
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
        self.mod_depth_label.configure(
            text=f"Modulator depth (FM intensity): {self.synth_state.mod_depth_pct} %"
        )
        self._sync_param_entries()
        self.preset_value_label.configure(
            text=f"Preset: {self.synth_state.active_preset}"
        )
        presets = MODE_PRESETS.get(self.synth_state.synth_mode, {})
        if self.synth_state.active_preset in presets:
            self.preset_description_label.configure(
                text=presets[self.synth_state.active_preset].description
            )
        else:
            self.preset_description_label.configure(text="Manually adjusted sound")

        if self.synth_state.connected and self.synth_state.port:
            self.status_label.configure(text=f"Status: Connected ({self.synth_state.port})")
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

    # Recomputes all voice modulators
    def _recompute_all_voice_modulators(self) -> None:
        self.synth_state.update_voice_modulators(self._modulator_for_carrier)

    # Gets the voice tuples
    def _voice_tuples(self) -> list[tuple[str, float, float]]:
        return [
            (v.voice_id, v.carrier_hz, v.modulator_hz)
            for v in self.synth_state.active_voices.values()
        ]

    # Dispatch functions: Routing functions to EITHER play sound on audio module OR on local device
    
    # Routing function to play sound
    def _dispatch_voice_on(self, voice_id: str) -> None:

        voice = self.synth_state.active_voices.get(voice_id)
        if voice is None:
            return

        # If Teensy is connected, send 'play sound' message to Teensy
        if self.serial_client.is_connected and self.synth_state.serial_allowed:
            # First mute all sounds
            self.audio_engine.all_notes_off()
            try:
                slot, stolen = self.serial_client.alloc_slot(voice_id) 
                # stolen:
                # If maximum amount of voices are played (defined in serial_client.TEENSY_MAX_VOICES) AND a command comes in to play a new note
                # -> New note is prioritized -> stolen note defines note that is 'overwritten' by the new note
                if stolen is not None:
                    if stolen in self.synth_state.active_voices:
                        self.note_off(stolen)
                    self.serial_client.send_note_off(
                        self.synth_state.modulator_hz,
                        self.synth_state.volume_pct,
                        self.synth_state.mod_depth_pct,
                        pure_sine=self.synth_state.pure_sine_test,
                        voice_id=slot,
                    )
                    self._log(f"Teensy voice steal: slot {slot} from {stolen}")

                # Build up and send packet to Teensy
                packet = self.serial_client.send(
                    voice.carrier_hz,
                    voice.modulator_hz,
                    self.synth_state.volume_pct,
                    self.synth_state.mod_depth_pct,
                    pure_sine=self.synth_state.pure_sine_test,
                    voice_id=slot,
                )
                self.synth_state.last_packet = packet
                self._log(f"Sent: {packet}")

            # Error handling
            except Exception as exc:
                self.synth_state.connected = False
                self.serial_client.disconnect()
                self._set_connection_controls(False)
                self.status_label.configure(text=f"Status: Send error ({exc})")
                self._log(f"Send error: {exc}")
                if self._local_audio_active():
                    self._play_local_voice(voice_id)
            self._refresh_display()
            return

        # If Teensy is not connected AND local audio button is activated, play sound on local device
        if self._local_audio_active():
            if self.serial_client.is_connected and not self.synth_state.serial_allowed:
                self._log(f"Mode {MODE_LABELS[self.synth_state.synth_mode]} local only")
            self._play_local_voice(voice_id)
            self._refresh_display()
            return

        self.status_label.configure(
            text="Status: Not connected – display only"
        )
        self._log(
            f"Note {voice.carrier_hz:.2f} Hz "
            "(no serial / local playback off)"
        )
        self._refresh_display()

    # Function to mute sound (single voice)
    def _dispatch_voice_off(self, voice_id: str) -> None:
        # If Teensy is connected, send 'mute sound' message to Teensy
        if self.serial_client.is_connected and self.synth_state.serial_allowed:
            self.audio_engine.all_notes_off()
            try:
                slot = self.serial_client.release_slot(voice_id)
                if slot is not None:
                    packet = self.serial_client.send_note_off(
                        self.synth_state.modulator_hz,
                        self.synth_state.volume_pct,
                        self.synth_state.mod_depth_pct,
                        pure_sine=self.synth_state.pure_sine_test,
                        voice_id=slot,
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

        # If Teensy is not connected AND local audio play is enabled, mute sound on local device
        if self.audio_engine.is_available and self.local_audio_var.get():
            self.audio_engine.note_off(voice_id)
            self.synth_state.last_packet = f"local:note-off:{voice_id}"
            self._log(f"Note-Off local: {voice_id}")
        # Else only display the action that would have been taken
        else:
            self._log(f"Note-Off (only display): {voice_id}")

    # Function to mute all sounds, i.e. when the button 'Stop' is pressed
    def _dispatch_all_notes_off(self) -> None:
        if self.serial_client.is_connected and self.synth_state.serial_allowed:
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

    # Function to change sound when sound is already playing
    def _dispatch_param_update(self) -> None:
        if not self.synth_state.is_playing:
            return

        # If Teensy connected, do parameter update on Teensy
        if self.serial_client.is_connected and self.synth_state.serial_allowed:
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
                        pure_sine=self.synth_state.pure_sine_test,
                        voice_id=slot,
                    )
                    self.synth_state.last_packet = packet
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
            self._log(self.synth_state.last_packet)
            self._refresh_display()

    # Function to play sound on local device
    def _play_local_voice(self, voice_id: str) -> None:
        voice = self.synth_state.active_voices.get(voice_id)
        if voice is None:
            return
        params = self.synth_state.engine_params()
        if self.synth_state.synth_mode in ("fm", "pure_sine"):
            params["modulator_hz"] = voice.modulator_hz
        self.audio_engine.note_on(
            voice.voice_id,
            voice.carrier_hz,
            params,
        )
        packet = (
            f"local:{self.synth_state.synth_mode}:{voice.voice_id}:"
            f"{voice.carrier_hz:.2f}Hz"
        )
        self.synth_state.last_packet = packet
        self._log(f"Played locally: {packet}")

    # This function is called when a note is pressed on the PC's keyboard
    def _note_on(self, voice_id: str, frequency_hz: float) -> None:
        modulator = self._modulator_for_carrier(frequency_hz)
        stolen = self.synth_state.note_on(voice_id, frequency_hz, modulator)
        if stolen and self._local_audio_active():
            self.audio_engine.note_off(stolen)
        self._refresh_display()
        self._dispatch_voice_on(voice_id)

    # Function to mute sound on local device
    # This function is called when a note is released on the PC's keyboard
    def _note_off(self, voice_id: str) -> None:
        if not self.synth_state.note_off(voice_id):
            return
        self._dispatch_voice_off(voice_id)
        self._refresh_display()

    # Function to send the current state to the audio module
    def _send_current_state(self) -> None:
        self._dispatch_param_update()

    # Function to handle the note pressed event
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

    # Function to handle the stop event
    def _on_stop(self) -> None:
        self._pressed_keys.clear()
        for key in list(self._note_buttons):
            self._set_note_button_pressed(key, False)
        self.synth_state.all_notes_off()
        self._dispatch_all_notes_off()
        self._refresh_display()

    # Function to handle the modulator changed event
    def _on_modulator_changed(self, value: float) -> None:
        self.synth_state.modulator_hz = clamp_modulator_hz(value)
        self._mark_custom_preset()
        self._save_config()
        self._refresh_display()
        if self.synth_state.is_playing:
            self._recompute_all_voice_modulators()
            self._dispatch_param_update()

    # Function to handle the volume changed event
    def _on_volume_changed(self, value: float) -> None:
        self.synth_state.volume_pct = clamp_volume_pct(value)
        self._mark_custom_preset()
        self._save_config()
        self._refresh_display()
        if self.synth_state.is_playing:
            self._dispatch_param_update()

    # Function to handle the mod depth changed event
    def _on_mod_depth_changed(self, value: float) -> None:
        self.synth_state.mod_depth_pct = clamp_mod_depth_pct(value)
        self._mark_custom_preset()
        self._save_config()
        self._refresh_display()
        if self.synth_state.is_playing:
            self._dispatch_param_update()

    # Function to handle the auto reconnect changed event
    def _on_auto_reconnect_changed(self) -> None:
        self._save_config()
        state = "enabled" if self.auto_reconnect_var.get() else "disabled"
        self._log(f"Auto-Reconnect {state}")

    # Function to handle the connect event
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
        self._refresh_display()

    # Function to handle the connect error event
    def _handle_connect_error(self, message: str) -> None:
        self._connect_in_progress = False
        self.synth_state.connected = False
        self.synth_state.port = None
        self.serial_client.disconnect()
        self._set_connection_controls(False)
        self.status_label.configure(text=f"Status: Connection error ({message})")
        self._log(f"Connection error: {message}")
        self._refresh_display()

    # Function to handle the disconnect event
    def _on_disconnect(self) -> None:
        port = self.synth_state.port or self.port_var.get()
        if self.synth_state.is_playing and self.synth_state.serial_allowed:
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

    # Function to handle the window close event
    def _on_close(self) -> None:
        self.unbind_all("<KeyPress>")
        self.unbind_all("<KeyRelease>")
        self.midi_handler.stop()
        self.serial_client.stop_watchdog()
        self.serial_client.disconnect()
        self.audio_engine.close()
        self._save_config()
        self.destroy()

# Entry point function
def run_app() -> None:
    app = SynthApp()
    app.mainloop()
