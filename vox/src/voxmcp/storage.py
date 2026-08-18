"""Bounded local audio recovery and replay storage."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
import uuid
from collections import deque
from pathlib import Path


class AudioStore:
    """Keeps latest STT/TTS files and a small replay ring, never an unbounded archive."""

    def __init__(self, root: Path, *, replay_items: int = 8, ttl_hours: int = 24) -> None:
        self.root = root
        self.latest_dir = root / "latest"
        self.replay_dir = root / "replay"
        self.work_dir = root / "work"
        self.replay_items = max(1, replay_items)
        self.ttl_seconds = max(1, ttl_hours) * 3600
        self._lock = threading.RLock()
        self._replay: deque[Path] = deque(maxlen=self.replay_items)
        for directory in (self.latest_dir, self.replay_dir, self.work_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self._load_replay()

    @property
    def latest_stt(self) -> Path:
        return self.latest_dir / "stt.wav"

    @property
    def latest_tts(self) -> Path:
        return self.latest_dir / "tts.wav"

    def new_work_path(self, kind: str, suffix: str = ".wav") -> Path:
        if kind not in {"stt", "tts"}:
            raise ValueError("kind must be stt or tts")
        return self.work_dir / f"{kind}-{uuid.uuid4().hex}{suffix}"

    def commit_stt(self, source: Path) -> Path:
        with self._lock:
            self._atomic_copy(source, self.latest_stt)
            if source != self.latest_stt:
                source.unlink(missing_ok=True)
            self.prune()
            return self.latest_stt

    def commit_tts(self, source: Path) -> Path:
        with self._lock:
            replay_path = self.replay_dir / f"tts-{time.time_ns()}-{uuid.uuid4().hex[:8]}.wav"
            os.replace(source, replay_path)
            self._atomic_copy(replay_path, self.latest_tts)
            evicted = self._replay[0] if len(self._replay) == self._replay.maxlen else None
            self._replay.append(replay_path)
            if evicted is not None and evicted not in self._replay:
                evicted.unlink(missing_ok=True)
            self._save_replay()
            self.prune()
            return replay_path

    def replay(self, offset: int = 0) -> Path | None:
        """Return the newest cached TTS file; offset 1 is the turn before it."""
        with self._lock:
            candidates = [path for path in self._replay if path.is_file()]
            if offset < 0 or offset >= len(candidates):
                return None
            return candidates[-1 - offset]

    def prune(self) -> None:
        cutoff = time.time() - self.ttl_seconds
        with self._lock:
            for path in self.work_dir.glob("*"):
                try:
                    if path.stat().st_mtime < cutoff:
                        path.unlink(missing_ok=True)
                except OSError:
                    continue
            live = deque(
                (p for p in self._replay if p.is_file()), maxlen=self.replay_items
            )
            self._replay = live
            keep = set(live)
            for path in self.replay_dir.glob("tts-*.wav"):
                if path not in keep:
                    path.unlink(missing_ok=True)
            self._save_replay()

    def status(self) -> dict[str, object]:
        with self._lock:
            return {
                "latest_stt": str(self.latest_stt) if self.latest_stt.is_file() else None,
                "latest_tts": str(self.latest_tts) if self.latest_tts.is_file() else None,
                "replay_items": len([p for p in self._replay if p.is_file()]),
                "retention_hours": self.ttl_seconds // 3600,
            }

    @staticmethod
    def _atomic_copy(source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, raw_path = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
        os.close(fd)
        temp_path = Path(raw_path)
        try:
            shutil.copyfile(source, temp_path)
            os.replace(temp_path, destination)
        finally:
            temp_path.unlink(missing_ok=True)

    @property
    def _index_path(self) -> Path:
        return self.replay_dir / "index.json"

    def _load_replay(self) -> None:
        try:
            data = json.loads(self._index_path.read_text())
            paths = [self.replay_dir / name for name in data.get("files", [])]
            self._replay.extend(path for path in paths if path.is_file())
        except (OSError, ValueError, TypeError):
            self._replay.extend(sorted(self.replay_dir.glob("tts-*.wav"))[-self.replay_items :])

    def _save_replay(self) -> None:
        payload = {"files": [path.name for path in self._replay if path.is_file()]}
        fd, raw_path = tempfile.mkstemp(prefix=".index.", dir=self.replay_dir)
        os.close(fd)
        temp_path = Path(raw_path)
        try:
            temp_path.write_text(json.dumps(payload, separators=(",", ":")))
            os.replace(temp_path, self._index_path)
        finally:
            temp_path.unlink(missing_ok=True)

