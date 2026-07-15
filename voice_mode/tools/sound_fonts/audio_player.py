"""
Simple audio player for sound fonts.

Handles audio playback with features like volume control, start/end times,
and potential future support for URLs and looping.
"""

import subprocess
from pathlib import Path
from typing import Optional
import sys


class Player:
    """Simple audio player using ffplay."""
    
    def play(
        self,
        file_path: str,
        start: float = 0.0,
        end: Optional[float] = None,
        volume: float = 1.0
    ) -> bool:
        """
        Play an audio file or slice of it.
        
        Args:
            file_path: Path to audio file (local path, future: URLs)
            start: Start time in seconds
            end: End time in seconds (None for end of file)
            volume: Volume multiplier (0.0 to 1.0)
            
        Returns:
            True if playback started successfully, False otherwise
        """
        # Check if file exists (skip for URLs in future)
        if not file_path.startswith(('http://', 'https://')):
            path = Path(file_path)
            if not path.exists():
                if sys.stderr.isatty():
                    print(f"Error: Audio file not found: {file_path}", file=sys.stderr)
                return False
        
        # Build ffplay command for non-blocking audio playback
        cmd = [
            "ffplay",
            "-nodisp",      # No video display
            "-autoexit",    # Exit when playback ends
            "-loglevel", "quiet",  # Suppress output
        ]
        
        # Add start time if specified
        if start > 0:
            cmd.extend(["-ss", str(start)])
        
        # Add duration if end time specified
        if end is not None:
            duration = end - start
            if duration > 0:
                cmd.extend(["-t", str(duration)])
        
        # Add volume filter if not 1.0
        if volume != 1.0:
            # Clamp volume between 0 and 2 (200%)
            volume = max(0.0, min(2.0, volume))
            cmd.extend(["-af", f"volume={volume}"])
        
        # Add the file path
        cmd.append(file_path)
        
        try:
            # Run in background (non-blocking)
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            return True
        except FileNotFoundError:
            # ffplay not installed
            if sys.stderr.isatty():
                print("Error: ffplay not found. Please install ffmpeg.", file=sys.stderr)
            return False
        except Exception as e:
            if sys.stderr.isatty():
                print(f"Error playing audio: {e}", file=sys.stderr)
            return False