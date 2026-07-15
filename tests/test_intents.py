from __future__ import annotations

import pytest

from voxmcp.intents import classify_spoken_intent, normalize_utterance
from voxmcp.models import SpokenIntent


@pytest.mark.parametrize(
    ("utterance", "intent"),
    [
        ("Stop voice mode.", SpokenIntent.STOP),
        ("switch to text", SpokenIntent.STOP),
        ("Mute!", SpokenIntent.PAUSE),
        ("hold on", SpokenIntent.PAUSE),
        ("Resume voice mode", SpokenIntent.RESUME),
        ("I'm back", SpokenIntent.RESUME),
        ("Can you repeat that?", SpokenIntent.REPEAT),
        ("Give me a second", SpokenIntent.WAIT),
        ("Over", SpokenIntent.END_TURN),
        ("That's all.", SpokenIntent.END_TURN),
    ],
)
def test_short_standalone_controls_are_recognized(
    utterance: str, intent: SpokenIntent
) -> None:
    match = classify_spoken_intent(utterance)
    assert match.intent is intent
    assert match.matched is True


@pytest.mark.parametrize(
    "utterance",
    [
        "I think we should stop voice mode from writing temporary files",
        "Please repeat the test with a larger fixture",
        "The pause implementation should retain its session",
        "What?",
        "Somewhat surprising",
        "I am done speaking about the repeat logic but have one more point",
        "Could you wait until the background task finishes and then inspect it",
    ],
)
def test_control_words_inside_content_never_hijack_the_turn(utterance: str) -> None:
    assert classify_spoken_intent(utterance).intent is SpokenIntent.NONE


@pytest.mark.parametrize(
    ("utterance", "seconds"),
    [
        ("wait 10 seconds", 10.0),
        ("please wait for five minutes", 300.0),
        ("wait for 30 minutes", 1800.0),
    ],
)
def test_bounded_wait_durations(utterance: str, seconds: float) -> None:
    match = classify_spoken_intent(utterance)
    assert match.intent is SpokenIntent.WAIT
    assert match.duration_seconds == seconds


def test_excessive_wait_is_not_accepted_as_control() -> None:
    assert classify_spoken_intent("wait 31 minutes").intent is SpokenIntent.NONE


def test_normalization_is_stable_and_does_not_match_substrings() -> None:
    assert normalize_utterance("  I'M   back… ") == "im back"
    assert classify_spoken_intent("unstoppable").intent is SpokenIntent.NONE
