"""Keyboard panel: on-screen note buttons and PC keyboard input."""

from tkinter import Entry, TclError, Text
from typing import Callable

import customtkinter as ctk

from synth.safety_limits import VOLUME_KEYBOARD_STEP, clamp_carrier_hz
from synth.synth_mode_presets import FM_PRESETS
from synth.synth_state import PC_KEYBOARD_MAPPING
from gui.synth_controller import SynthController
from gui.widgets import set_entry_text

# X11 repeats a held key as KeyRelease+KeyPress a few ms apart. Wait this long
# before treating a release as real, so a following press can cancel it.
KEY_RELEASE_DEBOUNCE_MS = 5


class KeyboardPanel:
    """Builds the note buttons with editable frequencies and handles PC keyboard input.

    PC keyboard: A S D F G H J K play notes (hold, polyphonic), + / - change the volume,
    the spacebar stops all sounds and 1..6 select presets.

    The widgets are created directly in `parent` (rows 0 to 2, column 0).

    Args:
        parent: Widget (grid layout) the keyboard widgets are created in.
        controller (SynthController): Application logic.
        on_stop (Callable[[], None]): Stops all sounds (spacebar, 'Stop Sounds' button).
        adjust_volume (Callable[[int], None]): Changes the volume by a percentage delta.
    """

    def __init__(
        self,
        parent,
        controller: SynthController,
        on_stop: Callable[[], None],
        adjust_volume: Callable[[int], None],
    ) -> None:
        self.parent = parent
        self.controller = controller
        self.state = controller.state
        self._on_stop = on_stop
        self._adjust_volume = adjust_volume

        self._pressed_keys: set[str] = set()
        self._key_release_after: dict[str, object] = {}
        self._note_buttons: dict[str, ctk.CTkButton] = {}
        self._key_freq_entries: dict[str, ctk.CTkEntry] = {}
        self._note_button_default_color: str | tuple[str, str] | None = None

        self._build()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build(self) -> None:
        parent = self.parent

        keyboard_header = ctk.CTkFrame(parent, fg_color="transparent")
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

        keyboard_frame = ctk.CTkFrame(parent, fg_color="transparent")
        keyboard_frame.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="ew")

        # Creating buttons for each key and frequency
        for index, (key, frequency_hz) in enumerate(
            self.state.key_frequencies.items()
        ):
            key_label = key.upper()
            button = ctk.CTkButton(
                keyboard_frame,
                text=f"{key_label}\n{frequency_hz:.2f} Hz",
                width=72,
                command=lambda k=key: self.controller.note_on(
                    k, self.state.key_frequencies[k]
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

        key_count = len(self.state.key_frequencies)
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
            parent,
            text="PC Keyboard: A S D F G H J K: hold, polyphonic | + / -: Volume | Spacebar: Stop Sounds",
            text_color="gray70",
        ).grid(row=2, column=0, padx=12, pady=(0, 8), sticky="w")

    # ------------------------------------------------------------------
    # Bindings
    # ------------------------------------------------------------------

    # Note: customtkinter widgets forbid bind_all, so the main window is used.
    def bind_keys(self) -> None:
        """Listen to PC keyboard events in the whole application."""
        window = self.parent.winfo_toplevel()
        window.bind_all("<KeyPress>", self._on_key_press, add="+")
        window.bind_all("<KeyRelease>", self._on_key_release, add="+")
        self.controller.log("Laptop keyboard active: A S D F G H J K")

    def unbind_keys(self) -> None:
        """Stop listening to PC keyboard events."""
        window = self.parent.winfo_toplevel()
        window.unbind_all("<KeyPress>")
        window.unbind_all("<KeyRelease>")

    # ------------------------------------------------------------------
    # Visual key state
    # ------------------------------------------------------------------

    def clear_pressed_keys(self) -> None:
        """Forget all held keys and reset the button highlighting."""
        self._cancel_pending_key_releases()
        self._pressed_keys.clear()
        for key in list(self._note_buttons):
            self._set_note_button_pressed(key, False)

    def _set_note_button_pressed(self, key: str, pressed: bool) -> None:
        button = self._note_buttons.get(key)
        if button is None:
            return
        if pressed:
            button.configure(fg_color="#1f6aa5")
        elif self._note_button_default_color is not None:
            button.configure(fg_color=self._note_button_default_color)

    # ------------------------------------------------------------------
    # Frequency editing
    # ------------------------------------------------------------------

    # Applies a manually edited frequency for a keyboard key
    def _commit_key_frequency(self, key: str) -> None:
        entry = self._key_freq_entries[key]
        raw = entry.get().strip().replace(",", ".")
        try:
            value = float(raw)
        except ValueError:
            set_entry_text(entry, self.state.key_frequencies[key], 2)
            return
        value = clamp_carrier_hz(value)
        self.state.key_frequencies[key] = value
        set_entry_text(entry, value, 2)
        self._note_buttons[key].configure(text=f"{key.upper()}\n{value:.2f} Hz")
        self.controller.save_config()

    def _reset_key_frequencies(self) -> None:
        self.state.key_frequencies = {
            key: clamp_carrier_hz(freq) for key, freq in PC_KEYBOARD_MAPPING.items()
        }
        for key, freq in self.state.key_frequencies.items():
            entry = self._key_freq_entries.get(key)
            if entry is not None:
                set_entry_text(entry, freq, 2)
            button = self._note_buttons.get(key)
            if button is not None:
                button.configure(text=f"{key.upper()}\n{freq:.2f} Hz")
        self.controller.save_config()
        self.controller.log("Keyboard frequencies reset to default")

    # ------------------------------------------------------------------
    # PC keyboard events
    # ------------------------------------------------------------------

    def _should_ignore_keyboard(self, event: object) -> bool:
        """True if the key press belongs to a text field and must not play notes."""
        widget = getattr(event, "widget", None)
        if widget is None:
            widget = self.parent.focus_get()
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

    def _on_key_press(self, event: object) -> None:
        if self._should_ignore_keyboard(event):
            return

        key = self._normalize_key(event)
        if key is not None:
            self._cancel_key_release_timer(key)
            if key in self._pressed_keys:
                return
            self._pressed_keys.add(key)
            self._set_note_button_pressed(key, True)
            self.controller.note_on(key, self.state.key_frequencies[key])
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
                self.controller.apply_preset(preset_names[index])

    def _on_key_release(self, event: object) -> None:
        if self._should_ignore_keyboard(event):
            return

        key = self._normalize_key(event)
        if key is None or key not in self._pressed_keys:
            return

        self._cancel_key_release_timer(key)
        self._key_release_after[key] = self.parent.after(
            KEY_RELEASE_DEBOUNCE_MS, self._commit_key_release, key
        )

    def _commit_key_release(self, key: str) -> None:
        self._key_release_after.pop(key, None)
        if key not in self._pressed_keys:
            return
        self._pressed_keys.discard(key)
        self._set_note_button_pressed(key, False)
        self.controller.note_off(key)

    def _cancel_key_release_timer(self, key: str) -> None:
        token = self._key_release_after.pop(key, None)
        if token is None:
            return
        try:
            self.parent.after_cancel(token)
        except TclError:
            pass

    def _cancel_pending_key_releases(self) -> None:
        for key in list(self._key_release_after):
            self._cancel_key_release_timer(key)
