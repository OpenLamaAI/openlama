"""Tool: code_execute – run code in Python, Node.js, or Shell."""

import asyncio
import shutil
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

    # Resolve python command: python3 on Unix, python on Windows
    py_cmd = "python" if sys.platform == "win32" else "python3"

    runners = {
        "python": (py_cmd, ".py"),
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

    # Check if the runner exists
    if not shutil.which(cmd):
        # Fallback attempts
        if cmd == py_cmd and shutil.which(sys.executable):
            cmd = sys.executable
        elif ext in (".sh", ".zsh") and shutil.which("bash"):
            cmd = "bash"
        else:
            return f"'{cmd}' not found. Please install it or use a different language."

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
