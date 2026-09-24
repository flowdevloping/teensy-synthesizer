"""Defines linguistic elements of the custom conlang.

This script defines phonemes, lexemes and utterances which form the building blocks of the custom conlang.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

PhonemeKind = Literal["beep", "glide", "warble"]

# Extra silence inserted between words in an utterance (on top of gap_after_ms).
WORD_GAP_MS = 120


@dataclass(frozen=True)
class Phoneme:
    """Represents the smallest meaning-distinguishing unit of the custom conlang.

    In our case a Phoneme is a single sound effect, e.g. a 'beep', 'glide', or 'warble' or whatever sound effect.

    Attributes:
        kind (PhonemeKind): The type of phoneme.
        start_hz (float): The starting frequency of the phoneme.
        duration_ms (int): The duration of the phoneme in milliseconds.
        end_hz (float | None): The ending frequency of the phoneme.
        gap_after_ms (int): The gap after the phoneme in milliseconds.
    """

    kind: PhonemeKind
    start_hz: float
    duration_ms: int
    end_hz: float | None = None
    gap_after_ms: int = 30


def _beep(hz: float, duration_ms: int, gap_after_ms: int = 30) -> Phoneme:
    return Phoneme("beep", hz, duration_ms, gap_after_ms=gap_after_ms)


def _glide(
    start_hz: float, end_hz: float, duration_ms: int, gap_after_ms: int = 30
) -> Phoneme:
    return Phoneme(
        "glide", start_hz, duration_ms, end_hz=end_hz, gap_after_ms=gap_after_ms
    )


def _warble(hz: float, duration_ms: int, gap_after_ms: int = 30) -> Phoneme:
    return Phoneme("warble", hz, duration_ms, gap_after_ms=gap_after_ms)


@dataclass(frozen=True)
class Lexeme:
    """Represents a lexeme of the custom conlang.

    In our case we choose lexemes we want to represent, e.g. 'hello', 'human', 'yes', 'no', 'attention', 'query', 'ack'.
    Then we define the sequence of phonemes that make up the lexeme, e.g. 'hello' = ('beep', 'glide', 'beep').

    Attributes:
        id (str): The unique identifier of the lexeme.
        meaning (str): The meaning of the lexeme in the target language.
        phonemes (tuple[Phoneme, ...]): The sequence of phonemes that make up the lexeme.
    """

    id: str
    meaning: str
    phonemes: tuple[Phoneme, ...]


@dataclass(frozen=True)
class Utterance:
    """Represents an utterance of the custom conlang.

    In our case we define utterances we want to represent, e.g. 'greet_human', 'affirm', 'refuse', 'alert', 'ask', 'acknowledge'.
    Then we define the sequence of lexemes that make up the utterance, e.g. 'greet_human' = ('hello', 'human').

    Attributes:
        id (str): The unique identifier of the utterance.
        label (str): The label of the utterance in the target language.
        lexeme_ids (tuple[str, ...]): The sequence of lexemes that make up the utterance.
    """

    id: str
    label: str
    lexeme_ids: tuple[str, ...]


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
            _beep(500, 35, 45),
            _beep(500, 35, 45),
            _beep(500, 90, 30),
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
    """Get a lexeme by its id.

    Get a lexeme by its id from the LEXEMES dictionary.


    Args:
        lexeme_id (str): The id of the lexeme to get.

    Returns:
        Lexeme (dataclass: Lexeme): The lexeme with the given id.

    Raises:
        ValueError: If the lexeme is not found in the LEXEMES dictionary.
    """

    lexeme = LEXEMES.get(lexeme_id)
    if lexeme is None:
        raise ValueError(f"Unknown lexeme: {lexeme_id}")
    return lexeme


def get_utterance(utterance_id: str) -> Utterance:
    """Get an utterance by its id.

    Get an utterance by its id from the UTTERANCES dictionary.

    Args:
        utterance_id (str): The id of the utterance to get.

    Returns:
        Utterance (dataclass: Utterance): The utterance with the given id.

    Raises:
        ValueError: If the utterance is not found in the UTTERANCES dictionary.
    """

    utterance = UTTERANCES.get(utterance_id)
    if utterance is None:
        raise ValueError(f"Unknown utterance: {utterance_id}")
    return utterance


def resolve_lexemes(lexeme_ids: list[str] | tuple[str, ...]) -> list[Lexeme]:
    """Resolve a list of lexeme ids to a list of lexemes.

    ...by calling the get_lexeme function for each lexeme id.

    Args:
        lexeme_ids (list[str] | tuple[str, ...]): The list of lexeme ids to resolve.

    Returns:
        list[Lexeme]: The list of lexemes.
    """

    return [get_lexeme(lexeme_id) for lexeme_id in lexeme_ids]


def meanings_label(lexeme_ids: list[str] | tuple[str, ...]) -> str:
    """Resolve a list of lexeme ids to a string of the meanings of the lexemes.

    Resolve a list of lexeme ids to a string of the meanings of the lexemes by calling the get_lexeme function for each lexeme id and joining the meanings with a ' + ' separator.

    Args:
        lexeme_ids (list[str] | tuple[str, ...]): The list of lexeme ids to resolve.

    Returns:
        str: The string of the meanings of the lexemes.
    """

    parts = [get_lexeme(lexeme_id).meaning for lexeme_id in lexeme_ids]
    return " + ".join(parts) if parts else "—"


def lexicon_to_dict() -> dict[str, Any]:
    """Convert the lexicon to a dictionary.

    Convert the lexicon to a dictionary by converting the LEXEMES and UTTERANCES dictionaries to dictionaries of dictionaries using the asdict function.

    Returns:
        dict[str, Any]: The dictionary of the lexicon.
    """

    return {
        "lexemes": {lexeme_id: asdict(lexeme) for lexeme_id, lexeme in LEXEMES.items()},
        "utterances": {
            utterance_id: asdict(utterance)
            for utterance_id, utterance in UTTERANCES.items()
        },
    }
