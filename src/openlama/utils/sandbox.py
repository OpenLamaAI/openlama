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
    # Use os.sep suffix to prevent prefix collision (e.g., /home/user vs /home/username)
    return any(
        resolved == a or str(resolved).startswith(str(a) + os.sep)
        for a in allowed
    )
