"""
Sound Fonts Audio Player

A lightweight audio player for Sound Fonts that can play audio file slices
with specified start and end points. Supports WAV and MP3 files.
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional


class AudioPlayer:
    def __init__(self, voicemode_home: str = None):
        self.voicemode_home = Path(voicemode_home or os.path.expanduser("~/.voicemode"))
        
    def play_audio_slice(self, file_path: str, start: float = 0.0, end: Optional[float] = None, volume: float = 1.0):
        """
        Play a slice of an audio file using ffmpeg/ffplay
        
        Args:
            file_path: Path to audio file
            start: Start time in seconds
            end: End time in seconds (None for end of file)
            volume: Volume multiplier (0.0 to 1.0)
        """
        if not os.path.exists(file_path):
            print(f"Error: Audio file not found: {file_path}", file=sys.stderr)
            return False
            
        # Build ffplay command for non-blocking audio playback
        cmd = [
            "ffplay",
            "-nodisp",  # No video display
            "-autoexit",  # Exit when playback ends
            "-loglevel", "quiet",  # Suppress output
            "-ss", str(start),  # Start time
        ]
        
        if end is not None:
            duration = end - start
            cmd.extend(["-t", str(duration)])  # Duration to play
            
        if volume != 1.0:
            cmd.extend(["-af", f"volume={volume}"])  # Volume filter
            
        cmd.append(file_path)
        
        try:
            # Run in background (non-blocking)
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception as e:
            print(f"Error playing audio: {e}", file=sys.stderr)
            return False
            
    def load_sound_font(self, font_name: str = None) -> Optional[Dict[str, Any]]:
        """Load Sound Font configuration"""
        if font_name:
            config_path = self.voicemode_home / "sound-fonts" / font_name / "config.json"
        else:
            # Try to find active sound font from settings
            settings_path = self.voicemode_home / "settings.json"
            if settings_path.exists():
                try:
                    with open(settings_path) as f:
                        settings = json.load(f)
                    font_name = settings.get("sound_font")
                    if font_name:
                        config_path = self.voicemode_home / "sound-fonts" / font_name / "config.json"
                    else:
                        return None
                except:
                    return None
            else:
                return None
                
        if not config_path.exists():
            return None
            
        try:
            with open(config_path) as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading sound font config: {e}", file=sys.stderr)
            return None
            
    def resolve_audio_path(self, config: Dict[str, Any], file_name: str) -> str:
        """Resolve audio file path relative to sound font directory"""
        font_dir = Path(config.get("base_path", self.voicemode_home / "sound-fonts" / config["name"]))
        return str(font_dir / file_name)
        
    def play_sound_for_event(self, tool_name: str, action: str, subagent_type: str = None, metadata: Dict[str, Any] = None):
        """
        Play sound for a specific tool event based on Sound Font configuration
        
        Args:
            tool_name: Name of the tool (e.g., "Task", "Bash", "Read")
            action: Event action ("start" or "end")
            subagent_type: For Task tool, the subagent (e.g., "mama-bear")
            metadata: Additional event metadata
        """
        config = self.load_sound_font()
        if not config:
            return False
            
        sounds = config.get("sounds", {})
        
        # Look up sound configuration
        tool_config = sounds.get(tool_name)
        if not tool_config:
            tool_config = sounds.get("default", {})
            if not tool_config:
                return False
                
        # Handle subagent_type for Task tool
        if subagent_type and "subagent_type" in tool_config:
            subagent_config = tool_config["subagent_type"].get(subagent_type)
            if subagent_config:
                sound_config = subagent_config.get(action)
            else:
                sound_config = tool_config.get("default", {}).get(action)
        else:
            # For Task tool without subagent_type, use default sounds
            if tool_name == "Task" and "default" in tool_config:
                sound_config = tool_config["default"].get(action)
            else:
                sound_config = tool_config.get(action)
            
        if not sound_config:
            return False
            
        # Extract sound parameters
        file_name = sound_config.get("file")
        if not file_name:
            return False
            
        file_path = self.resolve_audio_path(config, file_name)
        start = sound_config.get("start", 0.0)
        end = sound_config.get("end")
        volume = sound_config.get("volume", 1.0)
        
        # Log the event
        self.log_sound_event(tool_name, action, subagent_type, sound_config)
        
        return self.play_audio_slice(file_path, start, end, volume)
        
    def log_sound_event(self, tool_name: str, action: str, subagent_type: str = None, sound_config: Dict[str, Any] = None):
        """Log sound events in VoiceMode format"""
        import time
        
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        
        log_entry = {
            "timestamp": timestamp,
            "event": "sound_fonts_play",
            "tool_name": tool_name,
            "action": action,
            "subagent_type": subagent_type,
            "file": sound_config.get("file") if sound_config else None,
            "start": sound_config.get("start") if sound_config else None,
            "end": sound_config.get("end") if sound_config else None,
            "volume": sound_config.get("volume") if sound_config else None
        }
        
        # Write to VoiceMode logs directory
        log_file = self.voicemode_home / "logs" / "sound-fonts.log"
        log_file.parent.mkdir(exist_ok=True)
        
        with open(log_file, "a") as f:
            f.write(json.dumps(log_entry) + "\n")
            
        # Also print to stderr for debugging
        print(f"[SoundFonts] {timestamp} - Playing {action} sound for {tool_name}" + 
              (f" ({subagent_type})" if subagent_type else "") + 
              f": {sound_config.get('file')}[{sound_config.get('start')}-{sound_config.get('end')}]" if sound_config else "",
              file=sys.stderr)