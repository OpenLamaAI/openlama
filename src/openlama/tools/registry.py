"""Tool registry – register, lookup, execute tools for Ollama tool calling."""

from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable, Optional

from openlama.database import log_tool_call

ToolFn = Callable[[dict], Awaitable[str]]


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict  # JSON Schema
    execute: ToolFn
    admin_only: bool = False


_TOOLS: dict[str, Tool] = {}


def register_tool(
    name: str,
    description: str,
    parameters: dict,
    execute: ToolFn,
    admin_only: bool = False,
):
    _TOOLS[name] = Tool(
        name=name,
        description=description,
        parameters=parameters,
        execute=execute,
        admin_only=admin_only,
    )


def get_tool(name: str) -> Optional[Tool]:
    return _TOOLS.get(name)


def get_all_tools() -> list[Tool]:
    return list(_TOOLS.values())


def format_tools_for_ollama(admin: bool = True) -> list[dict]:
    """Convert registered tools to Ollama's tools parameter format."""
    tools = []
    for t in _TOOLS.values():
        if t.admin_only and not admin:
            continue
        tools.append({
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        })
    return tools


async def execute_tool(name: str, arguments: dict, user_id: int) -> str:
    """Execute a tool by name, log the call, return result string."""
    tool = _TOOLS.get(name)
    if not tool:
        return f"Tool not found: {name}"
    try:
        result = await tool.execute(arguments)
        log_tool_call(user_id, name, arguments, result, success=True)
        return result
    except Exception as e:
        error_msg = f"Tool execution error ({name}): {str(e)[:500]}"
        log_tool_call(user_id, name, arguments, error_msg, success=False)
        return error_msg
