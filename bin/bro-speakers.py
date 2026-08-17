#!/usr/bin/env python3
"""Cheap whole-clip speaker ID for two enrolled voices."""
from __future__ import annotations

import json
import os
import sys
import wave
from pathlib import Path

import numpy as np
from numpy.fft import rfft, rfftfreq

BRO_HOME = Path(os.environ.get("BRO_HOME", Path.home() / ".bro"))
SPEAKERS = BRO_HOME / "speakers"
VOICES = SPEAKERS / "voices"
ECAPA_VOICES = SPEAKERS / "ecapa"
ECAPA_ONNX = SPEAKERS / "model" / "ecapa.onnx"
ENABLED = SPEAKERS / "enabled"
DEFAULT_WAV = Path.home() / ".vox" / "audio" / "latest" / "stt.wav"
MIN_SCORE = 0.08
ECAPA_MIN_SCORE = 0.25
ECAPA_MARGIN = 0.05


def usage() -> None:
    print(
        "usage: bro-speakers on|off|status\n"
        "       bro-speakers enroll NAME [wav]\n"
        "       bro-speakers who [wav]\n"
        "       bro-speakers list",
        file=sys.stderr,
    )


def load_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as handle:
        sr = handle.getframerate()
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        raw = handle.readframes(handle.getnframes())
    if width == 2:
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif width == 4:
        audio = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        raise SystemExit(f"unsupported sample width: {width}")
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    return audio, sr


def _has_ecapa() -> bool:
    return ECAPA_ONNX.is_file()


def _resample_16k(audio: np.ndarray, sr: int) -> np.ndarray:
    if sr == 16000:
        return audio
    if sr <= 0:
        raise SystemExit("bad sample rate")
    n_out = int(round(audio.size * 16000 / sr))
    if n_out < 16:
        raise SystemExit("clip too short to enroll or identify")
    old_idx = np.linspace(0.0, 1.0, audio.size, dtype=np.float32)
    new_idx = np.linspace(0.0, 1.0, n_out, dtype=np.float32)
    return np.interp(new_idx, old_idx, audio).astype(np.float32)


def _fbank80(audio: np.ndarray, sr: int) -> np.ndarray:
    audio = _resample_16k(audio, sr)
    sr = 16000
    # pre-emphasis
    audio = np.append(audio[0], audio[1:] - 0.97 * audio[:-1]).astype(np.float32)
    frame = int(0.025 * sr)
    hop = int(0.010 * sr)
    n_fft = 512
    if audio.size < frame:
        raise SystemExit("clip too short to enroll or identify")
    n_frames = 1 + (audio.size - frame) // hop
    window = np.hamming(frame).astype(np.float32)
    frames = np.lib.stride_tricks.as_strided(
        audio,
        shape=(n_frames, frame),
        strides=(audio.strides[0] * hop, audio.strides[0]),
        writeable=False,
    ).copy() * window
    spec = np.abs(rfft(frames, n=n_fft)) ** 2
    freqs = rfftfreq(n_fft, d=1.0 / sr)
    n_mels = 80
    low, high = 20.0, min(8000.0, sr / 2.0)
    mel_pts = np.linspace(_hz_to_mel(low), _hz_to_mel(high), n_mels + 2)
    hz_pts = _mel_to_hz(mel_pts)
    bins = np.floor((n_fft + 1) * hz_pts / sr).astype(int)
    filters = np.zeros((n_mels, spec.shape[1]), dtype=np.float32)
    for i in range(n_mels):
        left, center, right = bins[i], bins[i + 1], bins[i + 2]
        if right <= left:
            continue
        for b in range(left, center):
            if 0 <= b < filters.shape[1] and center != left:
                filters[i, b] = (b - left) / (center - left)
        for b in range(center, right):
            if 0 <= b < filters.shape[1] and right != center:
                filters[i, b] = (right - b) / (right - center)
    mel = np.log(np.maximum(spec @ filters.T, 1e-10)).astype(np.float32)
    # Wespeaker inference uses cepstral mean norm.
    mel = mel - mel.mean(axis=0, keepdims=True)
    return mel


_ECAPA_SESS = None


def embed_ecapa(path: Path) -> np.ndarray:
    global _ECAPA_SESS
    import onnxruntime as ort

    if _ECAPA_SESS is None:
        _ECAPA_SESS = ort.InferenceSession(str(ECAPA_ONNX), providers=["CPUExecutionProvider"])
    audio, sr = load_wav(path)
    feats = _fbank80(audio, sr)
    if feats.shape[0] < 20:
        raise SystemExit("clip too short to enroll or identify")
    name = _ECAPA_SESS.get_inputs()[0].name
    out = _ECAPA_SESS.run(None, {name: feats[np.newaxis, :, :]})[0]
    vec = np.asarray(out[0], dtype=np.float32)
    n = float(np.linalg.norm(vec))
    return vec / n if n > 0 else vec


def _hz_to_mel(hz: np.ndarray | float) -> np.ndarray | float:
    return 2595.0 * np.log10(1.0 + np.asarray(hz) / 700.0)


def _mel_to_hz(mel: np.ndarray | float) -> np.ndarray | float:
    return 700.0 * (10.0 ** (np.asarray(mel) / 2595.0) - 1.0)


def embed_cheap(path: Path) -> np.ndarray:
    audio, sr = load_wav(path)
    if audio.size < sr * 0.2:
        raise SystemExit("clip too short to enroll or identify")
    audio = audio - float(audio.mean())
    frame = int(0.025 * sr)
    hop = int(0.010 * sr)
    window = np.hanning(frame).astype(np.float32)
    if audio.size < frame:
        raise SystemExit("clip too short to enroll or identify")
    n_frames = 1 + (audio.size - frame) // hop
    frames = np.lib.stride_tricks.as_strided(
        audio,
        shape=(n_frames, frame),
        strides=(audio.strides[0] * hop, audio.strides[0]),
        writeable=False,
    ).copy()
    energy = np.sqrt((frames * frames).mean(axis=1) + 1e-12)
    keep = energy > max(float(np.median(energy)) * 0.4, 0.005)
    if not np.any(keep):
        keep = energy > 0
    frames = frames[keep] * window
    spec = np.abs(rfft(frames, n=512)) + 1e-10
    freqs = rfftfreq(512, d=1.0 / sr)
    n_mels = 26
    mel_pts = np.linspace(_hz_to_mel(0.0), _hz_to_mel(min(sr / 2.0, 8000.0)), n_mels + 2)
    hz_pts = _mel_to_hz(mel_pts)
    bins = np.floor((512 + 1) * hz_pts / sr).astype(int)
    filters = np.zeros((n_mels, spec.shape[1]), dtype=np.float32)
    for i in range(n_mels):
        left, center, right = bins[i], bins[i + 1], bins[i + 2]
        if right <= left:
            continue
        for b in range(left, center):
            if 0 <= b < filters.shape[1] and center != left:
                filters[i, b] = (b - left) / (center - left)
        for b in range(center, right):
            if 0 <= b < filters.shape[1] and right != center:
                filters[i, b] = (right - b) / (right - center)
    mel = np.log(spec @ filters.T + 1e-10)
    centroid = (spec * freqs).sum(axis=1) / spec.sum(axis=1)
    # Pitch via frame autocorrelation peak in 70–350 Hz.
    pitches = []
    min_lag = max(1, int(sr / 350))
    max_lag = min(frame - 1, int(sr / 70))
    for frame_i in frames[::3]:
        centered = frame_i - frame_i.mean()
        corr = np.correlate(centered, centered, mode="full")[frame - 1 :]
        if max_lag <= min_lag or corr[0] <= 0:
            continue
        peak = min_lag + int(np.argmax(corr[min_lag:max_lag]))
        if corr[peak] / corr[0] > 0.3:
            pitches.append(sr / peak)
    pitch = np.array(pitches, dtype=np.float32)
    if pitch.size == 0:
        # FFT peak fallback for clean tones.
        mag = spec.mean(axis=0)
        band = (freqs >= 70) & (freqs <= 350)
        if np.any(band):
            f0 = float(freqs[band][int(np.argmax(mag[band]))])
            pitch = np.array([f0], dtype=np.float32)
    if pitch.size == 0:
        pitch_stats = np.array([0.0, 0.0], dtype=np.float32)
    else:
        pitch_stats = np.array([float(pitch.mean()), float(pitch.std())], dtype=np.float32)
    def _unit(v: np.ndarray) -> np.ndarray:
        n = float(np.linalg.norm(v))
        return v / n if n > 0 else v

    # Pitch is the cheap 2-person split (you vs her). Don't let a long
    # mel vector drown it after one global L2.
    timbre = _unit(
        np.concatenate(
            [
                mel.mean(axis=0),
                mel.std(axis=0),
                np.array([float(centroid.mean()), float(centroid.std())], dtype=np.float32),
            ]
        )
    )
    # Keep F0 as a magnitude, not a 2-d unit vector (that collapses to
    # [1, 0] whenever pitch is steady, wiping the actual frequency).
    pitch_feat = np.array(
        [
            float(pitch_stats[0] / 300.0),
            float(min(pitch_stats[1] / 40.0, 1.0)),
        ],
        dtype=np.float32,
    )
    vec = _unit(np.concatenate([0.35 * timbre, pitch_feat]))
    return vec.astype(np.float32)


def embed(path: Path) -> np.ndarray:
    if _has_ecapa():
        try:
            return embed_ecapa(path)
        except ImportError:
            pass
    return embed_cheap(path)


def voice_dir() -> Path:
    return ECAPA_VOICES if _has_ecapa() else VOICES


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def enabled() -> bool:
    return ENABLED.is_file() and ENABLED.read_text().strip() == "on"


def set_enabled(value: bool) -> None:
    SPEAKERS.mkdir(parents=True, exist_ok=True)
    ENABLED.write_text("on\n" if value else "off\n")


def voice_paths() -> list[Path]:
    folder = voice_dir()
    if not folder.is_dir():
        return []
    return sorted(folder.glob("*.npy"))


def cmd_status() -> int:
    names = [p.stem for p in voice_paths()]
    print(f"speakers={'on' if enabled() else 'off'}")
    print(f"backend={'ecapa' if _has_ecapa() else 'cheap'}")
    print("voices=" + (",".join(names) if names else "(none)"))
    return 0


def cmd_enroll(name: str, wav: Path) -> int:
    if not wav.is_file():
        print(f"no wav: {wav}", file=sys.stderr)
        return 1
    clean = "".join(ch for ch in name.lower() if ch.isalnum() or ch in "-_")
    if not clean:
        print("bad name", file=sys.stderr)
        return 2
    folder = voice_dir()
    folder.mkdir(parents=True, exist_ok=True)
    vec = embed(wav)
    np.save(folder / f"{clean}.npy", vec)
    print(f"enrolled {clean} from {wav} ({'ecapa' if _has_ecapa() else 'cheap'})")
    return 0


def _label(probe: np.ndarray, catalog: list[tuple[str, np.ndarray]]) -> str:
    scored = [(cosine(probe, vec), name) for name, vec in catalog]
    scored.sort(reverse=True)
    best, name = scored[0]
    second = scored[1][0] if len(scored) > 1 else -1.0
    min_score = ECAPA_MIN_SCORE if _has_ecapa() else MIN_SCORE
    margin = ECAPA_MARGIN if _has_ecapa() else 0.015
    if best < min_score or (len(scored) > 1 and best - second < margin):
        return "unknown"
    return name


def _write_wav(path: Path, audio: np.ndarray, sr: int) -> None:
    clipped = np.clip(audio, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sr)
        handle.writeframes(pcm.tobytes())


def _timeline(wav: Path, catalog: list[tuple[str, np.ndarray]]) -> list[tuple[float, float, str]]:
    audio, sr = load_wav(wav)
    win = int(1.6 * sr)
    hop = int(0.8 * sr)
    if audio.size < win:
        return []
    import tempfile

    parts: list[tuple[float, float, str]] = []
    with tempfile.TemporaryDirectory() as tmp:
        start = 0
        idx = 0
        while start + win <= audio.size:
            chunk = audio[start : start + win]
            piece = Path(tmp) / f"w{idx}.wav"
            _write_wav(piece, chunk, sr)
            label = _label(embed(piece), catalog)
            t0 = start / sr
            t1 = (start + win) / sr
            if parts and parts[-1][2] == label:
                parts[-1] = (parts[-1][0], t1, label)
            else:
                parts.append((t0, t1, label))
            start += hop
            idx += 1
    return parts


def cmd_who(wav: Path) -> int:
    if not enabled():
        print("off")
        return 0
    if not wav.is_file():
        print("unknown")
        return 1
    voices = voice_paths()
    if not voices:
        print("unknown")
        return 1
    catalog = [(path.stem, np.load(path)) for path in voices]
    name = _label(embed(wav), catalog)
    print(name)
    parts = _timeline(wav, catalog)
    if parts:
        bits = [f"{label}:{a:.1f}-{b:.1f}" for a, b, label in parts]
        print("timeline=" + ",".join(bits))
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        usage()
        return 2
    cmd = argv[0]
    if cmd == "on":
        set_enabled(True)
        print("speakers on")
        return 0
    if cmd == "off":
        set_enabled(False)
        print("speakers off")
        return 0
    if cmd == "status":
        return cmd_status()
    if cmd == "list":
        return cmd_status()
    if cmd == "enroll":
        if len(argv) < 2:
            usage()
            return 2
        wav = Path(argv[2]) if len(argv) > 2 else DEFAULT_WAV
        return cmd_enroll(argv[1], wav)
    if cmd == "who":
        wav = Path(argv[1]) if len(argv) > 1 else DEFAULT_WAV
        return cmd_who(wav)
    usage()
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
