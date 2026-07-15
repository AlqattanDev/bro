"""Audio transcription with word-level timestamps."""

from .types import TranscriptionBackend, OutputFormat, TranscriptionResult, WordData, SegmentData
from .core import transcribe_audio, transcribe_audio_sync

__all__ = [
    'transcribe_audio',
    'transcribe_audio_sync',
    'TranscriptionBackend',
    'OutputFormat',
    'TranscriptionResult',
    'WordData',
    'SegmentData',
]