"""Format converters for transcription output."""

import csv
import io
from typing import Dict, Any, List

from .types import TranscriptionResult, OutputFormat


def format_timestamp_srt(seconds: float) -> str:
    """Format timestamp for SRT (HH:MM:SS,mmm)"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}".replace(".", ",")


def format_timestamp_vtt(seconds: float) -> str:
    """Format timestamp for WebVTT (HH:MM:SS.mmm)"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


def convert_to_srt(transcription: Dict[str, Any]) -> str:
    """
    Convert transcription to SRT subtitle format.
    """
    srt_lines = []
    
    for i, segment in enumerate(transcription.get("segments", []), 1):
        start = format_timestamp_srt(segment.get("start", 0))
        end = format_timestamp_srt(segment.get("end", 0))
        text = segment.get("text", "").strip()
        
        # Add speaker if available
        if "speaker" in segment:
            text = f"[{segment['speaker']}] {text}"
        
        srt_lines.append(str(i))
        srt_lines.append(f"{start} --> {end}")
        srt_lines.append(text)
        srt_lines.append("")
    
    return "\n".join(srt_lines)


def convert_to_vtt(transcription: Dict[str, Any]) -> str:
    """
    Convert transcription to WebVTT format.
    """
    vtt_lines = ["WEBVTT", ""]
    
    for segment in transcription.get("segments", []):
        start = format_timestamp_vtt(segment.get("start", 0))
        end = format_timestamp_vtt(segment.get("end", 0))
        text = segment.get("text", "").strip()
        
        # Add speaker if available
        if "speaker" in segment:
            text = f"<v {segment['speaker']}>{text}"
        
        vtt_lines.append(f"{start} --> {end}")
        vtt_lines.append(text)
        vtt_lines.append("")
    
    return "\n".join(vtt_lines)


def convert_to_csv(transcription: Dict[str, Any]) -> str:
    """
    Convert transcription to CSV format with word-level data.
    """
    output = io.StringIO()
    
    # Determine columns based on available data
    has_words = "words" in transcription and transcription["words"]
    has_speakers = any("speaker" in w for w in transcription.get("words", []))
    has_probability = any("probability" in w for w in transcription.get("words", []))
    
    # Write header
    if has_words:
        headers = ["word", "start", "end"]
        if has_speakers:
            headers.append("speaker")
        if has_probability:
            headers.append("probability")
    else:
        headers = ["text", "start", "end"]
        if has_speakers:
            headers.append("speaker")
    
    writer = csv.DictWriter(output, fieldnames=headers)
    writer.writeheader()
    
    # Write data
    if has_words:
        for word in transcription.get("words", []):
            row = {
                "word": word.get("word", ""),
                "start": word.get("start", 0),
                "end": word.get("end", 0)
            }
            if has_speakers:
                row["speaker"] = word.get("speaker", "")
            if has_probability:
                row["probability"] = word.get("probability", "")
            writer.writerow(row)
    else:
        for segment in transcription.get("segments", []):
            row = {
                "text": segment.get("text", "").strip(),
                "start": segment.get("start", 0),
                "end": segment.get("end", 0)
            }
            if has_speakers:
                row["speaker"] = segment.get("speaker", "")
            writer.writerow(row)
    
    return output.getvalue()


def convert_to_format(transcription: TranscriptionResult, format: OutputFormat) -> str:
    """
    Convert transcription to specified format.
    
    Args:
        transcription: The transcription result
        format: Target output format
        
    Returns:
        Formatted string representation
    """
    if format == OutputFormat.SRT:
        return convert_to_srt(transcription)
    elif format == OutputFormat.VTT:
        return convert_to_vtt(transcription)
    elif format == OutputFormat.CSV:
        return convert_to_csv(transcription)
    else:
        # Default to JSON (handled elsewhere)
        import json
        return json.dumps(transcription, indent=2)