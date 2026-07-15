import json
from pathlib import Path

import httpx
import pytest

from voxmcp.errors import VoxError
from voxmcp.speech import LocalSpeechClient, api_url


def test_api_url_avoids_duplicate_v1():
    assert (
        api_url("http://127.0.0.1:8880/v1", "/v1/audio/speech")
        == "http://127.0.0.1:8880/v1/audio/speech"
    )
    assert (
        api_url("http://127.0.0.1:8880/v1", "audio/speech")
        == "http://127.0.0.1:8880/v1/audio/speech"
    )


@pytest.mark.asyncio
async def test_synthesize_rejects_empty_message(tmp_path: Path):
    client = LocalSpeechClient(
        tts_base_url="http://127.0.0.1:8880/v1",
        stt_base_url="http://127.0.0.1:2022/v1",
    )
    with pytest.raises(VoxError, match="empty"):
        await client.synthesize("  ", tmp_path / "out.wav")


@pytest.mark.asyncio
async def test_transcribe_rejects_missing_file(tmp_path: Path):
    client = LocalSpeechClient(
        tts_base_url="http://127.0.0.1:8880/v1",
        stt_base_url="http://127.0.0.1:2022/v1",
    )
    with pytest.raises(VoxError, match="does not exist"):
        await client.transcribe(tmp_path / "missing.wav")


@pytest.mark.asyncio
async def test_clone_profile_routes_only_to_local_mlx_with_reference_fields(tmp_path: Path):
    voices = tmp_path / "voices"
    voices.mkdir()
    audio = voices / "river.wav"
    audio.write_bytes(b"RIFF" + b"0" * 64)
    profiles = tmp_path / "voices.json"
    profiles.write_text(
        json.dumps(
            {
                "voices": {
                    "river": {
                        "ref_audio": "river.wav",
                        "ref_text": "reference words",
                        "base_url": "http://127.0.0.1:8890/v1",
                        "model": "local-clone-model",
                    }
                }
            }
        )
    )
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["payload"] = json.loads(request.content)
        return httpx.Response(200, content=b"RIFF" + b"1" * 64)

    client = LocalSpeechClient(
        tts_base_url="http://127.0.0.1:8880/v1",
        stt_base_url="http://127.0.0.1:2022/v1",
        clone_profiles_path=profiles,
        clone_voices_dir=voices,
        client_factory=lambda **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(handler), **kwargs
        ),
    )
    result = await client.synthesize("hello", tmp_path / "out.wav", voice="river")

    assert result.backend == "mlx-audio"
    assert seen["url"] == "http://127.0.0.1:8890/v1/audio/speech"
    assert seen["payload"]["ref_audio"] == str(audio.resolve())
    assert seen["payload"]["ref_text"] == "reference words"


@pytest.mark.asyncio
async def test_clone_profile_rejects_non_loopback_endpoint(tmp_path: Path):
    voices = tmp_path / "voices"
    voices.mkdir()
    audio = voices / "river.wav"
    audio.write_bytes(b"RIFF" + b"0" * 64)
    profiles = tmp_path / "voices.json"
    profiles.write_text(
        json.dumps(
            {
                "voices": {
                    "river": {
                        "ref_audio": "river.wav",
                        "ref_text": "reference words",
                        "base_url": "https://paid.example/v1",
                    }
                }
            }
        )
    )
    client = LocalSpeechClient(
        tts_base_url="http://127.0.0.1:8880/v1",
        stt_base_url="http://127.0.0.1:2022/v1",
        clone_profiles_path=profiles,
        clone_voices_dir=voices,
    )

    with pytest.raises(VoxError, match="literal loopback|local-only"):
        await client.synthesize("hello", tmp_path / "out.wav", voice="river")
