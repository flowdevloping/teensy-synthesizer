"""Conlang panel: play words and phrases of the constructed language."""

from typing import Callable

import customtkinter as ctk

from conlang.conlang_lexicon import (
    LEXEME_ORDER,
    LEXEMES,
    UTTERANCE_ORDER,
    UTTERANCES,
    get_utterance,
    meanings_label,
)
from conlang.conlang_utterance_player import (
    CONLANG_VOICE_ID,
    UtterancePlayer,
    compile_utterance,
)
from gui.synth_controller import SynthController


class ConlangPanel:
    """Builds the conlang controls and schedules utterance playback.

    Playback runs through the same note callbacks as keyboard notes, on the voice
    `CONLANG_VOICE_ID`.

    Args:
        parent: Widget the panel frame is created in.
        controller (SynthController): Application logic.
        on_stop (Callable[[], None]): Stops all sounds ('Stop' button).

    Attributes:
        frame (ctk.CTkFrame): The panel frame. The caller places it in the layout.
    """

    def __init__(
        self,
        parent,
        controller: SynthController,
        on_stop: Callable[[], None],
    ) -> None:
        self.controller = controller
        self._on_stop = on_stop

        self.frame = ctk.CTkFrame(parent)
        self._utterance_player = UtterancePlayer(
            schedule=self._schedule_event,
            cancel=self._cancel_event,
            on_note_on=lambda freq: controller.note_on(CONLANG_VOICE_ID, freq),
            on_retune=lambda freq: controller.retune_voice(CONLANG_VOICE_ID, freq),
            on_note_off=lambda: controller.note_off(CONLANG_VOICE_ID),
            on_finished=self._on_utterance_finished,
        )
        self._build()

    def _build(self) -> None:
        conlang_frame = self.frame
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
            play_row, text="Play", width=80, command=self._on_play
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

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------

    def speak(self, lexeme_ids: list[str]) -> None:
        """Play a sequence of lexemes."""
        try:
            events = compile_utterance(lexeme_ids)
            label = meanings_label(lexeme_ids)
        except ValueError as exc:
            self.controller.log(f"Conlang speak failed: {exc}")
            return
        self.stop(release=True)
        self.conlang_status_label.configure(text=f"Speaking: {label}")
        self._utterance_player.play(events)
        self.controller.log(f"Conlang speak: {label}")

    def stop(self, release: bool = True) -> None:
        """Cancel the running utterance, optionally releasing its voice."""
        self._utterance_player.stop()
        if release:
            self.controller.note_off(CONLANG_VOICE_ID)

    def reset_status(self) -> None:
        """Show that nothing is spoken."""
        self.conlang_status_label.configure(text="Speaking: —")

    def _on_play(self) -> None:
        label = self.conlang_utterance_var.get()
        utterance_id = next(
            (uid for uid in UTTERANCE_ORDER if UTTERANCES[uid].label == label),
            None,
        )
        if utterance_id is None:
            self.controller.log(f"Unknown utterance: {label}")
            return
        utterance = get_utterance(utterance_id)
        self.speak(list(utterance.lexeme_ids))

    def _on_utterance_finished(self) -> None:
        self.reset_status()
        self.controller.log("Conlang utterance finished")

    def _schedule_event(self, delay_ms: int, callback) -> object:
        return self.frame.after(max(0, int(delay_ms)), callback)

    def _cancel_event(self, token: object) -> None:
        self.frame.after_cancel(token)
