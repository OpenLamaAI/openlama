"""Tool: process_manager – process and system management (admin only)."""

import asyncio
import re
import sys

from openlama.config import get_config_int
from openlama.tools.registry import register_tool

# ── Input validation ─────────────────────────────────────

_VALID_SIGNALS = frozenset({
    "TERM", "KILL", "HUP", "INT", "QUIT", "USR1", "USR2", "STOP", "CONT",
    "1", "2", "3", "9", "15", "19", "18",
})
_RE_PID = re.compile(r"^\d+$")
_RE_PORT = re.compile(r"^\d{1,5}$")
_RE_PROCESS_NAME = re.compile(r"^[\w\-.]+$")
_RE_PS_FLAGS = re.compile(r"^[a-zA-Z]+$")
# systemctl subcommands whitelist
_SYSTEMCTL_ACTIONS = frozenset({
    "status", "start", "stop", "restart", "enable", "disable",
    "is-active", "is-enabled", "list-units", "list-timers", "daemon-reload",
})


def _validate_signal(signal: str) -> str | None:
    """Return error message if signal is invalid, None if OK."""
    if signal.upper() in _VALID_SIGNALS:
        return None
    return f"Invalid signal: {signal}. Allowed: {', '.join(sorted(_VALID_SIGNALS))}"


def _validate_pid(target: str) -> str | None:
    if _RE_PID.match(target):
        return None
    return f"Invalid PID: {target}. Must be numeric."


def _validate_port(target: str) -> str | None:
    if _RE_PORT.match(target) and 0 < int(target) <= 65535:
        return None
    return f"Invalid port: {target}. Must be 1-65535."


def _validate_process_name(target: str) -> str | None:
    if _RE_PROCESS_NAME.match(target):
        return None
    return f"Invalid process name: {target}. Only alphanumeric, dash, dot, underscore allowed."


# ── Safe command execution ───────────────────────────────

async def _run_exec(args: list[str], timeout: int = None) -> str:
    """Run a command using exec (no shell) and return output."""
    if timeout is None:
        timeout = get_config_int("code_execution_timeout", 30)
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
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


async def _run_shell(cmd: str, timeout: int = None) -> str:
    """Run a fixed (hardcoded) shell command. Only for static pipelines."""
    if timeout is None:
        timeout = get_config_int("code_execution_timeout", 30)
    try:
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


# ── Known actions ────────────────────────────────────────
_KNOWN_ACTIONS = frozenset({
    "ps", "kill", "top", "df", "free", "uptime", "netstat", "lsof",
    "systemctl", "sysinfo",
})


async def _execute(args: dict) -> str:
    action = args.get("action", "").strip()
    target = args.get("target", "").strip()

    if not action:
        return "Please specify an action (ps, kill, top, df, free, uptime, netstat, systemctl, lsof, sysinfo)"

    # Block unknown actions — no more fallback to arbitrary commands
    if action not in _KNOWN_ACTIONS:
        return f"Unknown action: {action}. Available: {', '.join(sorted(_KNOWN_ACTIONS))}"

    _win = sys.platform == "win32"

    if action == "ps":
        if _win:
            return await _run_exec(["tasklist"])
        flags = target or "aux"
        if not _RE_PS_FLAGS.match(flags):
            return f"Invalid ps flags: {flags}. Only letters allowed (e.g., aux, ef)."
        return await _run_exec(["ps", flags])

    if action == "kill":
        if not target:
            return "Please specify a process PID or name to terminate."
        signal = args.get("signal", "TERM").upper()
        err = _validate_signal(signal)
        if err:
            return err
        if _win:
            if target.isdigit():
                return await _run_exec(["taskkill", "/PID", target, "/F"])
            err = _validate_process_name(target)
            if err:
                return err
            return await _run_exec(["taskkill", "/IM", target, "/F"])
        if target.isdigit():
            return await _run_exec(["kill", f"-{signal}", target])
        err = _validate_process_name(target)
        if err:
            return err
        return await _run_exec(["pkill", f"-{signal}", "-f", target])

    if action == "top":
        if _win:
            return await _run_exec(["wmic", "cpu", "get", "loadpercentage"])
        if sys.platform == "darwin":
            return await _run_exec(["top", "-l", "1", "-n", "15", "-s", "0"])
        return await _run_shell("top -b -n 1 | head -30")

    if action == "df":
        if _win:
            return await _run_exec(["wmic", "logicaldisk", "get", "size,freespace,caption"])
        return await _run_exec(["df", "-h"])

    if action == "free":
        if _win:
            return await _run_exec(["wmic", "os", "get", "freephysicalmemory,totalvisiblememorysize"])
        return await _run_shell(
            "free -h 2>/dev/null || "
            "(echo '=== Memory ===' && vm_stat && echo '' && "
            "echo '=== Swap ===' && sysctl vm.swapusage 2>/dev/null)"
        )

    if action == "uptime":
        if _win:
            return await _run_exec(["wmic", "os", "get", "lastbootuptime"])
        return await _run_exec(["uptime"])

    if action == "netstat":
        if _win:
            if target:
                if not _RE_PS_FLAGS.match(target.lstrip("-")):
                    return f"Invalid netstat flags: {target}"
                return await _run_exec(["netstat", target])
            return await _run_exec(["netstat", "-ano"])
        if sys.platform == "darwin":
            return await _run_shell("lsof -i -P -n | head -50")
        return await _run_shell("netstat -tlnp 2>/dev/null || lsof -i -P -n | head -50")

    if action == "lsof":
        if _win:
            if target:
                is_port = _RE_PORT.match(target) and 0 < int(target) <= 65535
                is_pid = _RE_PID.match(target)
                if not is_port and not is_pid:
                    return f"Invalid target: {target}. Provide a port number (1-65535) or PID."
                if is_port:
                    return await _run_exec(["netstat", "-ano", "|", "findstr", f":{target}"])
                return await _run_exec(["netstat", "-ano"])
            return await _run_exec(["netstat", "-ano"])
        if target:
            # Validate: must be a port number or PID
            if _RE_PORT.match(target) and 0 < int(target) <= 65535:
                return await _run_exec(["lsof", "-i", f":{target}"])
            if _RE_PID.match(target):
                return await _run_exec(["lsof", "-p", target])
            return f"Invalid target: {target}. Provide a port number (1-65535) or PID."
        return await _run_shell("lsof -i -P -n | head -50")

    if action == "systemctl":
        if _win:
            return "systemctl is not available on Windows. Use 'sc query' or Task Manager."
        if not target:
            return await _run_shell(
                "systemctl list-units --type=service --state=running 2>/dev/null || launchctl list | head -30"
            )
        # Parse "status nginx" or just "list-units"
        parts = target.split(None, 1)
        sub_action = parts[0]
        if sub_action not in _SYSTEMCTL_ACTIONS:
            return f"Invalid systemctl action: {sub_action}. Allowed: {', '.join(sorted(_SYSTEMCTL_ACTIONS))}"
        cmd_parts = ["systemctl", sub_action]
        if len(parts) > 1:
            svc_name = parts[1].strip()
            err = _validate_process_name(svc_name)
            if err:
                return f"Invalid service name: {svc_name}. Only alphanumeric, dash, dot, underscore allowed."
            cmd_parts.append(svc_name)
        return await _run_exec(cmd_parts)

    if action == "sysinfo":
        if _win:
            return await _run_shell(
                'echo === OS === && ver && '
                'echo. && echo === Uptime === && wmic os get lastbootuptime && '
                'echo. && echo === Disk === && wmic logicaldisk get size,freespace,caption && '
                'echo. && echo === CPU === && wmic cpu get numberofcores,name && '
                'echo. && echo === Memory === && wmic os get freephysicalmemory,totalvisiblememorysize'
            )
        return await _run_shell(
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
