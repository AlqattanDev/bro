from pathlib import Path

import pytest

from voxmcp.compat import LegacyCompatibility
from voxmcp.errors import VoxError


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["../../escape", "/tmp/escape", "Two Words", "a/b"])
async def test_clone_names_cannot_escape_the_private_voice_directory(
    tmp_path: Path,
    name: str,
) -> None:
    compatibility = LegacyCompatibility(
        tts_base_url="http://127.0.0.1:8880/v1",
        stt_base_url="http://127.0.0.1:2022/v1",
        base_dir=tmp_path,
    )

    with pytest.raises(VoxError, match="Clone names"):
        await compatibility.clone("add", name=name, audio=tmp_path / "clip.wav")
