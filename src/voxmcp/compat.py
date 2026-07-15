"""Safe adapters to the frozen VoiceMode compatibility implementation."""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .errors import VoxError


@dataclass(slots=True)
class LegacyResult:
    success: bool
    command: list[str]
    output: str
    exit_code: int

    def to_dict(self) -> dict[str, object]:
        return {
            "success": self.success,
            "command": self.command,
            "output": self.output,
            "exit_code": self.exit_code,
            "implementation": "frozen VoiceMode 8.11.0 compatibility layer",
        }


class LegacyCompatibility:
    """Delegates mature fringe features without exposing an arbitrary shell."""

    def __init__(
        self,
        *,
        tts_base_url: str,
        stt_base_url: str,
        base_dir: Path,
        timeout: float = 120.0,
    ) -> None:
        self.timeout = timeout
        self.base_dir = base_dir
        self.environment = os.environ.copy()
        for key in (
            "OPENAI_API_KEY",
            "AZURE_OPENAI_API_KEY",
            "CARTESIA_API_KEY",
            "VOICEMODE_MCP_TOKEN",
            "VOICEMODE_MCP_URL",
        ):
            self.environment.pop(key, None)
        self.environment.update(
            {
                "VOICEMODE_TTS_BASE_URLS": tts_base_url,
                "VOICEMODE_STT_BASE_URLS": stt_base_url,
                "VOICEMODE_PREFER_LOCAL": "true",
                "VOICEMODE_ALWAYS_TRY_LOCAL": "true",
                "VOICEMODE_CONNECT_ENABLED": "false",
                "VOICEMODE_BASE_DIR": str(base_dir),
                "NO_PROXY": "127.0.0.1,localhost,::1",
                "no_proxy": "127.0.0.1,localhost,::1",
            }
        )

    async def run(self, args: list[str], *, timeout: float | None = None) -> LegacyResult:
        command = [sys.executable, "-m", "voice_mode", *args]
        try:
            completed = await asyncio.to_thread(
                subprocess.run,
                command,
                env=self.environment,
                capture_output=True,
                text=True,
                timeout=timeout or self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise VoxError(f"Compatibility command timed out: {' '.join(args[:2])}") from exc
        output = (completed.stdout + completed.stderr).strip()
        if len(output) > 20_000:
            output = output[-20_000:]
        return LegacyResult(
            success=completed.returncode == 0,
            command=args,
            output=output,
            exit_code=completed.returncode,
        )

    async def dj(
        self,
        action: str,
        *,
        target: str | None = None,
        volume: int | None = None,
        limit: int = 50,
    ) -> LegacyResult:
        allowed = {
            "play", "status", "pause", "resume", "stop", "next", "prev",
            "volume", "history", "favorite", "find", "library_scan", "library_stats",
        }
        if action not in allowed:
            raise VoxError(f"Unsupported DJ action: {action}")
        args = ["dj", action]
        if action == "find":
            if not target:
                raise VoxError("DJ find requires a search query")
            args = ["dj", "find", target]
            args.extend(["--limit", str(max(1, min(200, limit)))])
            return await self.run(args)
        if action == "library_scan":
            args = ["dj", "library", "scan"]
            if target:
                library_path = Path(target).expanduser().resolve()
                if not library_path.is_dir():
                    raise VoxError(f"Music library path is not a directory: {library_path}")
                args.extend(["--path", str(library_path)])
            return await self.run(args, timeout=300.0)
        if action == "library_stats":
            return await self.run(["dj", "library", "stats"])
        if action == "play":
            if not target:
                raise VoxError("DJ play requires a local path")
            parsed = urlsplit(target)
            if parsed.scheme not in {"", "file"}:
                raise VoxError("Vox local-only mode rejects remote DJ URLs")
            local_path = Path(parsed.path if parsed.scheme == "file" else target).expanduser()
            if not local_path.exists():
                raise VoxError(f"DJ file does not exist: {local_path}")
            args.append(str(local_path.resolve()))
        if volume is not None:
            if not 0 <= volume <= 100:
                raise VoxError("Volume must be 0-100")
            if action == "volume":
                args = ["dj", "volume", str(volume)]
            elif action == "play":
                args.extend(["--volume", str(volume)])
        elif action == "volume":
            args = ["dj", "volume"]
        return await self.run(args)

    async def soundfonts(self, enabled: bool) -> LegacyResult:
        return await self.run(["soundfonts", "on" if enabled else "off"])

    async def clone(
        self,
        action: str,
        name: str | None = None,
        audio: Path | None = None,
        reference_text: str | None = None,
    ) -> LegacyResult:
        if action not in {"list", "add", "remove", "show"}:
            raise VoxError(f"Unsupported clone action: {action}")
        if action != "list" and (
            not name or re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", name) is None
        ):
            raise VoxError(
                "Clone names must be 1-64 lowercase letters, digits, underscores, or hyphens"
            )
        if action == "show":
            try:
                payload = json.loads((self.base_dir / "voices.json").read_text())
                profile = payload.get("voices", {}).get(name)
            except (OSError, ValueError, TypeError):
                profile = None
            if not isinstance(profile, dict):
                return LegacyResult(False, ["clone", "show", str(name)], "profile not found", 1)
            return LegacyResult(
                True,
                ["clone", "show", str(name)],
                json.dumps({"name": name, **profile}, indent=2, sort_keys=True),
                0,
            )
        args = ["clone", action]
        if action in {"add", "remove", "show"} and not name:
            raise VoxError(f"Clone {action} requires a name")
        if name:
            args.append(name)
        if action == "add":
            if audio is None or not audio.is_file():
                raise VoxError("Clone add requires an existing local audio file")
            args.append(str(audio.resolve()))
            if reference_text:
                args.extend(["--ref-text", reference_text])
            # The vendored 8.11.0 add command otherwise writes a remote `ms2`
            # default into the profile. Vox never creates a non-loopback route.
            args.extend(["--base-url", "http://127.0.0.1:8890/v1"])
        return await self.run(args, timeout=300.0)

    async def exchanges(self, action: str = "list") -> LegacyResult:
        if action not in {"list", "stats", "conversations"}:
            raise VoxError(f"Unsupported exchanges action: {action}")
        mapped = "view" if action in {"list", "conversations"} else action
        return await self.run(["exchanges", mapped])
