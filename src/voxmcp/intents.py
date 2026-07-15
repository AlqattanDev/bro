"""Conservative whole-utterance spoken control intent recognition."""

from __future__ import annotations

import re
import unicodedata
from types import MappingProxyType

from .models import IntentMatch, SpokenIntent


# These are intentionally small exact-match sets.  A control command must be
# the entire utterance; prose that happens to contain "stop" or "repeat" is not
# commandeered by the voice layer.
_PHRASES = MappingProxyType(
    {
        SpokenIntent.STOP: frozenset(
            {
                "stop",
                "stop voice mode",
                "please stop voice mode",
                "exit voice mode",
                "end voice mode",
                "turn voice mode off",
                "close voice mode",
                "switch to text",
                "switch back to text",
                "stop the survey",
            }
        ),
        SpokenIntent.PAUSE: frozenset(
            {
                "pause",
                "pause voice mode",
                "please pause",
                "hold on",
                "hang on",
                "mute",
                "mute voice mode",
            }
        ),
        SpokenIntent.RESUME: frozenset(
            {
                "resume",
                "resume voice mode",
                "please resume",
                "continue listening",
                "im back",
            }
        ),
        SpokenIntent.REPEAT: frozenset(
            {
                "repeat",
                "repeat that",
                "please repeat",
                "say that again",
                "can you repeat that",
            }
        ),
        SpokenIntent.WAIT: frozenset(
            {
                "wait",
                "please wait",
                "wait a moment",
                "give me a second",
                "give me a minute",
            }
        ),
        SpokenIntent.END_TURN: frozenset(
            {
                "over",
                "end turn",
                "end my turn",
                "done speaking",
                "im done",
                "thats all",
                "send it",
            }
        ),
    }
)

_PUNCTUATION = re.compile(r"[^\w\s]", flags=re.UNICODE)
_WHITESPACE = re.compile(r"\s+")
_WAIT_DURATION = re.compile(
    r"^(?:please\s+)?wait(?:\s+for)?\s+"
    r"(?P<amount>\d{1,3}|one|two|three|four|five|ten)\s+"
    r"(?P<unit>seconds?|minutes?)$"
)
_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "ten": 10,
}


def normalize_utterance(text: str) -> str:
    """Normalize punctuation and whitespace without changing word content."""

    if not isinstance(text, str):
        return ""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    # Apostrophes are removed so "I'm" and "that's" match stable phrases.
    normalized = normalized.replace("'", "").replace("’", "")
    normalized = _PUNCTUATION.sub(" ", normalized)
    return _WHITESPACE.sub(" ", normalized).strip()


def classify_spoken_intent(text: str) -> IntentMatch:
    """Classify an utterance only when it exactly matches a control command."""

    normalized = normalize_utterance(text)
    if not normalized or len(normalized) > 80 or len(normalized.split()) > 8:
        return IntentMatch(SpokenIntent.NONE, normalized)

    for intent, phrases in _PHRASES.items():
        if normalized in phrases:
            return IntentMatch(intent, normalized, matched_phrase=normalized)

    wait_match = _WAIT_DURATION.fullmatch(normalized)
    if wait_match:
        raw_amount = wait_match.group("amount")
        amount = _NUMBER_WORDS.get(raw_amount, int(raw_amount) if raw_amount.isdigit() else 0)
        unit = wait_match.group("unit")
        seconds = float(amount * (60 if unit.startswith("minute") else 1))
        # A spoken wait is bounded.  Longer absences should use an explicit
        # session pause so a transcription mistake cannot wedge the channel.
        if 1 <= seconds <= 30 * 60:
            return IntentMatch(
                SpokenIntent.WAIT,
                normalized,
                matched_phrase=normalized,
                duration_seconds=seconds,
            )

    return IntentMatch(SpokenIntent.NONE, normalized)


# A short alias is convenient for adapters and remains unambiguous.
parse_spoken_intent = classify_spoken_intent
