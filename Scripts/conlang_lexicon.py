"""
Seed lexicon for the Conlang.

class Phoneme: 
A phoneme is a single sound. 
E.g. a 'beep', 'glide', or 'warble' sound effect. 

class Lexeme: 
A lexeme is a sequence of phonemes.
E.g. 'hello', 'human', 'yes', 'no', 'attention', 'query', 'ack'. 

class Utterance: 
An utterance is a sequence of lexemes. 
E.g. 'greet_human = hello + human', 'affirm = yes', 'alert = attention'

The dict helpers are JSON-serializable so a robot adapter can load the same
mappings later without a second player.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

PhonemeKind = Literal["beep", "glide", "warble"]

# Extra silence inserted between words in an utterance (on top of gap_after_ms).
WORD_GAP_MS = 120


@dataclass(frozen=True)
class Phoneme:
    kind: PhonemeKind
    start_hz: float
    duration_ms: int
    end_hz: float | None = None
    gap_after_ms: int = 30


@dataclass(frozen=True)
class Lexeme:
    id: str
    meaning: str
    phonemes: tuple[Phoneme, ...]


@dataclass(frozen=True)
class Utterance:
    id: str
    label: str
    lexeme_ids: tuple[str, ...]


def _beep(hz: float, duration_ms: int, gap_after_ms: int = 30) -> Phoneme:
    return Phoneme("beep", hz, duration_ms, gap_after_ms=gap_after_ms)


def _glide(start_hz: float, end_hz: float, duration_ms: int, gap_after_ms: int = 30) -> Phoneme:
    return Phoneme("glide", start_hz, duration_ms, end_hz=end_hz, gap_after_ms=gap_after_ms)


def _warble(hz: float, duration_ms: int, gap_after_ms: int = 30) -> Phoneme:
    return Phoneme("warble", hz, duration_ms, gap_after_ms=gap_after_ms)


LEXEMES: dict[str, Lexeme] = {
    "hello": Lexeme(
        "hello",
        "Hallo",
        (
            _beep(1650, 55, 30),
            _glide(1500, 2100, 110, 25),
            _beep(1900, 60, 40),
        ),
    ),
    "human": Lexeme(
        "human",
        "Mensch",
        (
            _beep(820, 90, 35),
            _beep(720, 70, 25),
            _glide(720, 1050, 130, 40),
        ),
    ),
    "yes": Lexeme(
        "yes",
        "Ja",
        (
            _beep(1700, 40, 20),
            _glide(1750, 2300, 90, 30),
        ),
    ),
    "no": Lexeme(
        "no",
        "Nein",
        (
            _beep(1300, 80, 20),
            _glide(1250, 520, 180, 40),
        ),
    ),
    "attention": Lexeme(
        "attention",
        "Achtung",
        (
            _beep(2400, 35, 45),
            _beep(2400, 35, 45),
            _beep(3100, 90, 30),
        ),
    ),
    "query": Lexeme(
        "query",
        "Nachfrage",
        (
            _beep(980, 50, 20),
            _glide(1100, 2600, 240, 40),
        ),
    ),
    "ack": Lexeme(
        "ack",
        "Verstanden",
        (
            _warble(1550, 140, 25),
            _beep(1400, 70, 30),
        ),
    ),
}

LEXEME_ORDER: tuple[str, ...] = (
    "hello",
    "human",
    "yes",
    "no",
    "attention",
    "query",
    "ack",
)

UTTERANCES: dict[str, Utterance] = {
    "greet_human": Utterance("greet_human", "Hallo, Mensch", ("hello", "human")),
    "affirm": Utterance("affirm", "Ja", ("yes",)),
    "refuse": Utterance("refuse", "Nein", ("no",)),
    "alert": Utterance("alert", "Achtung", ("attention",)),
    "ask": Utterance("ask", "Nachfrage", ("query",)),
    "acknowledge": Utterance("acknowledge", "Verstanden", ("ack",)),
}

UTTERANCE_ORDER: tuple[str, ...] = (
    "greet_human",
    "affirm",
    "refuse",
    "alert",
    "ask",
    "acknowledge",
)


def get_lexeme(lexeme_id: str) -> Lexeme:
    lexeme = LEXEMES.get(lexeme_id)
    if lexeme is None:
        raise ValueError(f"Unknown lexeme: {lexeme_id}")
    return lexeme


def get_utterance(utterance_id: str) -> Utterance:
    utterance = UTTERANCES.get(utterance_id)
    if utterance is None:
        raise ValueError(f"Unknown utterance: {utterance_id}")
    return utterance


def resolve_lexemes(lexeme_ids: list[str] | tuple[str, ...]) -> list[Lexeme]:
    return [get_lexeme(lexeme_id) for lexeme_id in lexeme_ids]


def meanings_label(lexeme_ids: list[str] | tuple[str, ...]) -> str:
    parts = [get_lexeme(lexeme_id).meaning for lexeme_id in lexeme_ids]
    return " + ".join(parts) if parts else "—"


def lexicon_to_dict() -> dict[str, Any]:
    return {
        "lexemes": {lexeme_id: asdict(lexeme) for lexeme_id, lexeme in LEXEMES.items()},
        "utterances": {
            utterance_id: asdict(utterance) for utterance_id, utterance in UTTERANCES.items()
        },
    }
