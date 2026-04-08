"""Tool: file_write – write content to a file on the server."""

from pathlib import Path

from openlama.tools.registry import register_tool
from openlama.utils.sandbox import is_safe_path


async def _execute(args: dict) -> str:
    path = args.get("path", "").strip()
    content = args.get("content", "")
    mode = args.get("mode", "write")

    if not path:
        return "Please provide a file path."
    if not is_safe_path(path):
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
