"""Privacy-preserving append-only JSONL event logging."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from .models import SessionState


_EVENT_NAME = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
_TRANSCRIPT_MARKERS = ("transcript", "utterance", "message", "prompt", "content", "text")
_SECRET_MARKERS = ("api_key", "apikey", "password", "secret", "token", "authorization")


class EventLogError(RuntimeError):
    """Raised when an event cannot be safely serialized or appended."""


class JsonlEventLogger:
    """Append compact events with raw transcripts disabled by default."""

    def __init__(
        self,
        path: str | Path,
        *,
        include_transcripts: bool = False,
        clock: Callable[[], float] = time.time,
        fsync: bool = False,
        max_event_bytes: int = 64 * 1024,
    ) -> None:
        if max_event_bytes < 1024:
            raise ValueError("max_event_bytes must be at least 1024")
        self.path = Path(path)
        self.include_transcripts = bool(include_transcripts)
        self._clock = clock
        self._fsync = fsync
        self._max_event_bytes = max_event_bytes
        self._lock = threading.Lock()

    def log(
        self,
        event: str,
        *,
        session_id: str | None = None,
        state: SessionState | str | None = None,
        data: Mapping[str, Any] | None = None,
        transcript: str | None = None,
    ) -> dict[str, Any]:
        """Append one event and return the exact safe record that was written."""

        if not isinstance(event, str) or not _EVENT_NAME.fullmatch(event):
            raise EventLogError("event name contains unsupported characters")
        if data is not None and not isinstance(data, Mapping):
            raise EventLogError("event data must be a mapping")

        timestamp = float(self._clock())
        record: dict[str, Any] = {
            "schema_version": 1,
            "timestamp": _iso_timestamp(timestamp),
            "timestamp_unix": timestamp,
            "event": event,
        }
        if session_id is not None:
            record["session_id"] = str(session_id)
        if state is not None:
            record["state"] = state.value if isinstance(state, SessionState) else str(state)
        if data:
            record["data"] = _sanitize(data, include_transcripts=self.include_transcripts)
        if transcript is not None:
            record["transcript"] = (
                transcript
                if self.include_transcripts
                else _redacted_summary(transcript)
            )

        try:
            payload = json.dumps(
                record, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8") + b"\n"
        except (TypeError, ValueError) as exc:
            raise EventLogError(f"event is not JSON serializable: {exc}") from exc
        if len(payload) > self._max_event_bytes:
            raise EventLogError(
                f"event is too large ({len(payload)} bytes; max {self._max_event_bytes})"
            )

        self._append(payload)
        return record

    def _append(self, payload: bytes) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
            fd = os.open(self.path, flags, 0o600)
            try:
                os.chmod(self.path, 0o600)
                written = 0
                while written < len(payload):
                    written += os.write(fd, payload[written:])
                if self._fsync:
                    os.fsync(fd)
            except OSError as exc:
                raise EventLogError(f"failed to append event: {exc}") from exc
            finally:
                os.close(fd)


class NullEventLogger:
    """Drop-in logger for deployments that disable event persistence."""

    def log(self, event: str, **_: Any) -> None:
        return None


def read_events(path: str | Path) -> list[dict[str, Any]]:
    """Read an event log for diagnostics and tests."""

    events: list[dict[str, Any]] = []
    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise EventLogError(f"event on line {line_number} is not an object")
                events.append(value)
    except (OSError, json.JSONDecodeError) as exc:
        raise EventLogError(f"failed to read event log: {exc}") from exc
    return events


def _sanitize(value: Any, *, include_transcripts: bool, key: str = "") -> Any:
    lowered_key = key.casefold()
    if any(marker in lowered_key for marker in _SECRET_MARKERS):
        return {"redacted": True, "kind": "secret"}
    if (
        not include_transcripts
        and any(marker in lowered_key for marker in _TRANSCRIPT_MARKERS)
    ):
        return _redacted_summary(value)

    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return {"redacted": True, "kind": "bytes", "byte_count": len(value)}
    if isinstance(value, Mapping):
        return {
            str(child_key): _sanitize(
                child_value,
                include_transcripts=include_transcripts,
                key=str(child_key),
            )
            for child_key, child_value in value.items()
        }
    if isinstance(value, Sequence):
        return [
            _sanitize(item, include_transcripts=include_transcripts, key=key)
            for item in value
        ]
    # Never use repr(value): exception and object reprs can contain credentials
    # or transcripts.  The type name is enough for diagnostics.
    return {"redacted": True, "kind": type(value).__name__}


def _redacted_summary(value: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {"redacted": True}
    if isinstance(value, str):
        summary["char_count"] = len(value)
        summary["word_count"] = len(value.split())
    elif isinstance(value, bytes):
        summary["byte_count"] = len(value)
    elif isinstance(value, Sequence):
        summary["item_count"] = len(value)
    return summary


def _iso_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )
