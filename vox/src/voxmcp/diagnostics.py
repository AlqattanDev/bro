"""Truthful, side-effect-light runtime diagnostics."""

from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Any

import sounddevice as sd

from . import __version__


def audio_devices() -> dict[str, Any]:
    try:
        devices = sd.query_devices()
        default_input, default_output = sd.default.device
        normalized = []
        for index, device in enumerate(devices):
            normalized.append(
                {
                    "index": index,
                    "name": str(device["name"]),
                    "input_channels": int(device["max_input_channels"]),
                    "output_channels": int(device["max_output_channels"]),
                    "default_sample_rate": float(device["default_samplerate"]),
                    "is_default_input": index == default_input,
                    "is_default_output": index == default_output,
                }
            )
        return {
            "available": True,
            "default_input": default_input,
            "default_output": default_output,
            "devices": normalized,
        }
    except Exception as exc:
        return {
            "available": False,
            "error": f"{type(exc).__name__}: {exc}",
            "devices": [],
        }


def dependency_status() -> dict[str, Any]:
    commands = {
        "ffmpeg": shutil.which("ffmpeg"),
        "ffplay": shutil.which("ffplay"),
        "afplay": shutil.which("afplay"),
        "say": shutil.which("say"),
        "mpv": shutil.which("mpv"),
        "launchctl": shutil.which("launchctl"),
    }
    return {
        "commands": commands,
        "required_ready": bool(commands["ffmpeg"] and commands["launchctl"]),
        "playback_ready": bool(commands["ffplay"] or commands["afplay"]),
        "fallback_tts_ready": bool(commands["say"] and commands["ffmpeg"]),
    }


def local_assets(home: Path | None = None) -> dict[str, Any]:
    root = Path.home() if home is None else home
    base = root / ".voicemode" / "services"
    candidates = {
        "whisper_server": base / "whisper" / "build" / "bin" / "whisper-server",
        "whisper_cli": base / "whisper" / "build" / "bin" / "whisper-cli",
        "whisper_model": base / "whisper" / "models" / "ggml-large-v3-turbo.bin",
        "whisper_base_model": base / "whisper" / "models" / "ggml-base.bin",
        "kokoro_python": base / "kokoro" / ".venv" / "bin" / "python",
        "kokoro_app": base / "kokoro" / "api" / "src" / "main.py",
    }
    return {
        key: {
            "path": str(path),
            "exists": path.exists(),
            "size_bytes": path.stat().st_size if path.is_file() else None,
        }
        for key, path in candidates.items()
    }


def system_status() -> dict[str, Any]:
    return {
        "vox_version": __version__,
        "python": sys.version.split()[0],
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "pid": os.getpid(),
        "local_only": True,
        "api_keys_used": False,
    }


def static_diagnostics(home: Path | None = None) -> dict[str, Any]:
    return {
        "system": system_status(),
        "dependencies": dependency_status(),
        "audio": audio_devices(),
        "assets": local_assets(home),
    }

