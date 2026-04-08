"""Tool: file_read – read a file from the server filesystem."""

from pathlib import Path

from openlama.config import get_config, get_config_int, get_config_bool
from openlama.tools.registry import register_tool


def _is_safe_path(path: str) -> bool:
    """Check if path is under allowed directories."""
    if not get_config_bool("tool_sandbox_enabled", True):
        return True
    resolved = Path(path).resolve()
    sandbox = get_config("tool_sandbox_path")
    allowed = [Path(sandbox).resolve(), Path.home().resolve()]
    return any(str(resolved).startswith(str(a)) for a in allowed)


async def _execute(args: dict) -> str:
    path = args.get("path", "").strip()
    if not path:
        return "Please provide a file path."

    if not _is_safe_path(path):
        return f"Access denied for path: {path}"

    p = Path(path)
    if not p.exists():
        return f"File not found: {path}"
    if p.is_dir():
        items = sorted(p.iterdir())
        listing = "\n".join(
            f"{'[DIR] ' if i.is_dir() else ''}{i.name}" for i in items[:100]
        )
        return f"Directory: {path}\n\n{listing}"

    try:
        max_chars = get_config_int("max_file_read_chars", 50000)
        content = p.read_text(encoding="utf-8", errors="replace")
        if len(content) > max_chars:
            content = content[:max_chars] + f"\n... (truncated, total {p.stat().st_size} bytes)"
        return f"File: {path}\nSize: {p.stat().st_size} bytes\n\n{content}"
    except Exception as e:
        return f"File read error: {e}"


register_tool(
    name="file_read",
    description="Read a local file or list directory contents on the server.",
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path of the file or directory to read",
            },
        },
        "required": ["path"],
    },
    execute=_execute,
    admin_only=True,
)
