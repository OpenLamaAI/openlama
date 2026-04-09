"""openlama CLI — main entry point."""
import click
from openlama import __version__

def _restart_daemon_if_running_cli():
    """Restart daemon if running, for config changes to take effect."""
    try:
        from openlama.daemon import _read_pid, restart_daemon
        pid = _read_pid()
        if pid:
            click.echo("  ⟳ Restarting daemon to apply changes...")
            restart_daemon()
            click.echo("  ✓ Daemon restarted")
    except Exception as e:
        click.echo(f"  ⚠ Could not restart daemon: {e}")
        click.echo("  Run manually: openlama restart")


def _ver_tuple(v: str) -> tuple[int, ...]:
    """Parse version string to tuple for comparison. '0.1.28' → (0, 1, 28)"""
    try:
        return tuple(int(x) for x in v.split("."))
    except (ValueError, AttributeError):
        return (0,)


def _check_for_update():
    """Check if a newer version is available on PyPI. Non-blocking, cached."""
    import time
    cache_file = None
    try:
        from openlama.config import DATA_DIR
        cache_file = DATA_DIR / ".update_check"
        # Check at most once per hour
        if cache_file.exists():
            data = cache_file.read_text().strip().split("|")
            if len(data) == 2:
                ts, cached_ver = float(data[0]), data[1]
                if time.time() - ts < 300:  # 5 minutes
                    if cached_ver and _ver_tuple(cached_ver) > _ver_tuple(__version__):
                        click.echo(f"  ⬆ Update available: v{__version__} → v{cached_ver}  (openlama update)")
                    return

        import httpx
        r = httpx.get("https://pypi.org/pypi/openlama/json", timeout=3,
                      headers={"Cache-Control": "no-cache"})
        if r.status_code == 200:
            latest = r.json().get("info", {}).get("version", "")
            if cache_file:
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(f"{time.time()}|{latest}")
            if latest and _ver_tuple(latest) > _ver_tuple(__version__):
                click.echo(f"  ⬆ Update available: v{__version__} → v{latest}  (openlama update)")
    except Exception:
        pass


@click.group()
@click.version_option(version=__version__, prog_name="openlama")
@click.pass_context
def main(ctx):
    """openlama — Personal AI agent bot powered by Ollama.

    \b
    Quick start:
      openlama setup                    Interactive setup wizard
      openlama start                    Start Telegram bot (foreground)
      openlama start -d                 Start as background daemon
      openlama start --install-service    Register as OS service (auto-start on boot)
      openlama start --uninstall-service Remove OS service registration
      openlama chat                      Interactive terminal chat (TUI)

    \b
    Daemon management:
      openlama stop               Stop the daemon
      openlama restart            Restart the daemon
      openlama status             Show connection and process status
      openlama logs               View daemon logs
      openlama logs --last 50     Show last 50 lines
      openlama logs --level ERROR Filter by log level

    \b
    Tools & Extensions:
      openlama tool list          List all registered tools
      openlama skill list         List installed skills
      openlama skill create       Create a new skill interactively
      openlama skill delete NAME  Delete a skill
      openlama mcp list           List MCP servers
      openlama mcp add NAME CMD   Add an MCP server
      openlama mcp remove NAME    Remove an MCP server
      openlama cron list          List scheduled tasks
      openlama cron delete ID     Delete a scheduled task

    \b
    Configuration:
      openlama config list        View all settings
      openlama config get KEY     Get a single setting
      openlama config set KEY VAL Set a config value
      openlama config reset       Reset all settings to defaults
      openlama config stt         Manage voice recognition (STT)
      openlama config obsidian    Manage Obsidian note integration

    \b
    Maintenance:
      openlama doctor             Diagnose and fix issues
      openlama doctor fix         Auto-fix fixable issues
      openlama update             Update openlama and Ollama
      openlama update --self-only   Update openlama only
      openlama update --ollama-only Update Ollama only

    \b
    TUI chat commands (inside 'openlama chat'):
      /help         Show commands         /clear      Clear context
      /model        Change model          /models     List models
      /settings     Model parameters      /set K V    Set parameter
      /think        Toggle think mode     /compress   Compress context
      /status       Session info          /session    View/extend session
      /export       Export conversation   /profile    Redo profile setup
      /pull MODEL   Download model        /rm MODEL   Delete model
      /skills       List skills           /cron       List tasks
      /mcp          MCP status            /ollama     Server management
      /quit         Exit chat
    """
    # Check for updates on every command (except --version itself)
    if ctx.invoked_subcommand:
        _check_for_update()

# ─── Core commands ───────────────────────��─────

@main.command()
def setup():
    """Run the interactive setup wizard (Ollama, models, Telegram, password)."""
    from openlama.logo import print_logo
    print_logo()
    from openlama.onboarding import run_setup
    run_setup()

@main.command()
@click.option("-d", "--daemon", is_flag=True, help="Run as background daemon")
@click.option("--with-cli", is_flag=True, help="Enable CLI chat alongside Telegram")
@click.option("--install-service", is_flag=True, help="Register as OS service (auto-start on boot)")
@click.option("--uninstall-service", is_flag=True, help="Remove OS service registration")
def start(daemon, with_cli, install_service, uninstall_service):
    """Start the Telegram bot (foreground by default, -d for daemon)."""
    if install_service:
        from openlama.service import install
        install()
        return
    if uninstall_service:
        from openlama.service import uninstall
        uninstall()
        return

    # Pre-flight check: ensure setup has been done
    from openlama.config import get_config
    token = get_config("telegram_bot_token")
    if not token:
        click.echo()
        click.echo("  openlama is not configured yet.")
        click.echo("  Run 'openlama setup' first to complete initial setup.")
        click.echo()
        raise SystemExit(1)

    from openlama.logo import print_logo
    print_logo()

    if daemon:
        from openlama.daemon import start_daemon
        start_daemon()
    else:
        from openlama.config import TERMUX
        if TERMUX:
            # Foreground mode on Termux: acquire wake-lock to survive screen-off
            import subprocess as _sp
            result = _sp.run(["termux-wake-lock"], capture_output=True, timeout=5)
            if result.returncode == 0:
                click.echo("  🔒 Wake lock acquired")
            else:
                click.echo("  ⚠ termux-wake-lock failed — process may be killed when screen is off")
                click.echo("    Install Termux:API app from F-Droid and run: pkg install termux-api")
        try:
            from openlama.channels.telegram.bot import main as run_telegram
            run_telegram()
        finally:
            if TERMUX:
                _sp.run(["termux-wake-unlock"], capture_output=True, timeout=5)

@main.command()
def stop():
    """Stop the background daemon process."""
    from openlama.daemon import stop_daemon
    stop_daemon()

@main.command()
def restart():
    """Restart the background daemon (stop + start)."""
    from openlama.daemon import restart_daemon
    restart_daemon()

@main.command()
def chat():
    """Interactive terminal chat (TUI). Shares context with Telegram.

    \b
    Features:
      • Dynamic slash command search (type / to see all commands)
      • Rich markdown rendering with syntax highlighting
      • Bottom toolbar with processing indicator
      • Command history (persistent across sessions)

    \b
    Commands: /help, /model, /models, /settings, /set, /think,
    /clear, /compress, /status, /session, /export, /profile,
    /pull, /rm, /skills, /cron, /mcp, /ollama, /quit
    """
    import asyncio
    from openlama.channels.cli.chat import run_chat
    asyncio.run(run_chat())

@main.command()
def status():
    """Show process, Ollama, ComfyUI, MCP, and skills status."""
    import asyncio
    import sys
    from pathlib import Path
    from rich.console import Console
    from rich.panel import Panel
    from openlama.logo import print_logo
    from openlama.daemon import get_daemon_status, _read_pid, _find_running_process, _is_launchd_managed, _is_systemd_managed
    from openlama.config import get_config, TERMUX

    console = Console()
    print_logo(console, compact=True)

    # Process status with execution mode
    pid_info = get_daemon_status()

    # Detect execution mode
    run_mode = ""
    if _is_launchd_managed():
        run_mode = "launchd service"
    elif sys.platform == "linux" and not TERMUX:
        if _is_systemd_managed():
            run_mode = "systemd service"
    elif TERMUX:
        boot_script = Path.home() / ".termux" / "boot" / "start-openlama.sh"
        if boot_script.exists():
            run_mode = "Termux:Boot"

    if not run_mode:
        pid = _read_pid()
        if pid:
            run_mode = "daemon (-d)"
        elif _find_running_process():
            run_mode = "foreground (start)"

    # Ollama status
    async def check_ollama():
        from openlama.ollama_client import ollama_alive, list_models, check_ollama_update
        alive = await ollama_alive()
        models = await list_models() if alive else []
        ver_info = await check_ollama_update() if alive else {}
        return alive, models, ver_info

    alive, models, ver_info = asyncio.run(check_ollama())
    ollama_url = get_config("ollama_base")
    default_model = get_config("default_model")

    lines = []
    lines.append(f"  Process:  {pid_info}")
    if run_mode:
        lines.append(f"    Mode:   {run_mode}")
    lines.append(f"")
    ver_str = f" v{ver_info.get('current', '?')}" if ver_info else ""
    lines.append(f"  Ollama:   {'Connected' + ver_str if alive else 'Not reachable'}")
    lines.append(f"    URL:    {ollama_url}")
    if alive:
        lines.append(f"    Default: {default_model or '(none)'}")
        if models:
            MAX_DISPLAY = 5
            if len(models) <= MAX_DISPLAY:
                lines.append(f"    Models:  {', '.join(models)}")
            else:
                shown = ', '.join(models[:MAX_DISPLAY])
                lines.append(f"    Models:  {shown} ... (+{len(models) - MAX_DISPLAY} more, {len(models)} total)")
        else:
            lines.append(f"    Models:  (none)")
        if ver_info.get("update_available"):
            lines.append(f"    Update:  v{ver_info['latest']} available")
    lines.append(f"")

    comfy_enabled = get_config("comfy_enabled", "false").lower() == "true"
    lines.append(f"  ComfyUI:  {'Enabled' if comfy_enabled else 'Disabled'}")

    # MCP servers
    from openlama.core.mcp_client import list_server_configs
    mcp_configs = list_server_configs()
    lines.append(f"")
    lines.append(f"  MCP:      {len(mcp_configs)} server(s) configured")

    # Skills
    from openlama.core.skills import list_skills
    skills = list_skills()
    lines.append(f"  Skills:   {len(skills)} installed")

    console.print(Panel("\n".join(lines), title=f"openlama v{__version__}", border_style="blue"))


def _find_brew() -> str | None:
    """Find brew binary even when PATH is incomplete (e.g. SSH non-interactive)."""
    import shutil
    b = shutil.which("brew")
    if b:
        return b
    from pathlib import Path
    for p in ["/opt/homebrew/bin/brew", "/usr/local/bin/brew"]:
        if Path(p).exists():
            return p
    return None


def _detect_ollama_install() -> str:
    """Detect how Ollama was installed. Returns: 'brew', 'app', 'script', 'unknown'."""
    import shutil
    import subprocess
    import sys
    from pathlib import Path

    if sys.platform != "darwin" and sys.platform != "linux":
        return "unknown"

    ollama_path = shutil.which("ollama") or ""

    # Also check known homebrew paths when PATH is incomplete (SSH)
    if not ollama_path:
        for p in ["/opt/homebrew/bin/ollama", "/usr/local/bin/ollama"]:
            if Path(p).exists():
                ollama_path = p
                break

    # macOS detection
    if sys.platform == "darwin":
        # Check if binary lives in Cellar (definitive brew indicator)
        if ollama_path:
            try:
                resolved = str(Path(ollama_path).resolve())
                if "/Cellar/" in resolved:
                    return "brew"
            except Exception:
                pass

        # Check via brew list
        brew_bin = _find_brew()
        if brew_bin:
            try:
                result = subprocess.run(
                    [brew_bin, "list", "ollama"],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0 and "Cellar" in result.stdout:
                    return "brew"
            except Exception:
                pass

        # Check if installed as .app
        if Path("/Applications/Ollama.app").exists():
            return "app"

    # Linux: check systemd service
    if sys.platform == "linux" and shutil.which("systemctl"):
        try:
            result = subprocess.run(
                ["systemctl", "is-enabled", "ollama"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                return "systemd"
        except Exception:
            pass

    if ollama_path:
        return "script"

    return "unknown"


def _update_ollama_binary(console, platform: str) -> bool:
    """Update Ollama binary and restart. Returns True if upgrade was attempted."""
    import subprocess
    import shutil

    method = _detect_ollama_install()
    console.print(f"  [dim]Install method: {method}[/dim]")

    if platform == "win32":
        console.print("  Windows: download from https://ollama.com/download/windows")
        return False

    if method == "brew":
        brew_bin = _find_brew() or "brew"
        subprocess.run([brew_bin, "upgrade", "ollama"], capture_output=True, text=True, timeout=300)
        subprocess.run([brew_bin, "services", "restart", "ollama"], capture_output=True, text=True, timeout=30)
        return True

    if method == "app":
        # Ollama.app: no CLI updater — the app auto-updates on launch
        console.print("  Ollama.app detected — close and reopen Ollama.app to update,")
        console.print("  or switch to brew: brew install ollama && brew services start ollama")
        # Try to at least restart the running process
        subprocess.run(["pkill", "-f", "Ollama"], capture_output=True, timeout=5)
        return False

    if method == "script" or shutil.which("bash"):
        # Linux / macOS without brew: official install script
        subprocess.run(
            ["bash", "-c", "curl -fsSL https://ollama.com/install.sh | sh"],
            capture_output=True, text=True, timeout=300,
        )
        if shutil.which("systemctl"):
            subprocess.run(["systemctl", "restart", "ollama"], capture_output=True, text=True, timeout=30)
        else:
            subprocess.run(["pkill", "-f", "ollama"], capture_output=True, timeout=5)
        return True

    console.print(f"  Could not detect install method. Visit https://ollama.com")
    return False


# ─── Update command ─────────────────────────────

@main.command()
@click.option("--ollama-only", is_flag=True, help="Only update Ollama, not openlama")
@click.option("--self-only", is_flag=True, help="Only update openlama, not Ollama")
def update(ollama_only, self_only):
    """Update openlama and Ollama to latest versions."""
    import asyncio
    import subprocess
    import sys
    import shutil
    from rich.console import Console
    from openlama import __version__ as old_ver
    console = Console()

    if not ollama_only:
        console.print(f"\n  [bold]Updating openlama...[/bold] (current: v{old_ver})")
        try:
            # Check PyPI for latest version — JSON API updates faster than Simple API
            import httpx as _httpx
            latest_ver = None
            try:
                # Primary: JSON API (faster CDN propagation)
                r = _httpx.get("https://pypi.org/pypi/openlama/json", timeout=5,
                               headers={"Cache-Control": "no-cache"})
                if r.status_code == 200:
                    latest_ver = r.json().get("info", {}).get("version", "")
                if not latest_ver:
                    # Fallback: Simple API
                    r2 = _httpx.get("https://pypi.org/simple/openlama/", timeout=5,
                                    headers={"Accept": "application/vnd.pypi.simple.v1+json",
                                             "Cache-Control": "no-cache"})
                    if r2.status_code == 200:
                        data = r2.json()
                        versions = [v for v in data.get("versions", []) if not any(c in v for c in ("a", "b", "rc", "dev"))]
                        if versions:
                            latest_ver = sorted(versions, key=_ver_tuple)[-1]
            except Exception:
                pass

            if latest_ver and _ver_tuple(latest_ver) <= _ver_tuple(old_ver):
                console.print(f"  Already up to date (v{old_ver})")
            elif latest_ver:
                console.print(f"  [dim]Latest: v{latest_ver}[/dim]")

                uv_bin = shutil.which("uv")
                pipx_bin = shutil.which("pipx")

                # Detect install method
                openlama_bin = shutil.which("openlama") or ""
                method = "pip"
                if uv_bin:
                    check = subprocess.run([uv_bin, "tool", "list"], capture_output=True, text=True, timeout=10)
                    if check.returncode == 0 and "openlama" in check.stdout:
                        method = "uv_tool"
                if pipx_bin and method == "pip":
                    check = subprocess.run([pipx_bin, "list"], capture_output=True, text=True, timeout=10)
                    if check.returncode == 0 and "openlama" in check.stdout:
                        method = "pipx"

                console.print(f"  [dim]Install method: {method}[/dim]")

                if method == "uv_tool":
                    result = subprocess.run(
                        [uv_bin, "tool", "install", f"openlama>={latest_ver}", "--force", "--refresh"],
                        capture_output=True, text=True, timeout=120,
                    )
                    if result.returncode != 0:
                        console.print(f"  [yellow]uv failed, trying pip...[/yellow]")
                        subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "openlama", "--no-cache-dir"],
                                       capture_output=True, timeout=120)
                elif method == "pipx":
                    subprocess.run([pipx_bin, "upgrade", "openlama"], capture_output=True, text=True, timeout=120)
                else:
                    subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "openlama", "--no-cache-dir"],
                                   capture_output=True, timeout=120)

                ver_out = subprocess.run(["openlama", "--version"], capture_output=True, text=True, timeout=10)
                new_ver = ver_out.stdout.strip().split()[-1] if ver_out.returncode == 0 else "?"
                if new_ver != old_ver:
                    console.print(f"  [green]Updated: v{old_ver} -> v{new_ver}[/green]")
                else:
                    console.print(f"  [yellow]Version unchanged (v{new_ver}). Try: uv tool install openlama --force --refresh[/yellow]")
            else:
                console.print(f"  Could not check PyPI. Try: uv tool install openlama --force --refresh")
        except Exception as e:
            console.print(f"  [red]Failed: {e}[/red]")

    if not self_only:
        console.print("\n  [bold]Checking Ollama...[/bold]")

        async def _check():
            from openlama.ollama_client import check_ollama_update
            return await check_ollama_update()

        info = asyncio.run(_check())
        current = info.get("current", "unknown")
        latest = info.get("latest", "unknown")

        if not info.get("update_available"):
            console.print(f"  Already up to date (v{current})")
        else:
            console.print(f"  Updating Ollama v{current} -> v{latest}...")
            try:
                upgraded = _update_ollama_binary(console, sys.platform)
                if upgraded:
                    import time
                    # Wait for Ollama to fully restart with new binary
                    console.print("  Waiting for Ollama to restart...")
                    new_current = current
                    for attempt in range(10):
                        time.sleep(2)
                        try:
                            info2 = asyncio.run(_check())
                            new_current = info2.get("current", "?")
                            if new_current != current and new_current != "?":
                                break
                        except Exception:
                            continue

                    if new_current != current and new_current != "?":
                        console.print(f"  [green]Updated: v{current} -> v{new_current}[/green]")
                    else:
                        console.print(f"  Upgrade installed but version unchanged (v{new_current}).")
                        console.print(f"  Try: brew services restart ollama")
            except Exception as e:
                console.print(f"  [red]Failed: {e}[/red]")

    # Restart daemon if running (or managed by service manager)
    from openlama.daemon import _read_pid, _find_running_process, _is_launchd_managed, _is_systemd_managed
    is_running = _read_pid() or _find_running_process() or _is_launchd_managed() or _is_systemd_managed()
    if is_running and not ollama_only:
        console.print("\n  [bold]Restarting daemon...[/bold]")
        from openlama.daemon import restart_daemon
        restart_daemon()

    console.print()


# ─── Config commands ─────────────────────────────

@main.group()
def config():
    """View and modify configuration (get, set, list, reset)."""
    pass

@config.command("list")
def config_list():
    """Show all configuration key-value pairs."""
    from rich.console import Console
    from rich.table import Table
    from openlama.config import _DEFAULTS, get_config

    console = Console()
    table = Table(title="openlama Configuration", show_lines=True)
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="green")
    table.add_column("Default", style="dim")

    for key in sorted(_DEFAULTS.keys()):
        val = get_config(key)
        default = _DEFAULTS[key]
        # Mask sensitive values
        display = val
        if "token" in key or "password" in key or "hash" in key:
            display = val[:8] + "****" if len(val) > 8 else "****"
        table.add_row(key, display, default if val != default else "")

    console.print(table)

@config.command("get")
@click.argument("key")
def config_get(key):
    """Get a single configuration value."""
    from openlama.config import get_config
    val = get_config(key)
    if "token" in key or "password" in key or "hash" in key:
        click.echo(f"{key} = {val[:8]}****" if len(val) > 8 else f"{key} = ****")
    else:
        click.echo(f"{key} = {val}")

@config.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key, value):
    """Set a configuration value."""
    from openlama.database import init_db, set_setting
    init_db()
    set_setting(key, value)
    click.echo(f"✓ {key} = {value}")
    _restart_daemon_if_running_cli()

@config.command("reset")
@click.confirmation_option(prompt="Reset all settings?")
def config_reset():
    """Reset all settings to defaults."""
    click.echo("Settings reset. Run 'openlama setup' to reconfigure.")
    _restart_daemon_if_running_cli()


@config.command("stt")
@click.argument("action", required=False, default="status")
def config_stt(action):
    """Manage voice recognition (STT).

    \b
    Usage:
      openlama config stt            Show STT status
      openlama config stt install    Install faster-whisper
      openlama config stt enable     Enable STT
      openlama config stt disable    Disable STT
    """
    import sys
    import shutil
    import subprocess
    from openlama.database import init_db, set_setting
    from openlama.config import get_config
    init_db()

    if action == "status":
        enabled = get_config("stt_enabled", "false").lower() in ("true", "1")
        try:
            import faster_whisper
            installed = True
        except ImportError:
            installed = False
        click.echo(f"  STT installed:  {'Yes' if installed else 'No'}")
        click.echo(f"  STT enabled:    {'Yes' if enabled else 'No'}")
        if not installed:
            click.echo("  Install: openlama config stt install")
        return

    if action == "install":
        click.echo("  Installing faster-whisper...")
        python = sys.executable
        uv = shutil.which("uv")
        installed = False

        methods = []
        if uv:
            methods.append([uv, "pip", "install", "--python", python, "faster-whisper"])
        methods.append([python, "-m", "pip", "install", "faster-whisper"])
        if shutil.which("pip3"):
            methods.append(["pip3", "install", "faster-whisper"])

        for cmd in methods:
            try:
                click.echo(f"  Trying: {' '.join(cmd[:4])}...")
                result = subprocess.run(cmd, capture_output=True, timeout=300)
                if result.returncode == 0:
                    installed = True
                    break
            except (subprocess.TimeoutExpired, FileNotFoundError):
                continue

        if installed:
            set_setting("stt_enabled", "true")
            click.echo("  ✓ Installed and enabled")
        else:
            click.echo("  ✗ Installation failed — try: uv pip install --python $(which python3) faster-whisper")
        return

    if action == "enable":
        set_setting("stt_enabled", "true")
        click.echo("  ✓ STT enabled")
        return

    if action == "disable":
        set_setting("stt_enabled", "false")
        click.echo("  ✓ STT disabled")
        return

    click.echo(f"Unknown action: {action}. Use: status, install, enable, disable")


@config.command("obsidian")
@click.argument("args", nargs=-1)
def config_obsidian(args):
    """Manage Obsidian note integration.

    \b
    Usage:
      openlama config obsidian              Show status
      openlama config obsidian install      Install obsidian-cli
      openlama config obsidian vault NAME   Set vault name
      openlama config obsidian disable      Disable Obsidian integration
    """
    action = args[0] if args else "status"
    import shutil
    import subprocess
    from openlama.database import init_db, set_setting
    from openlama.config import get_config
    init_db()

    if action == "status":
        cli_installed = shutil.which("obsidian-cli") is not None
        vault = get_config("obsidian_vault")
        click.echo(f"  CLI installed:  {'Yes' if cli_installed else 'No'}")
        click.echo(f"  Vault:          {vault or '(not set)'}")
        click.echo(f"  Enabled:        {'Yes' if vault else 'No'}")
        if not cli_installed:
            click.echo("  Install CLI: openlama config obsidian install")
        if not vault:
            click.echo("  Set vault:   openlama config obsidian vault <name>")
        return

    if action == "install":
        click.echo("  Installing obsidian-cli...")
        brew = shutil.which("brew")
        if brew:
            try:
                subprocess.run([brew, "tap", "yakitrak/yakitrak"], capture_output=True, timeout=60)
                result = subprocess.run([brew, "install", "obsidian-cli"], capture_output=True, timeout=120)
                if result.returncode == 0:
                    click.echo("  ✓ obsidian-cli installed")
                    return
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

        go = shutil.which("go")
        if go:
            try:
                click.echo("  Trying: go install...")
                result = subprocess.run(
                    [go, "install", "github.com/Yakitrak/obsidian-cli@latest"],
                    capture_output=True, timeout=120,
                )
                if result.returncode == 0:
                    click.echo("  ✓ obsidian-cli installed via go")
                    return
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

        click.echo("  ✗ Installation failed")
        click.echo("  Manual: brew tap yakitrak/yakitrak && brew install obsidian-cli")
        return

    if action == "disable":
        set_setting("obsidian_vault", "")
        click.echo("  ✓ Obsidian integration disabled")
        _restart_daemon_if_running_cli()
        return

    if action == "vault":
        if len(args) < 2:
            click.echo("  Usage: openlama config obsidian vault <name>")
            click.echo("  Example: openlama config obsidian vault MyVault")
            return
        vault_name = args[1]
        set_setting("obsidian_vault", vault_name)
        cli_installed = shutil.which("obsidian-cli") is not None
        click.echo(f"  ✓ Obsidian vault: {vault_name}")
        if not cli_installed:
            click.echo("  ⚠ obsidian-cli not installed. Run: openlama config obsidian install")
        _restart_daemon_if_running_cli()
        return

    click.echo(f"  Unknown action: {action}. Use: status, install, vault <name>, disable")


# ─── Tool command ─────────────────────────────

@main.group()
def tool():
    """Manage tools (list registered tools)."""
    pass


@tool.command("list")
def tool_list():
    """List all registered tools."""
    from openlama.database import init_db
    from openlama.tools import init_tools, get_all_tools
    init_db()
    init_tools()

    tools = get_all_tools()
    if not tools:
        click.echo("  No tools registered.")
        return

    click.echo(f"\n  Registered tools ({len(tools)}):\n")
    click.echo(f"  {'Name':20s} {'Admin':6s} Description")
    click.echo(f"  {'─' * 20} {'─' * 6} {'─' * 50}")
    for t in sorted(tools, key=lambda x: x.name):
        admin = "yes" if t.admin_only else ""
        desc = (t.description or "")[:50]
        click.echo(f"  {t.name:20s} {admin:6s} {desc}")
    click.echo()


# ─── Logs command ─────────────────────────────

@main.command()
@click.option("--last", default=0, help="Show last N lines only")
@click.option("--level", default="", help="Filter by log level (INFO, WARNING, ERROR)")
def logs(last, level):
    """View daemon log output."""
    from openlama.daemon import tail_logs
    tail_logs(last=last, level=level)


# ─── Doctor command ────────────────────��────────

@main.command()
@click.argument("action", required=False, default="check")
def doctor(action):
    """Diagnose agent health and auto-fix issues.

    \b
    Usage:
      openlama doctor        Run all diagnostics
      openlama doctor fix    Run diagnostics and auto-fix fixable issues
    """
    import asyncio
    from rich.console import Console
    from rich.table import Table
    from openlama.doctor import run_checks, run_fixes

    console = Console()

    from openlama.logo import print_logo
    print_logo(console, compact=True)
    console.print("[bold]openlama doctor[/bold] — running diagnostics...\n")

    report = asyncio.run(run_checks())

    # Display results
    table = Table(show_lines=False, pad_edge=False, box=None)
    table.add_column("Status", width=4, justify="center")
    table.add_column("Check", style="bold", min_width=22)
    table.add_column("Details")

    icons = {"ok": "[green]✓[/green]", "warn": "[yellow]![/yellow]", "fail": "[red]✗[/red]"}

    for r in report.results:
        icon = icons.get(r.status, "?")
        style = {"ok": "", "warn": "yellow", "fail": "red"}.get(r.status, "")
        details = r.message
        if r.fixable and r.status != "ok":
            details += f" [dim](fixable: {r.fix_action})[/dim]"
        table.add_row(icon, r.name, details, style=style)

    console.print(table)

    # Summary
    console.print()
    summary_parts = [f"[green]{report.ok_count} passed[/green]"]
    if report.warn_count:
        summary_parts.append(f"[yellow]{report.warn_count} warning(s)[/yellow]")
    if report.fail_count:
        summary_parts.append(f"[red]{report.fail_count} failed[/red]")
    console.print(f"  {' · '.join(summary_parts)}")

    if report.fixable_count > 0:
        console.print(f"  [dim]{report.fixable_count} issue(s) can be auto-fixed. Run: openlama doctor fix[/dim]")

    # Fix mode
    if action == "fix":
        if report.fixable_count == 0 and report.fail_count == 0 and report.warn_count == 0:
            console.print("\n  [green]Nothing to fix — all checks passed![/green]\n")
            return

        console.print("\n[bold]Attempting auto-fixes...[/bold]\n")
        fix_results = asyncio.run(run_fixes(report))
        for line in fix_results:
            console.print(line)

        # Re-run checks
        console.print("\n[bold]Re-running diagnostics...[/bold]\n")
        report2 = asyncio.run(run_checks())

        table2 = Table(show_lines=False, pad_edge=False, box=None)
        table2.add_column("Status", width=4, justify="center")
        table2.add_column("Check", style="bold", min_width=22)
        table2.add_column("Details")

        for r in report2.results:
            icon = icons.get(r.status, "?")
            style = {"ok": "", "warn": "yellow", "fail": "red"}.get(r.status, "")
            table2.add_row(icon, r.name, r.message, style=style)

        console.print(table2)

        remaining = report2.fail_count + report2.warn_count
        if remaining == 0:
            console.print("\n  [green]All issues resolved![/green]\n")
        else:
            console.print(f"\n  [yellow]{remaining} issue(s) remaining. Some may need manual intervention.[/yellow]\n")

    console.print()


# ─── Cron commands ─────────────────────────────

@main.group()
def cron():
    """Manage scheduled tasks (list, delete)."""
    pass

@cron.command("list")
def cron_list():
    """List all scheduled tasks."""
    import datetime
    from rich.console import Console
    from rich.table import Table
    from openlama.database import init_db, list_cron_jobs

    init_db()
    console = Console()
    jobs = list_cron_jobs()
    if not jobs:
        console.print("[dim]No scheduled tasks.[/dim]")
        return

    table = Table(title="Scheduled Tasks", show_lines=True)
    table.add_column("ID", style="cyan", width=4)
    table.add_column("Status", width=4)
    table.add_column("Schedule", style="yellow")
    table.add_column("Task")
    table.add_column("Next Run", style="dim")

    for j in jobs:
        status = "ON" if j["enabled"] else "OFF"
        next_ts = j.get("next_run", 0)
        next_str = datetime.datetime.fromtimestamp(next_ts).strftime("%Y-%m-%d %H:%M") if next_ts > 0 else "-"
        table.add_row(str(j["id"]), status, j["cron_expr"], j["task"][:50], next_str)

    console.print(table)

@cron.command("delete")
@click.argument("job_id", type=int)
def cron_delete(job_id):
    """Delete a scheduled task by ID."""
    from openlama.database import init_db, delete_cron_job
    init_db()
    if delete_cron_job(job_id):
        click.echo(f"Task #{job_id} deleted.")
    else:
        click.echo(f"Task #{job_id} not found.")


# ─── Skill commands ─────────────────────────────

@main.group()
def skill():
    """Manage custom skills (list, create, delete)."""
    pass

@skill.command("list")
def skill_list():
    """List all installed skills."""
    from rich.console import Console
    from rich.table import Table
    from openlama.core.skills import list_skills

    console = Console()
    skills = list_skills()
    if not skills:
        console.print("[dim]No skills installed. Create one with 'openlama skill create'.[/dim]")
        return

    table = Table(title="Skills", show_lines=True)
    table.add_column("Name", style="cyan")
    table.add_column("Description", style="green")
    table.add_column("Trigger", style="yellow")

    for s in skills:
        table.add_row(s["name"], s.get("description", ""), s.get("trigger", ""))
    console.print(table)

@skill.command("create")
def skill_create():
    """Create a new skill interactively."""
    import questionary
    from openlama.core.skills import save_skill

    name = questionary.text("Skill name (kebab-case):").ask()
    if not name:
        return
    description = questionary.text("Description (when to use this skill):").ask()
    if not description:
        return
    trigger = questionary.text("Trigger keywords (comma-separated):").ask() or ""
    instructions = questionary.text("Instructions (markdown):").ask()
    if not instructions:
        return

    path = save_skill(name, description, trigger, instructions)
    click.echo(f"Skill '{name}' created at {path}")

@skill.command("delete")
@click.argument("name")
def skill_delete(name):
    """Delete a skill by name."""
    from openlama.core.skills import delete_skill
    if delete_skill(name):
        click.echo(f"Skill '{name}' deleted.")
    else:
        click.echo(f"Skill '{name}' not found.")


# ──�� MCP commands ─���───────────────────────────

@main.group()
def mcp():
    """Manage MCP (Model Context Protocol) servers."""
    pass

@mcp.command("list")
def mcp_list():
    """List all configured MCP servers."""
    from rich.console import Console
    from rich.table import Table
    from openlama.core.mcp_client import list_server_configs

    console = Console()
    configs = list_server_configs()
    if not configs:
        console.print("[dim]No MCP servers configured. Add one with 'openlama mcp add'.[/dim]")
        return

    table = Table(title="MCP Servers", show_lines=True)
    table.add_column("Name", style="cyan")
    table.add_column("Command", style="green")
    table.add_column("Args", style="yellow")

    for name, conf in configs.items():
        table.add_row(name, conf.get("command", ""), " ".join(conf.get("args", [])))
    console.print(table)

@mcp.command("add")
@click.argument("name")
@click.argument("command")
@click.argument("args", nargs=-1)
@click.option("--env", "-e", multiple=True, help="Environment variables (KEY=VALUE)")
def mcp_add(name, command, args, env):
    """Add an MCP server.

    \b
    Example:
      openlama mcp add github npx -y @github/github-mcp
      openlama mcp add fs npx -y @modelcontextprotocol/server-filesystem /home
    """
    from openlama.core.mcp_client import add_server_config

    env_dict = {}
    for e in env:
        if "=" in e:
            k, _, v = e.partition("=")
            env_dict[k] = v

    add_server_config(name, command, list(args), env_dict if env_dict else None)
    click.echo(f"MCP server '{name}' added. It will start with the bot.")

@mcp.command("remove")
@click.argument("name")
def mcp_remove(name):
    """Remove an MCP server by name."""
    from openlama.core.mcp_client import remove_server_config
    if remove_server_config(name):
        click.echo(f"MCP server '{name}' removed.")
    else:
        click.echo(f"MCP server '{name}' not found.")


if __name__ == "__main__":
    main()
