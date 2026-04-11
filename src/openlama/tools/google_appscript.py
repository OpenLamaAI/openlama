"""Google Apps Script tool — manage and execute scripts."""

from __future__ import annotations

import asyncio
import json

from openlama.tools.registry import register_tool
from openlama.tools.google_auth import build_service


def _svc():
    return build_service("script", "v1")


async def _get(args: dict) -> str:
    script_id = args.get("script_id", "")

    def _run():
        project = _svc().projects().get(scriptId=script_id).execute()
        return (
            f"Script: {project.get('title', '')}\n"
            f"ID: {project.get('scriptId', '')}\n"
            f"Parent: {project.get('parentId', '')}\n"
            f"Created: {project.get('createTime', '')}\n"
            f"Updated: {project.get('updateTime', '')}"
        )
    return await asyncio.to_thread(_run)


async def _content(args: dict) -> str:
    script_id = args.get("script_id", "")

    def _run():
        content = _svc().projects().getContent(scriptId=script_id).execute()
        files = content.get("files", [])
        lines = [f"Files ({len(files)}):"]
        for f in files:
            lines.append(f"\n--- {f.get('name', '?')}.{f.get('type', '?').lower()} ---")
            source = f.get("source", "")
            if len(source) > 2000:
                source = source[:2000] + "\n... (truncated)"
            lines.append(source)
        return "\n".join(lines)
    return await asyncio.to_thread(_run)


async def _create(args: dict) -> str:
    title = args.get("title", "Untitled Script")
    parent_id = args.get("parent_id", "")

    def _run():
        body = {"title": title}
        if parent_id:
            body["parentId"] = parent_id
        project = _svc().projects().create(body=body).execute()
        return f"Script created: {title}\nID: {project.get('scriptId', '')}"
    return await asyncio.to_thread(_run)


async def _run(args: dict) -> str:
    script_id = args.get("script_id", "")
    function = args.get("function", "")
    params = args.get("params", [])

    def _run_fn():
        body = {"function": function}
        if params:
            body["parameters"] = params
        result = _svc().scripts().run(scriptId=script_id, body=body).execute()
        if result.get("error"):
            details = result["error"].get("details", [{}])
            msg = details[0].get("errorMessage", str(result["error"])) if details else str(result["error"])
            return f"Script error: {msg}"
        return_value = result.get("response", {}).get("result", "")
        return f"Result: {json.dumps(return_value, indent=2) if return_value else '(no return value)'}"
    return await asyncio.to_thread(_run_fn)


_ACTIONS = {
    "get": _get,
    "content": _content,
    "create": _create,
    "run": _run,
}


async def _execute(args: dict) -> str:
    action = args.get("action", "")
    fn = _ACTIONS.get(action)
    if not fn:
        return f"Unknown action: {action}. Available: {', '.join(sorted(_ACTIONS))}"
    return await fn(args)


register_tool(
    name="google_appscript",
    description=(
        "Google Apps Script: view script info/content, create scripts, execute functions. "
        "Requires Google authentication."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(_ACTIONS.keys()), "description": "Apps Script action"},
            "script_id": {"type": "string", "description": "Script ID"},
            "title": {"type": "string", "description": "Script title"},
            "parent_id": {"type": "string", "description": "Parent file ID (Drive file to bind to)"},
            "function": {"type": "string", "description": "Function name to execute"},
            "params": {"type": "array", "description": "Function parameters"},
        },
        "required": ["action"],
    },
    execute=_execute,
)
