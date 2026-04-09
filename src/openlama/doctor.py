"""openlama doctor — diagnose and fix agent health."""
from __future__ import annotations

import asyncio
import os
import shutil
import sys
from pathlib import Path
from dataclasses import dataclass, field

from openlama.config import DATA_DIR, get_config, get_config_bool
from openlama.logger import get_logger

logger = get_logger("doctor")


@dataclass
class CheckResult:
    name: str
    status: str  # "ok", "warn", "fail"
    message: str
    fixable: bool = False
    fix_action: str = ""  # description of what fix does


@dataclass
class DoctorReport:
    results: list[CheckResult] = field(default_factory=list)

    @property
    def ok_count(self) -> int:
        return sum(1 for r in self.results if r.status == "ok")

    @property
    def warn_count(self) -> int:
        return sum(1 for r in self.results if r.status == "warn")

    @property
    def fail_count(self) -> int:
        return sum(1 for r in self.results if r.status == "fail")

    @property
    def fixable_count(self) -> int:
        return sum(1 for r in self.results if r.status != "ok" and r.fixable)


# ─── Individual checks ─────────────────────────────

def check_data_dir() -> CheckResult:
    """Check if data directory exists and is writable."""
    if DATA_DIR.exists() and os.access(DATA_DIR, os.W_OK):
        return CheckResult("Data directory", "ok", str(DATA_DIR))

    if not DATA_DIR.exists():
        return CheckResult(
            "Data directory", "fail",
            f"{DATA_DIR} does not exist",
            fixable=True, fix_action="Create data directory",
        )
    return CheckResult(
        "Data directory", "fail",
        f"{DATA_DIR} is not writable",
    )


def fix_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def check_database() -> CheckResult:
    """Check if database exists and is valid."""
    db_path = DATA_DIR / "openlama.db"
    if not db_path.exists():
        return CheckResult(
            "Database", "fail",
            f"{db_path} not found",
            fixable=True, fix_action="Initialize database",
        )
    try:
        import sqlite3
        conn = sqlite3.connect(db_path)
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        conn.close()
        table_names = [t[0] for t in tables]
        required = ["users", "settings"]
        missing = [t for t in required if t not in table_names]
        if missing:
            return CheckResult(
                "Database", "warn",
                f"Missing tables: {', '.join(missing)}",
                fixable=True, fix_action="Run database migration",
            )
        return CheckResult("Database", "ok", f"{len(table_names)} tables")
    except Exception as e:
        return CheckResult("Database", "fail", f"Corrupt or unreadable: {e}")


def fix_database():
    from openlama.database import init_db
    init_db()


def check_telegram_token() -> CheckResult:
    """Check if Telegram bot token is configured."""
    token = get_config("telegram_bot_token")
    if not token:
        return CheckResult(
            "Telegram bot token", "fail",
            "Not configured",
            fixable=False,
            fix_action="Run 'openlama setup' or 'openlama config set telegram_bot_token <token>'",
        )
    # Mask token for display
    masked = token[:8] + "..." + token[-4:] if len(token) > 12 else "****"
    return CheckResult("Telegram bot token", "ok", f"Set ({masked})")


async def check_telegram_connection() -> CheckResult:
    """Check if the Telegram bot token is valid by calling getMe."""
    token = get_config("telegram_bot_token")
    if not token:
        return CheckResult("Telegram connection", "fail", "No token configured")
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"https://api.telegram.org/bot{token}/getMe")
            if r.status_code == 200:
                data = r.json()
                if data.get("ok"):
                    bot_info = data.get("result", {})
                    username = bot_info.get("username", "unknown")
                    return CheckResult(
                        "Telegram connection", "ok",
                        f"Bot @{username} is reachable",
                    )
            if r.status_code == 401:
                return CheckResult(
                    "Telegram connection", "fail",
                    "Invalid token (401 Unauthorized)",
                )
            return CheckResult(
                "Telegram connection", "warn",
                f"Unexpected response: HTTP {r.status_code}",
            )
    except Exception as e:
        return CheckResult("Telegram connection", "warn", f"Connection error: {e}")


async def check_ollama() -> CheckResult:
    """Check Ollama server connectivity."""
    url = get_config("ollama_base")
    try:
        from openlama.ollama_client import ollama_alive
        alive = await ollama_alive()
        if alive:
            return CheckResult("Ollama server", "ok", f"Connected ({url})")
        return CheckResult(
            "Ollama server", "fail",
            f"Not reachable at {url}",
            fixable=True,
            fix_action="Attempt to start Ollama",
        )
    except Exception as e:
        return CheckResult("Ollama server", "fail", f"Error: {e}")


async def fix_ollama():
    """Try to start Ollama (local only — remote servers cannot be started)."""
    from openlama.config import is_ollama_remote
    if is_ollama_remote():
        url = get_config("ollama_base")
        print(f"  Remote Ollama server at {url} is not reachable.")
        print("  Check that the remote server is running and accessible.")
        return False

    ollama_bin = shutil.which("ollama")
    if not ollama_bin:
        print("  Ollama binary not found. Install from https://ollama.com")
        return False

    try:
        import sys
        import subprocess

        started = False
        # macOS: prefer brew services if installed via brew
        if sys.platform == "darwin" and shutil.which("brew"):
            result = subprocess.run(
                ["brew", "list", "ollama"], capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                subprocess.run(["brew", "services", "start", "ollama"], capture_output=True, text=True, timeout=15)
                started = True

        # Linux: prefer systemctl
        if not started and shutil.which("systemctl"):
            subprocess.run(["systemctl", "start", "ollama"], capture_output=True, text=True, timeout=15)
            started = True

        # Fallback: direct ollama serve
        if not started:
            await asyncio.create_subprocess_exec(
                ollama_bin, "serve",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )

        for _ in range(10):
            await asyncio.sleep(1)
            from openlama.ollama_client import ollama_alive
            if await ollama_alive():
                return True
        return False
    except Exception:
        return False


async def check_ollama_version() -> CheckResult:
    """Check if Ollama is up to date."""
    try:
        from openlama.ollama_client import check_ollama_update
        info = await check_ollama_update()
        current = info["current"]
        latest = info["latest"]

        if current == "unknown":
            return CheckResult("Ollama version", "warn", "Could not determine current version")
        if latest == "unknown":
            return CheckResult("Ollama version", "ok", f"v{current} (could not check latest)")
        if info["update_available"]:
            return CheckResult(
                "Ollama version", "warn",
                f"v{current} → v{latest} available",
                fixable=True, fix_action="Update Ollama to latest version",
            )
        return CheckResult("Ollama version", "ok", f"v{current} (latest)")
    except Exception as e:
        return CheckResult("Ollama version", "warn", f"Check failed: {e}")


async def fix_ollama_version():
    """Update Ollama to the latest version."""
    ollama_bin = shutil.which("ollama")

    if sys.platform == "darwin" and shutil.which("brew"):
        proc = await asyncio.create_subprocess_exec(
            "brew", "upgrade", "ollama",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.wait()
        return proc.returncode == 0
    elif sys.platform != "win32" and shutil.which("bash"):
        proc = await asyncio.create_subprocess_exec(
            "bash", "-c", "curl -fsSL https://ollama.com/install.sh | sh",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.wait()
        return proc.returncode == 0
    elif sys.platform == "win32":
        print("  Windows: Please update Ollama manually from https://ollama.com/download/windows")
        return False

    return False


def check_service_registered() -> CheckResult:
    """Check if openlama is registered as an OS service for auto-start on boot."""
    from openlama.config import TERMUX
    if sys.platform == "darwin":
        plist = Path.home() / "Library" / "LaunchAgents" / "com.openlama.agent.plist"
        if plist.exists():
            return CheckResult("Boot service", "ok", "launchd agent registered")
        return CheckResult(
            "Boot service", "warn",
            "Not registered. Run 'openlama start --install-service' to auto-start on boot.",
            fixable=True, fix_action="Register launchd service",
        )
    elif TERMUX:
        script = Path.home() / ".termux" / "boot" / "start-openlama.sh"
        if script.exists():
            return CheckResult("Boot service", "ok", "Termux:Boot script registered")
        return CheckResult(
            "Boot service", "warn",
            "Not registered. Run 'openlama start --install-service' for Termux:Boot auto-start.",
            fixable=True, fix_action="Register Termux:Boot script",
        )
    elif sys.platform == "linux":
        unit = Path.home() / ".config" / "systemd" / "user" / "openlama.service"
        if unit.exists():
            return CheckResult("Boot service", "ok", "systemd user service registered")
        return CheckResult(
            "Boot service", "warn",
            "Not registered. Run 'openlama start --install-service' to auto-start on boot.",
            fixable=True, fix_action="Register systemd service",
        )
    elif sys.platform == "win32":
        import subprocess
        result = subprocess.run(
            'schtasks /query /tn "openlama"',
            shell=True, capture_output=True, text=True,
        )
        if result.returncode == 0:
            return CheckResult("Boot service", "ok", "Task Scheduler entry registered")
        return CheckResult(
            "Boot service", "warn",
            "Not registered. Run 'openlama start --install-service' to auto-start on boot.",
            fixable=True, fix_action="Register scheduled task",
        )
    return CheckResult("Boot service", "ok", f"Unsupported platform: {sys.platform}")


def fix_service():
    from openlama.service import install
    install()


async def check_ollama_models() -> CheckResult:
    """Check if any models are available."""
    try:
        from openlama.ollama_client import ollama_alive, list_models
        if not await ollama_alive():
            return CheckResult("Ollama models", "fail", "Ollama not reachable")
        models = await list_models()
        if not models:
            return CheckResult(
                "Ollama models", "warn",
                "No models installed. Run 'ollama pull <model>' to install one.",
            )
        default = get_config("default_model")
        if default and default not in models:
            return CheckResult(
                "Ollama models", "warn",
                f"Default model '{default}' not found. {len(models)} models available.",
            )
        model_list = ", ".join(models[:5])
        suffix = f" (+{len(models) - 5} more)" if len(models) > 5 else ""
        return CheckResult("Ollama models", "ok", f"{model_list}{suffix}")
    except Exception as e:
        return CheckResult("Ollama models", "fail", f"Error: {e}")


async def check_comfyui() -> CheckResult:
    """Check ComfyUI connectivity (if enabled)."""
    enabled = get_config("comfy_enabled", "false").lower() in ("true", "1", "yes")
    if not enabled:
        return CheckResult("ComfyUI", "ok", "Disabled (not required)")

    try:
        from openlama.utils.comfyui_client import comfyui_alive
        alive = await comfyui_alive()
        if alive:
            return CheckResult("ComfyUI", "ok", f"Connected ({get_config('comfy_base')})")

        start_cmd = get_config("comfy_start_cmd", "")
        if start_cmd:
            return CheckResult(
                "ComfyUI", "warn",
                f"Not running, but auto-start configured",
            )
        return CheckResult(
            "ComfyUI", "warn",
            f"Enabled but not running at {get_config('comfy_base')}",
        )
    except Exception as e:
        return CheckResult("ComfyUI", "warn", f"Error: {e}")


def check_comfyui_workflows() -> CheckResult:
    """Check if workflow files exist."""
    enabled = get_config("comfy_enabled", "false").lower() in ("true", "1", "yes")
    if not enabled:
        return CheckResult("ComfyUI workflows", "ok", "Disabled (not required)")

    workflows_dir = DATA_DIR / "workflows"
    if not workflows_dir.exists():
        return CheckResult(
            "ComfyUI workflows", "warn",
            f"Workflows directory not found: {workflows_dir}",
            fixable=True, fix_action="Create workflows directory",
        )

    json_files = list(workflows_dir.glob("*.json"))
    if not json_files:
        return CheckResult(
            "ComfyUI workflows", "warn",
            "No workflow JSON files found",
        )
    return CheckResult(
        "ComfyUI workflows", "ok",
        f"{len(json_files)} workflow(s): {', '.join(f.stem for f in json_files)}",
    )


def fix_comfyui_workflows():
    workflows_dir = DATA_DIR / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)


def check_prompts_dir() -> CheckResult:
    """Check if prompts directory and key files exist."""
    prompts_dir = Path(get_config("prompts_dir"))
    if not prompts_dir.exists():
        return CheckResult(
            "Prompts directory", "warn",
            f"Not found: {prompts_dir}",
            fixable=True, fix_action="Create prompts directory",
        )

    files = ["SOUL.md", "USERS.md"]
    existing = [f for f in files if (prompts_dir / f).exists()]
    missing = [f for f in files if f not in existing]

    if missing:
        return CheckResult(
            "Prompts directory", "warn",
            f"Missing: {', '.join(missing)}. Complete setup via Telegram.",
        )
    return CheckResult("Prompts directory", "ok", f"All prompt files present")


def fix_prompts_dir():
    prompts_dir = Path(get_config("prompts_dir"))
    prompts_dir.mkdir(parents=True, exist_ok=True)


def check_skills() -> CheckResult:
    """Check skills directory."""
    from openlama.core.skills import list_skills
    skills = list_skills()
    skills_dir = DATA_DIR / "skills"
    if not skills_dir.exists():
        return CheckResult("Skills", "ok", "No skills directory (none installed)")
    return CheckResult("Skills", "ok", f"{len(skills)} skill(s) installed")


def check_mcp_config() -> CheckResult:
    """Check MCP configuration."""
    from openlama.core.mcp_client import list_server_configs
    configs = list_server_configs()
    if not configs:
        return CheckResult("MCP servers", "ok", "None configured")
    return CheckResult("MCP servers", "ok", f"{len(configs)} server(s) configured")


def check_daemon() -> CheckResult:
    """Check if daemon process is running."""
    from openlama.daemon import _read_pid, PID_FILE
    pid = _read_pid()
    if pid:
        return CheckResult("Daemon process", "ok", f"Running (PID {pid})")
    if PID_FILE.exists():
        return CheckResult(
            "Daemon process", "warn",
            "Stale PID file found (process not running)",
            fixable=True, fix_action="Remove stale PID file",
        )
    return CheckResult("Daemon process", "ok", "Not running (foreground mode or stopped)")


def fix_daemon():
    from openlama.daemon import PID_FILE
    PID_FILE.unlink(missing_ok=True)


def check_python_deps() -> CheckResult:
    """Check if critical Python dependencies are importable."""
    missing = []
    for pkg, module in [
        ("python-telegram-bot", "telegram"),
        ("httpx", "httpx"),
        ("Pillow", "PIL"),
        ("click", "click"),
        ("rich", "rich"),
        ("mcp", "mcp"),
    ]:
        try:
            __import__(module)
        except ImportError:
            missing.append(pkg)

    if missing:
        return CheckResult(
            "Python dependencies", "fail",
            f"Missing: {', '.join(missing)}",
            fixable=True, fix_action="Install missing packages",
        )
    return CheckResult("Python dependencies", "ok", "All critical packages available")


def fix_python_deps():
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "-e", "."], check=False)


def check_disk_space() -> CheckResult:
    """Check available disk space in data directory."""
    try:
        stat = os.statvfs(DATA_DIR if DATA_DIR.exists() else Path.home())
        free_gb = (stat.f_bavail * stat.f_frsize) / (1024 ** 3)
        if free_gb < 1:
            return CheckResult("Disk space", "warn", f"{free_gb:.1f} GB free (low)")
        return CheckResult("Disk space", "ok", f"{free_gb:.1f} GB free")
    except Exception:
        return CheckResult("Disk space", "ok", "Check skipped (unsupported platform)")


def check_admin_password() -> CheckResult:
    """Check if admin password is set."""
    try:
        from openlama.database import get_admin_password_hash
        pw_hash = get_admin_password_hash()
        if pw_hash:
            return CheckResult("Admin password", "ok", "Set")
        return CheckResult(
            "Admin password", "warn",
            "Not set. First Telegram login will set the password.",
        )
    except Exception:
        return CheckResult("Admin password", "warn", "Could not check (DB not initialized)")


def check_allowlist() -> CheckResult:
    """Check allow list status."""
    try:
        from openlama.database import get_allowed_ids
        ids = get_allowed_ids()
        if ids:
            return CheckResult("Allow list", "ok", f"{len(ids)} user(s) authorized")
        return CheckResult(
            "Allow list", "ok",
            "Empty (first authenticated user will be auto-added)",
        )
    except Exception:
        return CheckResult("Allow list", "ok", "Could not check (DB not initialized)")


# ─── Main doctor logic ─────────────────────────────

async def run_checks() -> DoctorReport:
    """Run all diagnostic checks."""
    report = DoctorReport()

    # Sync checks
    for check_fn in [
        check_data_dir,
        check_database,
        check_telegram_token,
        check_python_deps,
        check_daemon,
        check_service_registered,
        check_disk_space,
        check_prompts_dir,
        check_skills,
        check_mcp_config,
        check_admin_password,
        check_allowlist,
        check_comfyui_workflows,
    ]:
        try:
            report.results.append(check_fn())
        except Exception as e:
            report.results.append(CheckResult(check_fn.__name__, "fail", f"Check crashed: {e}"))

    # Async checks
    for check_fn in [
        check_telegram_connection,
        check_ollama,
        check_ollama_version,
        check_ollama_models,
        check_comfyui,
    ]:
        try:
            report.results.append(await check_fn())
        except Exception as e:
            report.results.append(CheckResult(check_fn.__name__, "fail", f"Check crashed: {e}"))

    return report


async def run_fixes(report: DoctorReport) -> list[str]:
    """Attempt to fix all fixable issues. Returns list of fix results."""
    fix_map = {
        "Data directory": fix_data_dir,
        "Database": fix_database,
        "Ollama server": fix_ollama,
        "Ollama version": fix_ollama_version,
        "Boot service": fix_service,
        "ComfyUI workflows": fix_comfyui_workflows,
        "Prompts directory": fix_prompts_dir,
        "Daemon process": fix_daemon,
        "Python dependencies": fix_python_deps,
    }

    results = []
    for check in report.results:
        if check.status == "ok" or not check.fixable:
            continue

        fix_fn = fix_map.get(check.name)
        if not fix_fn:
            results.append(f"  {check.name}: No auto-fix available")
            continue

        try:
            if asyncio.iscoroutinefunction(fix_fn):
                success = await fix_fn()
            else:
                success = fix_fn()

            if success is False:
                results.append(f"  {check.name}: Fix attempted but failed")
            else:
                results.append(f"  {check.name}: Fixed")
        except Exception as e:
            results.append(f"  {check.name}: Fix failed — {e}")

    return results
