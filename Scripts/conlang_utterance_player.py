"""Compiles Conlang utterances ('greet_human = hello + human', 'affirm = yes', 'alert = attention')
and lexemes (list of phonemes) into timed synth events (note on, retune, note off) and plays them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from conlang_lexicon import (
    WORD_GAP_MS,
    Lexeme,
    Phoneme,
    resolve_lexemes,
)
from safety_limits import clamp_carrier_hz

CONLANG_VOICE_ID = "conlang:0"
GLIDE_STEP_MS = 16
WARBLES_DEPTH_RATIO = 0.06
ACTION_NOTE_ON = "note_on"
ACTION_RETUNE = "retune"
ACTION_NOTE_OFF = "note_off"

ScheduleFn = Callable[[int, Callable[[], None]], object]
CancelFn = Callable[[object], None]
FreqFn = Callable[[float], None]
VoidFn = Callable[[], None]


@dataclass(frozen=True)
class TimedEvent:
    """Data class representing a timed event (note on, retune, note off)."""

    t_ms: int
    action: str
    freq_hz: float


def _hz(value: float) -> float:
    return clamp_carrier_hz(value)


# Function to compile a glide into a list of timed events
def _compile_glide(
    start_hz: float, end_hz: float, duration_ms: int, t0: int
) -> list[TimedEvent]:
    events = [TimedEvent(t0, ACTION_NOTE_ON, _hz(start_hz))]
    if duration_ms <= GLIDE_STEP_MS:
        events.append(TimedEvent(t0 + duration_ms, ACTION_RETUNE, _hz(end_hz)))
        events.append(TimedEvent(t0 + duration_ms, ACTION_NOTE_OFF, _hz(end_hz)))
        return events

    steps = max(1, duration_ms // GLIDE_STEP_MS)
    for i in range(1, steps + 1):
        progress = i / steps
        freq = start_hz + (end_hz - start_hz) * progress
        t = t0 + min(duration_ms, i * GLIDE_STEP_MS)
        events.append(TimedEvent(t, ACTION_RETUNE, _hz(freq)))
    events.append(TimedEvent(t0 + duration_ms, ACTION_NOTE_OFF, _hz(end_hz)))
    return events


# Function to compile a warble into a list of timed events
def _compile_warble(start_hz: float, duration_ms: int, t0: int) -> list[TimedEvent]:
    events = [TimedEvent(t0, ACTION_NOTE_ON, _hz(start_hz))]
    depth = start_hz * WARBLES_DEPTH_RATIO
    steps = max(1, duration_ms // GLIDE_STEP_MS)
    offsets = (0.0, 1.0, 0.0, -1.0)
    for i in range(1, steps):
        freq = start_hz + depth * offsets[i % 4]
        events.append(TimedEvent(t0 + i * GLIDE_STEP_MS, ACTION_RETUNE, _hz(freq)))
    events.append(TimedEvent(t0 + duration_ms, ACTION_NOTE_OFF, _hz(start_hz)))
    return events


# Function to compile a phoneme (beep, glide, or warble) into a list of timed events
def _compile_phoneme(phoneme: Phoneme, t0: int) -> tuple[list[TimedEvent], int]:
    duration = max(1, int(phoneme.duration_ms))
    start_hz = _hz(phoneme.start_hz)
    if phoneme.kind == "glide":
        end_hz = _hz(phoneme.end_hz if phoneme.end_hz is not None else phoneme.start_hz)
        events = _compile_glide(start_hz, end_hz, duration, t0)
    elif phoneme.kind == "warble":
        events = _compile_warble(start_hz, duration, t0)
    # If the phoneme is a beep, compile a note on and note off event
    else:
        events = [
            TimedEvent(t0, ACTION_NOTE_ON, start_hz),
            TimedEvent(t0 + duration, ACTION_NOTE_OFF, start_hz),
        ]
    t_end = t0 + duration + max(0, int(phoneme.gap_after_ms))
    return events, t_end


# Function to compile lexemes (list of phonemes) into a list of timed events
def compile_lexemes(lexemes: list[Lexeme]) -> list[TimedEvent]:
    """Compile lexemes (list of phonemes) into a list of timed events."""
    events: list[TimedEvent] = []
    t = 0
    for index, lexeme in enumerate(lexemes):
        for phoneme in lexeme.phonemes:
            chunk, t = _compile_phoneme(phoneme, t)
            events.extend(chunk)
        if index < len(lexemes) - 1:
            t += WORD_GAP_MS
    return events


def compile_utterance(lexeme_ids: list[str] | tuple[str, ...]) -> list[TimedEvent]:
    """Compile an utterance (list of lexeme ids) into a list of timed events."""
    return compile_lexemes(resolve_lexemes(lexeme_ids))


class UtterancePlayer:
    """Class to play a list of timed events (note on, retune, note off).

    Attributes:
        schedule (ScheduleFn): Function to schedule a timed event.
        cancel (CancelFn): Function to cancel a timed event.
        on_note_on (FreqFn): Function to handle note on events.
        on_retune (FreqFn): Function to handle retune events.
        on_note_off (VoidFn): Function to handle note off events.
    """

    def __init__(
        self,
        schedule: ScheduleFn,
        cancel: CancelFn,
        on_note_on: FreqFn,
        on_retune: FreqFn,
        on_note_off: VoidFn,
        on_finished: VoidFn | None = None,
    ) -> None:
        self._schedule = schedule
        self._cancel = cancel
        self._on_note_on = on_note_on
        self._on_retune = on_retune
        self._on_note_off = on_note_off
        self._on_finished = on_finished
        # List of scheduled events
        self._tokens: list[object] = []
        self._playing = False

    @property
    def is_playing(self) -> bool:
        """Check if the utterance player is playing."""
        return self._playing

    def play(self, events: list[TimedEvent]) -> None:
        """Schedule the list of timed events to play.

        ... by appending the events to the _tokens list.

        Args:
            events (list[TimedEvent]): The list of timed events to play.
        """
        self.stop()
        if not events:
            if self._on_finished is not None:
                self._on_finished()
            return

        self._playing = True
        for event in events:
            # _tokens: list of scheduled events
            # self._schedule: function to schedule an event
            # self._make_fire: function to fire an event
            self._tokens.append(
                self._schedule(max(0, event.t_ms), self._make_fire(event))
            )

        last_t = max(event.t_ms for event in events)
        self._tokens.append(self._schedule(max(0, last_t), self._mark_finished))

    def stop(self) -> None:
        """Stop playing the list of timed events."""
        self._playing = False
        tokens = self._tokens
        self._tokens = []
        for token in tokens:
            try:
                self._cancel(token)
            except Exception:
                pass

    def _make_fire(self, event: TimedEvent) -> Callable[[], None]:
        """Make a function to fire the timed event."""

        def _fire() -> None:
            if not self._playing:
                return
            if event.action == ACTION_NOTE_ON:
                self._on_note_on(event.freq_hz)
            elif event.action == ACTION_RETUNE:
                self._on_retune(event.freq_hz)
            elif event.action == ACTION_NOTE_OFF:
                self._on_note_off()

        return _fire

    def _mark_finished(self) -> None:
        if not self._playing:
            return
        self._playing = False
        self._tokens = []
        if self._on_finished is not None:
            self._on_finished()
