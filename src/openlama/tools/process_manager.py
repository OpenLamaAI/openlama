"""Tool: process_manager – process and system management (admin only)."""

import asyncio
import re
import shlex
import sys

from openlama.config import get_config_int
from openlama.tools.registry import register_tool

# Allowed actions — prevents arbitrary command fallback
_KNOWN_ACTIONS = {"ps", "kill", "top", "df", "free", "uptime", "netstat", "lsof", "systemctl", "sysinfo"}

# Allowed signals for kill
_ALLOWED_SIGNALS = {"TERM", "KILL", "HUP", "INT", "QUIT", "USR1", "USR2", "STOP", "CONT"}

# Safe argument pattern: alphanumeric, dash, dot, colon, slash, underscore
_SAFE_ARG_RE = re.compile(r'^[a-zA-Z0-9._:/@\-]+$')


def _sanitize_arg(arg: str) -> str | None:
    """Return sanitized argument or None if it contains shell metacharacters."""
    if not arg:
        return None
    if _SAFE_ARG_RE.match(arg):
        return arg
    return None


async def _run_cmd(cmd: str | list[str], timeout: int = None) -> str:
    """Run a command and return output. Prefers exec over shell when given a list."""
    if timeout is None:
        timeout = get_config_int("code_execution_timeout", 30)
    try:
        if isinstance(cmd, list):
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        else:
            proc = await asyncio.create_subprocess_shell(
                cmd,
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
        if err and proc.returncode != 0:
            parts.append(f"[stderr]\n{err}")
        parts.append(f"[exit code: {proc.returncode}]")
        return "\n".join(parts)

    except Exception as e:
        return f"Command execution error: {e}"


async def _execute(args: dict) -> str:
    action = args.get("action", "").strip()
    target = args.get("target", "").strip()

    if not action:
        return "Please specify an action (ps, kill, top, df, free, uptime, netstat, systemctl, lsof, sysinfo)"

    if action not in _KNOWN_ACTIONS:
        return f"Unknown action: {action}. Available: {', '.join(sorted(_KNOWN_ACTIONS))}"

    _win = sys.platform == "win32"

    if action == "ps":
        if _win:
            return await _run_cmd(["tasklist"])
        safe_target = _sanitize_arg(target)
        extra = safe_target or "aux"
        return await _run_cmd(["ps", extra])

    if action == "kill":
        if not target:
            return "Please specify a process PID or name to terminate."
        signal = args.get("signal", "TERM").upper()
        if signal not in _ALLOWED_SIGNALS:
            return f"Invalid signal: {signal}. Allowed: {', '.join(sorted(_ALLOWED_SIGNALS))}"
        safe_target = _sanitize_arg(target)
        if not safe_target:
            return f"Invalid target: contains disallowed characters."
        if _win:
            if safe_target.isdigit():
                return await _run_cmd(["taskkill", "/PID", safe_target, "/F"])
            return await _run_cmd(["taskkill", "/IM", safe_target, "/F"])
        if safe_target.isdigit():
            return await _run_cmd(["kill", f"-{signal}", safe_target])
        return await _run_cmd(["pkill", f"-{signal}", "-f", safe_target])

    if action == "top":
        if _win:
            return await _run_cmd("wmic cpu get loadpercentage")
        if sys.platform == "darwin":
            return await _run_cmd(["top", "-l", "1", "-n", "15", "-s", "0"])
        return await _run_cmd("top -b -n 1 | head -30")

    if action == "df":
        if _win:
            return await _run_cmd("wmic logicaldisk get size,freespace,caption")
        return await _run_cmd(["df", "-h"])

    if action == "free":
        if _win:
            return await _run_cmd("wmic os get freephysicalmemory,totalvisiblememorysize")
        return await _run_cmd(
            "free -h 2>/dev/null || "
            "(echo '=== Memory ===' && vm_stat && echo '' && "
            "echo '=== Swap ===' && sysctl vm.swapusage 2>/dev/null)"
        )

    if action == "uptime":
        if _win:
            return await _run_cmd("wmic os get lastbootuptime")
        return await _run_cmd(["uptime"])

    if action == "netstat":
        if _win:
            if target:
                safe_target = _sanitize_arg(target)
                if not safe_target:
                    return "Invalid target: contains disallowed characters."
                return await _run_cmd(["netstat", safe_target])
            return await _run_cmd(["netstat", "-ano"])
        if sys.platform == "darwin":
            return await _run_cmd("lsof -i -P -n | head -50")
        safe_target = _sanitize_arg(target)
        extra = safe_target or "-tlnp"
        return await _run_cmd(f"netstat {shlex.quote(extra)} 2>/dev/null || lsof -i -P -n | head -50")

    if action == "lsof":
        if _win:
            if target:
                safe_target = _sanitize_arg(target)
                if not safe_target:
                    return "Invalid target: contains disallowed characters."
                return await _run_cmd(f"netstat -ano | findstr :{shlex.quote(safe_target)}")
            return await _run_cmd(["netstat", "-ano"])
        if target:
            safe_target = _sanitize_arg(target)
            if not safe_target:
                return "Invalid target: contains disallowed characters."
            return await _run_cmd(f"lsof -i :{shlex.quote(safe_target)} 2>/dev/null || lsof -p {shlex.quote(safe_target)} 2>/dev/null")
        return await _run_cmd("lsof -i -P -n | head -50")

    if action == "systemctl":
        if _win:
            return "systemctl is not available on Windows. Use 'sc query' or Task Manager."
        if not target:
            return await _run_cmd("systemctl list-units --type=service --state=running 2>/dev/null || launchctl list | head -30")
        safe_target = _sanitize_arg(target)
        if not safe_target:
            return "Invalid target: contains disallowed characters."
        return await _run_cmd(f"systemctl {shlex.quote(safe_target)} 2>/dev/null || echo 'systemctl not available (macOS?)'")

    if action == "sysinfo":
        if _win:
            return await _run_cmd(
                'echo === OS === && ver && '
                'echo. && echo === Uptime === && wmic os get lastbootuptime && '
                'echo. && echo === Disk === && wmic logicaldisk get size,freespace,caption && '
                'echo. && echo === CPU === && wmic cpu get numberofcores,name && '
                'echo. && echo === Memory === && wmic os get freephysicalmemory,totalvisiblememorysize'
            )
        return await _run_cmd(
            "echo '=== OS ===' && uname -a && "
            "echo '' && echo '=== Uptime ===' && uptime && "
            "echo '' && echo '=== Disk ===' && df -h / && "
            "echo '' && echo '=== CPU ===' && (nproc 2>/dev/null || sysctl -n hw.ncpu) && "
            "echo '' && echo '=== Memory ===' && "
            "(free -h 2>/dev/null || (vm_stat | head -5))"
        )

    return f"Unknown action: {action}. Available: {', '.join(sorted(_KNOWN_ACTIONS))}"


register_tool(
    name="process_manager",
    description=(
        "Manage server processes and system status. "
        "List processes, terminate them, and monitor system resources."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": (
                    "Action to perform: ps (process list), kill (terminate process), top (real-time status), "
                    "df (disk), free (memory), uptime (uptime), netstat (network), "
                    "lsof (port/file), systemctl (service), sysinfo (system overview)"
                ),
            },
            "target": {
                "type": "string",
                "description": "Target (PID, process name, port number, service name, etc.)",
            },
            "signal": {
                "type": "string",
                "description": "Kill signal (default: TERM, force: KILL)",
                "default": "TERM",
            },
        },
        "required": ["action"],
    },
    execute=_execute,
    admin_only=True,
)
