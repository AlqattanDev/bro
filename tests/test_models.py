from __future__ import annotations

from voxmcp.models import TurnResult, TurnStatus


def test_turn_result_safe_dict_omits_raw_transcript_by_default() -> None:
    result = TurnResult(
        status=TurnStatus.COMPLETED,
        session_id="session-1",
        transcript="private words",
        backend="whisper.cpp",
        timings={"record_ms": 100.5},
    )

    safe = result.to_dict()
    assert "transcript" not in safe
    assert safe["transcript_redacted"] is True
    assert safe["transcript_char_count"] == len("private words")

    explicit = result.to_dict(include_transcript=True)
    assert explicit["transcript"] == "private words"
