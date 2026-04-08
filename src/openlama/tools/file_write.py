"""Tool: file_write – write content to a file on the server."""

from pathlib import Path

from openlama.config import get_config, get_config_bool
from openlama.tools.registry import register_tool


def _is_safe_path(path: str) -> bool:
    if not get_config_bool("tool_sandbox_enabled", True):
        return True
    resolved = Path(path).resolve()
    sandbox = get_config("tool_sandbox_path")
    allowed = [Path(sandbox).resolve(), Path.home().resolve()]
    return any(str(resolved).startswith(str(a)) for a in allowed)


async def _execute(args: dict) -> str:
    path = args.get("path", "").strip()
    content = args.get("content", "")
    mode = args.get("mode", "write")

    if not path:
        return "Please provide a file path."
    if not _is_safe_path(path):
        return f"Access denied for path: {path}"

    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        if mode == "append":
            with open(p, "a", encoding="utf-8") as f:
                f.write(content)
        else:
            p.write_text(content, encoding="utf-8")

        return f"File saved: {path} ({len(content)} chars)"
    except Exception as e:
        return f"File write error: {e}"


register_tool(
    name="file_write",
    description="Write content to a local file on the server. Can create new files or overwrite/append to existing ones.",
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path of the file",
            },
            "content": {
                "type": "string",
                "description": "Content to write",
            },
            "mode": {
                "type": "string",
                "description": "Write mode: 'write' (overwrite) or 'append'",
                "enum": ["write", "append"],
                "default": "write",
            },
        },
        "required": ["path", "content"],
    },
    execute=_execute,
    admin_only=True,
)
