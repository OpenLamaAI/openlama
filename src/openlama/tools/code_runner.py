"""Tool: code_execute – run code in Python, Node.js, or Shell."""

import asyncio
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from openlama.config import get_config_int
from openlama.tools.registry import register_tool


async def _execute(args: dict) -> str:
    language = args.get("language", "python").lower()
    code = args.get("code", "").strip()
    if not code:
        return "Please provide code to execute."

    timeout = get_config_int("code_execution_timeout", 30)

    runners = {
        "python": ("python3", ".py"),
        "node": ("node", ".js"),
        "nodejs": ("node", ".js"),
        "javascript": ("node", ".js"),
        "js": ("node", ".js"),
        "shell": ("bash", ".sh"),
        "bash": ("bash", ".sh"),
        "sh": ("sh", ".sh"),
        "zsh": ("zsh", ".zsh"),
    }

    if language not in runners:
        return f"Unsupported language: {language}. Supported: python, node/js, shell/bash"

    cmd, ext = runners[language]

    # Shell/bash: check availability on Windows
    if ext in (".sh", ".zsh") and sys.platform == "win32":
        if not shutil.which(cmd):
            # Try bash (e.g. Git Bash / WSL)
            if shutil.which("bash"):
                cmd = "bash"
            else:
                return (
                    "Shell scripts require bash. "
                    "Install Git Bash or WSL on Windows, "
                    "or use Python instead."
                )

    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=ext, delete=False) as f:
            f.write(code)
            tmp_path = f.name

        proc = await asyncio.create_subprocess_exec(
            cmd, tmp_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=tempfile.gettempdir(),
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return f"Execution timed out ({timeout}s)"

        Path(tmp_path).unlink(missing_ok=True)

        out = stdout.decode("utf-8", errors="replace")[:5000]
        err = stderr.decode("utf-8", errors="replace")[:2000]

        parts = []
        if out:
            parts.append(f"[stdout]\n{out}")
        if err:
            parts.append(f"[stderr]\n{err}")
        parts.append(f"[exit code: {proc.returncode}]")
        return "\n".join(parts) if parts else "(no output)"

    except Exception as e:
        return f"Code execution error: {e}"


register_tool(
    name="code_execute",
    description="Execute code and return the result. Supports Python, Node.js, and Shell (Bash).",
    parameters={
        "type": "object",
        "properties": {
            "language": {
                "type": "string",
                "description": "Programming language (python, node/js, shell/bash)",
                "enum": ["python", "node", "javascript", "shell", "bash"],
            },
            "code": {
                "type": "string",
                "description": "Code to execute",
            },
        },
        "required": ["language", "code"],
    },
    execute=_execute,
)
