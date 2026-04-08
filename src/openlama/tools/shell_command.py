"""Tool: shell_command – execute arbitrary shell commands (admin only)."""

import asyncio
import subprocess

from openlama.config import get_config_int
from openlama.tools.registry import register_tool


async def _execute(args: dict) -> str:
    command = args.get("command", "").strip()
    if not command:
        return "Please provide a command to execute."

    timeout = get_config_int("code_execution_timeout", 30)

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return f"Execution timed out ({timeout}s)"

        out = stdout.decode("utf-8", errors="replace")[:8000]
        err = stderr.decode("utf-8", errors="replace")[:2000]

        parts = []
        if out:
            parts.append(out)
        if err:
            parts.append(f"[stderr]\n{err}")
        parts.append(f"[exit code: {proc.returncode}]")
        return "\n".join(parts) if parts else "(no output)"

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
