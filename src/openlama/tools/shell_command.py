"""Tool: shell_command – execute arbitrary shell commands (admin only)."""

import shlex

from openlama.config import get_config_int
from openlama.tools.registry import register_tool
from openlama.utils.subprocess import run_command
from openlama.logger import get_logger

logger = get_logger("tool.shell")

# Shell metacharacters that enable command chaining/injection
_DANGEROUS_PATTERNS = [
    "$(", "`",           # command substitution
    "&&", "||",          # command chaining
    "|",                 # pipe
    ";",                 # command separator
    ">", ">>", "<",     # redirection
    "\n",               # newline (multi-command)
]

# Commands that should never be executed
_BLOCKED_COMMANDS = {
    "rm -rf /", "rm -rf /*", "mkfs", "dd if=/dev/zero",
    ":(){:|:&};:",  # fork bomb
}


def _validate_shell_command(command: str) -> tuple[bool, str]:
    """Validate shell command for dangerous patterns. Returns (safe, reason)."""
    cmd_lower = command.lower().strip()

    for blocked in _BLOCKED_COMMANDS:
        if blocked in cmd_lower:
            return False, f"Blocked command pattern: {blocked}"

    for pattern in _DANGEROUS_PATTERNS:
        if pattern in command:
            return False, f"Shell metacharacter not allowed: {repr(pattern)}. Use separate tool calls instead."

    return True, ""


async def _execute(args: dict) -> str:
    command = args.get("command", "").strip()
    if not command:
        return "Please provide a command to execute."

    safe, reason = _validate_shell_command(command)
    if not safe:
        logger.warning("shell_command blocked: %s — %s", command[:100], reason)
        return f"Command blocked: {reason}"

    timeout = get_config_int("code_execution_timeout", 30)
    try:
        return await run_command(command, shell=True, timeout=timeout)
    except Exception as e:
        return f"Command execution error: {e}"


register_tool(
    name="shell_command",
    description="Execute shell commands on the server. Use for system status checks, process management, file operations, etc.",
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Shell command to execute (e.g., 'ls -la', 'df -h', 'ps aux')",
            },
        },
        "required": ["command"],
    },
    execute=_execute,
    admin_only=True,
)
