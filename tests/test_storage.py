from pathlib import Path

from voxmcp.storage import AudioStore


def test_audio_store_bounds_replay_and_keeps_latest(tmp_path: Path):
    store = AudioStore(tmp_path, replay_items=2)
    for i in range(3):
        source = store.new_work_path("tts")
        source.write_bytes(b"RIFF" + bytes([i]) * 64)
        store.commit_tts(source)
    assert store.status()["replay_items"] == 2
    assert store.latest_tts.is_file()
    assert store.replay(0) is not None
    assert store.replay(2) is None


def test_stt_commit_overwrites_instead_of_archiving(tmp_path: Path):
    store = AudioStore(tmp_path)
    first = store.new_work_path("stt")
    first.write_bytes(b"first")
    store.commit_stt(first)
    second = store.new_work_path("stt")
    second.write_bytes(b"second")
    store.commit_stt(second)
    assert store.latest_stt.read_bytes() == b"second"
    assert not list(store.work_dir.iterdir())
