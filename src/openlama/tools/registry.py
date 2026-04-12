"""Tool registry – register, lookup, execute tools for Ollama tool calling."""

from __future__ import annotations

import asyncio
import json
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable, Optional

from openlama.database import log_tool_call
from openlama.logger import get_logger

logger = get_logger("tool.registry")

ToolFn = Callable[[dict], Awaitable[str]]

# Confirmation callback type: async fn(tool_name, args_summary) -> bool
ConfirmFn = Callable[[str, str], Awaitable[bool]]

# Tools that require user confirmation before execution
DANGEROUS_TOOLS = frozenset({
    "shell_command",
    "code_execute",
    "process_manager",
    "file_write",
})


def is_dangerous_tool(name: str) -> bool:
    """Check if a tool requires user confirmation."""
    return name in DANGEROUS_TOOLS


# Network-dependent tools that benefit from retry on transient failures
NETWORK_TOOLS = frozenset({
    "web_search", "url_fetch",
})

_RETRYABLE_ERRORS = (ConnectionError, TimeoutError, OSError)
MAX_TOOL_RETRIES = 2
RETRY_DELAY = 1.0


def _summarize_args(name: str, arguments: dict) -> str:
    """Create a human-readable summary of tool arguments for confirmation."""
    if name == "shell_command":
        return arguments.get("command", "(empty)")
    if name == "code_execute":
        lang = arguments.get("language", "unknown")
        code = arguments.get("code", "")
        if len(code) > 200:
            code = code[:200] + "..."
        return f"[{lang}] {code}"
    if name == "process_manager":
        action = arguments.get("action", "")
        target = arguments.get("target", "")
        signal = arguments.get("signal", "")
        parts = [action]
        if target:
            parts.append(target)
        if signal:
            parts.append(f"(signal={signal})")
        return " ".join(parts)
    if name == "file_write":
        path = arguments.get("path", "")
        mode = arguments.get("mode", "write")
        size = len(arguments.get("content", ""))
        return f"{mode} → {path} ({size} chars)"
    return json.dumps(arguments, ensure_ascii=False)[:300]


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict  # JSON Schema
    execute: ToolFn
    admin_only: bool = False


_TOOLS: dict[str, Tool] = {}
_tools_cache: dict[bool, list[dict]] | None = None


def register_tool(
    name: str,
    description: str,
    parameters: dict,
    execute: ToolFn,
    admin_only: bool = False,
):
    global _tools_cache
    _TOOLS[name] = Tool(
        name=name,
        description=description,
        parameters=parameters,
        execute=execute,
        admin_only=admin_only,
    )
    _tools_cache = None  # invalidate


def get_tool(name: str) -> Optional[Tool]:
    return _TOOLS.get(name)


def get_all_tools() -> list[Tool]:
    return list(_TOOLS.values())


def format_tools_for_ollama(admin: bool = True) -> list[dict]:
    """Convert registered tools to Ollama's tools parameter format. Cached."""
    global _tools_cache
    if _tools_cache is None:
        _tools_cache = {}
    if admin in _tools_cache:
        return _tools_cache[admin]

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
    _tools_cache[admin] = tools
    return tools


def _validate_tool_args(tool: Tool, args: dict) -> tuple[bool, str]:
    """Validate required parameters and basic type checks against tool schema."""
    schema = tool.parameters
    required = schema.get("required", [])

    for param in required:
        if param not in args:
            return False, f"Missing required parameter: {param}"

    properties = schema.get("properties", {})
    for key, value in args.items():
        if key in properties:
            expected_type = properties[key].get("type")
            if expected_type == "string" and not isinstance(value, str):
                return False, f"Parameter '{key}' must be string, got {type(value).__name__}"
            if expected_type == "integer" and not isinstance(value, int):
                return False, f"Parameter '{key}' must be integer, got {type(value).__name__}"
            if expected_type == "boolean" and not isinstance(value, bool):
                return False, f"Parameter '{key}' must be boolean, got {type(value).__name__}"

    return True, ""


async def execute_tool(
    name: str,
    arguments: dict,
    user_id: int,
    confirm_fn: ConfirmFn | None = None,
) -> str:
    """Execute a tool by name, log the call, return result string.

    If confirm_fn is provided and the tool is dangerous, asks user for
    confirmation before executing. Returns denial message if refused.
    """
    tool = _TOOLS.get(name)
    if not tool:
        return f"Tool not found: {name}"

    # Validate arguments against schema
    valid, error = _validate_tool_args(tool, arguments)
    if not valid:
        logger.warning("Tool %s args validation failed: %s", name, error)
        return f"Tool argument error: {error}. Please check the parameters and try again."

    # Dangerous tool confirmation gate
    if confirm_fn and is_dangerous_tool(name):
        summary = _summarize_args(name, arguments)
        try:
            approved = await confirm_fn(name, summary)
        except Exception as e:
            logger.warning("confirmation callback error for %s: %s", name, e)
            approved = False
        if not approved:
            log_tool_call(user_id, name, arguments, "[DENIED by user]", success=False)
            return f"Tool '{name}' execution was denied by user."

    # Retry logic for network-dependent tools
    max_attempts = MAX_TOOL_RETRIES + 1 if name in NETWORK_TOOLS else 1
    last_error = None
    for attempt in range(max_attempts):
        try:
            result = await tool.execute(arguments)
            log_tool_call(user_id, name, arguments, result, success=True)
            return result
        except _RETRYABLE_ERRORS as e:
            last_error = e
            if attempt < max_attempts - 1:
                delay = RETRY_DELAY * (2 ** attempt)
                logger.warning("Tool %s retry %d/%d after %.1fs: %s", name, attempt + 1, MAX_TOOL_RETRIES, delay, e)
                await asyncio.sleep(delay)
            else:
                error_msg = f"Tool {name} failed after {max_attempts} attempts: {e}"
                log_tool_call(user_id, name, arguments, error_msg, success=False)
                return error_msg
        except Exception as e:
            error_msg = f"Tool execution error ({name}): {str(e)[:500]}"
            log_tool_call(user_id, name, arguments, error_msg, success=False)
            return error_msg
    return f"Tool {name} failed: {last_error}"
