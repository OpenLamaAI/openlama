"""Shared sandbox path validation for file tools."""
import os
from pathlib import Path

from openlama.config import get_config, get_config_bool


def is_safe_path(path: str) -> bool:
    """Check if a path is within the allowed sandbox directories."""
    if not get_config_bool("tool_sandbox_enabled", True):
        return True
    resolved = Path(path).resolve()
    sandbox = get_config("tool_sandbox_path")
    allowed = [Path(sandbox).resolve(), Path.home().resolve()]
    for a in allowed:
        # Use is_relative_to (Python 3.9+) or check with path separator
        try:
            resolved.relative_to(a)
            return True
        except ValueError:
            continue
    return False
