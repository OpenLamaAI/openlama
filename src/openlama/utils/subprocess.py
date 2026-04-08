"""Shared subprocess runner for tool implementations."""
from __future__ import annotations

import asyncio


async def run_command(
    cmd: str | list[str],
    *,
    shell: bool = False,
    timeout: int = 30,
    max_stdout: int = 8000,
    max_stderr: int = 2000,
    cwd: str | None = None,
) -> str:
    """Run a subprocess and return formatted output.

    Returns a string with stdout, stderr (if any), and exit code.
    Kills the process on timeout.
    """
    if shell:
        if isinstance(cmd, list):
            cmd = " ".join(cmd)
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
    else:
        if isinstance(cmd, str):
            cmd = cmd.split()
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return f"Execution timed out ({timeout}s)"

    out = stdout.decode("utf-8", errors="replace")[:max_stdout] if stdout else ""
    err = stderr.decode("utf-8", errors="replace")[:max_stderr] if stderr else ""

    parts = []
    if out:
        parts.append(out)
    if err:
        parts.append(f"[stderr]\n{err}")
    parts.append(f"[exit code: {proc.returncode}]")
    return "\n".join(parts)
