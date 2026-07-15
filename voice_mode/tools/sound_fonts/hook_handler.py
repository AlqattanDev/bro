"""
Hook Handler for Sound Fonts

Handles parsing of Claude Code hook data and extracting relevant information
for sound playback.
"""

import json
import sys
from typing import Dict, Any, Optional


def parse_claude_code_hook(hook_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Parse Claude Code hook data to extract sound-relevant information.
    
    Args:
        hook_data: Raw hook data from Claude Code
        
    Returns:
        Dict with tool_name, action, subagent_type, and metadata
    """
    # Extract tool name
    tool_name = hook_data.get("tool_name")
    if not tool_name:
        return None
    
    # For PreToolUse hooks, action is "start"
    # For PostToolUse hooks, action is "end"
    # We'll assume "start" if not specified
    action = hook_data.get("action", "start")
    
    # Extract subagent_type from tool_input for Task calls
    subagent_type = None
    tool_input = hook_data.get("tool_input", {})
    if isinstance(tool_input, dict):
        subagent_type = tool_input.get("subagent_type")
    
    # Extract any additional metadata
    metadata = {
        "session_id": hook_data.get("session_id"),
        "cwd": hook_data.get("cwd"),
        "timestamp": hook_data.get("timestamp"),
    }
    
    return {
        "tool_name": tool_name,
        "action": action,
        "subagent_type": subagent_type,
        "metadata": metadata
    }


def read_hook_data_from_stdin() -> Optional[Dict[str, Any]]:
    """
    Read hook data from stdin (JSON format).
    
    Returns:
        Parsed hook data or None if error
    """
    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        return None


def parse_hook_arguments(args: list) -> Optional[Dict[str, Any]]:
    """
    Parse hook arguments from command line.
    
    Expected formats:
    - JSON string as single argument
    - Individual arguments: tool_name action [subagent_type] [metadata_json]
    """
    if len(args) == 1:
        # Single JSON argument
        try:
            return json.loads(args[0])
        except json.JSONDecodeError:
            return None
            
    # Individual arguments
    if len(args) < 2:
        return None
        
    hook_data = {
        "tool_name": args[0],
        "action": args[1]
    }
    
    if len(args) > 2:
        hook_data["subagent_type"] = args[2]
        
    if len(args) > 3:
        try:
            hook_data["metadata"] = json.loads(args[3])
        except:
            hook_data["metadata"] = {}
            
    return hook_data


def extract_subagent_from_metadata(metadata: Dict[str, Any]) -> Optional[str]:
    """
    Extract subagent_type from Claude Code hook metadata.
    
    For Task tool calls, the subagent_type might be in various places
    depending on how Claude Code structures the hook data.
    """
    if not metadata:
        return None
        
    # Direct subagent_type field
    if "subagent_type" in metadata:
        return metadata["subagent_type"]
        
    # Look in parameters
    params = metadata.get("parameters", {})
    if "subagent_type" in params:
        return params["subagent_type"]
        
    # Look in tool_args or similar
    tool_args = metadata.get("tool_args", {})
    if "subagent_type" in tool_args:
        return tool_args["subagent_type"]
        
    return None