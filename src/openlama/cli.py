"""openlama CLI — main entry point."""
import click
from openlama import __version__

@click.group()
@click.version_option(version=__version__, prog_name="openlama")
def main():
    """openlama — Personal AI agent bot powered by Ollama.

    \b
    Quick start:
      openlama setup          Set up Ollama, models, and Telegram
      openlama start          Run the Telegram bot
      openlama chat           Chat in the terminal (shared context)

    \b
    Management:
      openlama doctor         Diagnose and fix issues
      openlama update         Update openlama and Ollama
      openlama status         Show connection and process status
      openlama config list    View all settings
    """
    pass

# ─── Core commands ───────────────────────��─────

@main.command()
def setup():
    """Run the interactive setup wizard (Ollama, models, Telegram, password)."""
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

    if daemon:
        from openlama.daemon import start_daemon
        start_daemon()
    else:
        from openlama.channels.telegram.bot import main as run_telegram
        run_telegram()

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
    """Interactive terminal chat. Shares context with Telegram."""
    import asyncio
    from openlama.channels.cli.chat import run_chat
    asyncio.run(run_chat())

@main.command()
def status():
    """Show process, Ollama, ComfyUI, MCP, and skills status."""
    import asyncio
    from rich.console import Console
    from rich.panel import Panel
    from openlama.daemon import get_daemon_status
    from openlama.config import get_config

    console = Console()

    # Process status
    pid_info = get_daemon_status()

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
    lines.append(f"")
    ver_str = f" v{ver_info.get('current', '?')}" if ver_info else ""
    lines.append(f"  Ollama:   {'🟢 Connected' + ver_str if alive else '🔴 Not reachable'}")
    lines.append(f"  ├─ URL:   {ollama_url}")
    if alive:
        lines.append(f"  ├─ Model: {default_model or '(none)'}")
        lines.append(f"  ���─ Models: {len(models)} available")
        if ver_info.get("update_available"):
            lines.append(f"  ⚠  Update: v{ver_info['latest']} available")
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

    console.print(Panel("\n".join(lines), title="openlama Status", border_style="blue"))


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
            uv_bin = shutil.which("uv")
            if uv_bin:
                result = subprocess.run(
                    [uv_bin, "tool", "upgrade", "openlama"],
                    capture_output=True, text=True,
                )
                if result.returncode == 0:
                    ver_out = subprocess.run(
                        [uv_bin, "tool", "run", "openlama", "--version"],
                        capture_output=True, text=True,
                    )
                    new_ver = ver_out.stdout.strip().split()[-1] if ver_out.returncode == 0 else "?"
                    if new_ver != old_ver:
                        console.print(f"  [green]Updated: v{old_ver} -> v{new_ver}[/green]")
                    else:
                        console.print(f"  Already up to date (v{old_ver})")
                else:
                    subprocess.run(
                        [sys.executable, "-m", "pip", "install", "--upgrade", "openlama"],
                        capture_output=True,
                    )
                    console.print(f"  Updated via pip (was v{old_ver})")
            else:
                subprocess.run(
                    [sys.executable, "-m", "pip", "install", "--upgrade", "openlama"],
                    capture_output=True,
                )
                console.print(f"  Updated via pip (was v{old_ver})")
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
                if sys.platform == "darwin" and shutil.which("brew"):
                    subprocess.run(["brew", "upgrade", "ollama"], capture_output=True, text=True)
                elif sys.platform == "linux":
                    subprocess.run(
                        ["sh", "-c", "curl -fsSL https://ollama.com/install.sh | sh"],
                        capture_output=True, text=True,
                    )
                elif sys.platform == "win32":
                    console.print("  Windows: download from https://ollama.com/download/windows")
                    console.print()
                    return
                else:
                    console.print(f"  Unsupported platform: {sys.platform}")
                    console.print()
                    return

                info2 = asyncio.run(_check())
                console.print(f"  [green]Updated: v{current} -> v{info2.get('current', '?')}[/green]")
            except Exception as e:
                console.print(f"  [red]Failed: {e}[/red]")

    # Restart daemon if running
    from openlama.daemon import _read_pid
    pid = _read_pid()
    if pid and not ollama_only:
        console.print("  [bold]Restarting daemon...[/bold]")
        from openlama.daemon import restart_daemon
        restart_daemon()
        console.print("  [green]Daemon restarted.[/green]")

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

@config.command("reset")
@click.confirmation_option(prompt="Reset all settings?")
def config_reset():
    """Reset all settings to defaults."""
    click.echo("Settings reset. Run 'openlama setup' to reconfigure.")


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

    console.print("\n[bold]openlama doctor[/bold] — running diagnostics...\n")

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
