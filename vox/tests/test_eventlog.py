from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from voxmcp.eventlog import EventLogError, JsonlEventLogger, read_events
from voxmcp.models import SessionState


def test_default_logger_never_persists_raw_transcript_or_secrets(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    logger = JsonlEventLogger(path, clock=lambda: 1_700_000_000.0, fsync=True)
    raw = "My private spoken transcript contains project zephyr"

    record = logger.log(
        "turn.transcribed",
        session_id="session-1",
        state=SessionState.PROCESSING,
        transcript=raw,
        data={
            "backend": "whisper.cpp",
            "transcript": raw,
            "nested": {"message_text": raw},
            "api_key": "do-not-log-this",
            "duration_ms": 125,
        },
    )

    serialized = path.read_text()
    assert raw not in serialized
    assert "do-not-log-this" not in serialized
    assert record["transcript"] == {
        "redacted": True,
        "char_count": len(raw),
        "word_count": len(raw.split()),
    }
    event = read_events(path)[0]
    assert event["data"]["backend"] == "whisper.cpp"
    assert event["data"]["transcript"]["redacted"] is True
    assert event["data"]["api_key"] == {"kind": "secret", "redacted": True}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_raw_transcripts_require_explicit_opt_in(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    logger = JsonlEventLogger(path, include_transcripts=True)
    logger.log(
        "turn.transcribed",
        transcript="explicit transcript",
        data={"text": "nested transcript", "token": "still-secret"},
    )

    event = read_events(path)[0]
    assert event["transcript"] == "explicit transcript"
    assert event["data"]["text"] == "nested transcript"
    assert event["data"]["token"] == {"kind": "secret", "redacted": True}


def test_each_append_is_a_valid_json_line(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    logger = JsonlEventLogger(path)
    for index in range(20):
        logger.log("state.transition", data={"revision": index})

    lines = path.read_text().splitlines()
    assert len(lines) == 20
    assert [json.loads(line)["data"]["revision"] for line in lines] == list(range(20))


def test_invalid_or_oversized_events_fail_before_append(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    logger = JsonlEventLogger(path, max_event_bytes=1024, include_transcripts=True)

    with pytest.raises(EventLogError):
        logger.log("event with spaces")
    with pytest.raises(EventLogError):
        logger.log("turn", transcript="x" * 2_000)
    assert path.exists() is False
