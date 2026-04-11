"""Tool: self_update — Update openlama daemon to latest version."""

import asyncio
import shutil
import subprocess
import sys

from openlama.tools.registry import register_tool
from openlama.logger import get_logger

logger = get_logger("tool.update")


async def _execute(args: dict) -> str:
    action = args.get("action", "check").strip()

    if action == "check":
        return await _check_update()

    if action == "update":
        return await _do_update()

    return f"Unknown action: {action}. Available: check, update"


async def _check_update() -> str:
    """Check if a newer version is available."""
    from openlama import __version__
    try:
        import httpx
        r = await asyncio.to_thread(
            lambda: httpx.get("https://pypi.org/pypi/openlama/json", timeout=5)
        )
        if r.status_code == 200:
            latest = r.json().get("info", {}).get("version", "")
            if latest == __version__:
                return f"openlama is up to date (v{__version__})"
            return f"Update available: v{__version__} → v{latest}\nUse action 'update' to install."
    except Exception as e:
        return f"Version check failed: {e}"
    return "Could not check for updates."


async def _do_update() -> str:
    """Update openlama and restart daemon."""
    from openlama import __version__ as old_ver

    # Try uv first, then pip
    uv_bin = shutil.which("uv")
    updated = False
    method = ""

    if uv_bin:
        import os as _os
        clean_env = _os.environ.copy()
        clean_env.pop("VIRTUAL_ENV", None)
        clean_env.pop("UV_TOOL_DIR", None)
        result = await asyncio.to_thread(
            lambda: subprocess.run(
                [uv_bin, "tool", "install", "openlama", "--force", "--refresh"],
                capture_output=True, text=True, timeout=120,
                start_new_session=True, env=clean_env,
            )
        )
        if result.returncode == 0:
            updated = True
            method = "uv"

    if not updated:
        pip_cmds = [
            [sys.executable, "-m", "pip", "install", "--upgrade", "openlama"],
        ]
        # pip3 on Unix, pip on Windows
        pip_name = "pip" if sys.platform == "win32" else "pip3"
        pip_cmds.append([pip_name, "install", "--upgrade", "openlama"])
        for cmd in pip_cmds:
            if not shutil.which(cmd[0]):
                continue
            try:
                result = await asyncio.to_thread(
                    lambda c=cmd: subprocess.run(
                        c, capture_output=True, text=True, timeout=120,
                    )
                )
                if result.returncode == 0:
                    updated = True
                    method = "pip"
                    break
            except Exception:
                continue

    if not updated:
        return "Update failed — no pip/uv available."

    # Get new version
    new_ver = old_ver
    try:
        import httpx
        r = await asyncio.to_thread(
            lambda: httpx.get("https://pypi.org/pypi/openlama/json", timeout=5)
        )
        if r.status_code == 200:
            new_ver = r.json().get("info", {}).get("version", old_ver)
    except Exception:
        pass

    # Restart daemon
    restart_msg = ""
    try:
        from openlama.daemon import _read_pid, restart_daemon
        pid = _read_pid()
        if pid:
            await asyncio.to_thread(restart_daemon)
            restart_msg = " Daemon restarted."
    except Exception as e:
        restart_msg = f" Daemon restart failed: {e}"

    if new_ver != old_ver:
        return f"Updated: v{old_ver} → v{new_ver} (via {method}).{restart_msg}"
    return f"Already up to date (v{old_ver}).{restart_msg}"


register_tool(
    name="self_update",
    description="Check for and install openlama updates. Use when the user asks to update the bot/agent/daemon.",
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["check", "update"],
                "description": "check = check version, update = install latest and restart daemon",
            },
        },
        "required": ["action"],
    },
    execute=_execute,
    admin_only=True,
)
