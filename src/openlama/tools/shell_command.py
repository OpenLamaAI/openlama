"""Tool: shell_command – execute arbitrary shell commands (admin only)."""

from openlama.config import get_config_int
from openlama.tools.registry import register_tool
from openlama.utils.subprocess import run_command


async def _execute(args: dict) -> str:
    command = args.get("command", "").strip()
    if not command:
        return "Please provide a command to execute."
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
