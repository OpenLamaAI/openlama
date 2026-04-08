"""CLI chat channel — Rich TUI sharing context with Telegram."""
from __future__ import annotations

import asyncio
import io
import os
import sys

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule
from rich.text import Text
from rich.table import Table

from openlama.channels.base import Channel
from openlama.core.types import ChatRequest, ChatResponse
from openlama.core.agent import chat
from openlama.core.commands import COMMANDS, get_commands_by_category, format_help_text
from openlama.config import get_config
from openlama.database import (
    init_db, get_user, get_allowed_ids, get_model_settings,
    load_context, clear_context, update_user, db_conn,
)
from openlama.tools import init_tools
from openlama.ollama_client import ensure_ollama_running, list_models
from openlama.logger import get_logger

logger = get_logger("cli.chat")

console = Console()

CLI_FALLBACK_UID = 1


# ─── Helpers ─────────────────────────────

def _resolve_user_id() -> int:
    try:
        allowed = get_allowed_ids()
        if allowed:
            return allowed[0]
    except Exception:
        pass
    return CLI_FALLBACK_UID


def _get_status_line(uid: int) -> str:
    from openlama.core.context import _estimate_messages_tokens
    from openlama.core.prompt_builder import build_full_system_prompt

    user = get_user(uid)
    model = user.selected_model or "none"
    ctx = load_context(uid)
    settings = get_model_settings(uid, model) if model != "none" else None
    num_ctx = settings.num_ctx if settings else 8192

    sp = build_full_system_prompt()
    est = _estimate_messages_tokens(sp, ctx)
    pct = min(est / num_ctx * 100, 100) if num_ctx > 0 else 0

    token = get_config("telegram_bot_token")
    bot_name = ""
    if token:
        try:
            import httpx
            r = httpx.get(f"https://api.telegram.org/bot{token}/getMe", timeout=3)
            if r.status_code == 200:
                bot_name = r.json().get("result", {}).get("username", "")
        except Exception:
            pass

    parts = []
    parts.append(f"model: {model}")
    parts.append(f"ctx: {pct:.0f}% ({len(ctx)} turns)")
    if bot_name:
        parts.append(f"telegram: @{bot_name}")

    return " | ".join(parts)


# ─── Model selection ─────────────────────────────

async def _ensure_model(uid: int) -> bool:
    user = get_user(uid)
    if user.selected_model:
        return True

    default = get_config("default_model")
    if default:
        with db_conn() as conn:
            conn.execute("UPDATE users SET selected_model=? WHERE telegram_id=?", (default, uid))
        return True

    return await _select_model(uid)


async def _select_model(uid: int) -> bool:
    try:
        models = await list_models()
    except Exception:
        models = []

    if not models:
        console.print("  [red]No models available.[/red] Run 'ollama pull <model>' first.")
        return False

    console.print()
    for i, m in enumerate(models, 1):
        console.print(f"  [cyan]{i}[/cyan]. {m}")

    try:
        choice = Prompt.ask(f"\n  Select model [1-{len(models)}]")
        idx = int(choice.strip()) - 1
        if 0 <= idx < len(models):
            selected = models[idx]
            with db_conn() as conn:
                conn.execute("UPDATE users SET selected_model=? WHERE telegram_id=?", (selected, uid))
            console.print(f"  Model: [cyan]{selected}[/cyan]\n")
            return True
    except (ValueError, EOFError):
        pass

    return False


# ─── Profile setup ─────────────────────────────

def _ask_until_valid(panel_title: str, panel_body: str, min_chars: int = 10) -> str:
    console.print(Panel(panel_body, title=panel_title, border_style="blue", padding=(1, 2)))

    while True:
        try:
            text = Prompt.ask("[bold cyan]>[/bold cyan]")
        except (EOFError, KeyboardInterrupt):
            return ""
        text = text.strip()
        if not text:
            return ""
        if len(text) >= min_chars:
            return text
        console.print(f"  [yellow]Too short ({len(text)} chars). Min {min_chars} characters.[/yellow]")


async def _run_profile_setup(uid: int):
    from openlama.core.agent import PROFILE_QUESTIONS
    from openlama.core.prompt_builder import save_prompt_file, is_profile_setup_done, _has_real_content, _prompts_dir
    from openlama.core.onboarding import (
        LANGUAGES, check_model_available, refine_users_prompt, refine_soul_prompt,
    )

    console.print()
    console.print(Rule("[bold]Profile Setup[/bold]", style="blue"))
    console.print()

    d = _prompts_dir()
    language = "English"

    # Step 1: Language
    if not _has_real_content(d / "USERS.md"):
        console.print(Panel(
            "Select your primary language.",
            title="[bold]Step 1/3[/bold] — Language",
            border_style="blue", padding=(1, 2),
        ))
        for i, (code, name) in enumerate(LANGUAGES, 1):
            console.print(f"  [cyan]{i:2d}[/cyan]. {name} ({code})")
        console.print(f"  [dim]Or type a language name[/dim]")

        try:
            lang_input = Prompt.ask("[bold cyan]>[/bold cyan]", default="1")
        except (EOFError, KeyboardInterrupt):
            return

        lang_input = lang_input.strip()
        try:
            idx = int(lang_input) - 1
            if 0 <= idx < len(LANGUAGES):
                language = LANGUAGES[idx][1]
            else:
                language = "English"
        except ValueError:
            language = lang_input if lang_input else "English"
        console.print(f"  [green]Language: {language}[/green]\n")

    # Step 2: USERS.md
    if not _has_real_content(d / "USERS.md"):
        raw = _ask_until_valid(
            "[bold]Step 2/3[/bold] — About You",
            PROFILE_QUESTIONS["users"] + f"\n\n(Language: {language})",
        )
        if raw:
            save_prompt_file("USERS.md", f"# User Profile\n\nLanguage: {language}\n\n{raw}")
            console.print("  [green]Saved.[/green]\n")
        else:
            console.print("  [dim]Skipped.[/dim]\n")
    else:
        console.print("  [dim]Step 2/3 — Already set.[/dim]\n")

    # Step 3: SOUL.md
    if not _has_real_content(d / "SOUL.md"):
        raw = _ask_until_valid(
            "[bold]Step 3/3[/bold] — Agent Identity",
            PROFILE_QUESTIONS["soul"],
        )
        if raw:
            save_prompt_file("SOUL.md", f"# Agent Identity\n\n{raw}")
            console.print("  [green]Saved.[/green]\n")
        else:
            console.print("  [dim]Skipped.[/dim]\n")
    else:
        console.print("  [dim]Step 3/3 — Already set.[/dim]\n")

    if not is_profile_setup_done():
        console.print("  [yellow]Incomplete. Redo with /profile[/yellow]\n")
        return

    # AI refinement
    ok, model, _ = await check_model_available()
    if not ok or not model:
        save_prompt_file("USERS.md", "")
        save_prompt_file("SOUL.md", "")
        console.print("  [yellow]No model available. Run 'openlama setup' to install a model.[/yellow]\n")
        return

    console.print("  [bold]Refining prompts with AI...[/bold]")
    with console.status("[blue]Refining user profile...", spinner="dots"):
        users_raw = (d / "USERS.md").read_text(encoding="utf-8") if (d / "USERS.md").exists() else ""
        refined_users = await refine_users_prompt(model, users_raw, language)
        if refined_users:
            save_prompt_file("USERS.md", refined_users)

    with console.status("[blue]Refining agent identity...", spinner="dots"):
        soul_raw = (d / "SOUL.md").read_text(encoding="utf-8") if (d / "SOUL.md").exists() else ""
        refined_soul = await refine_soul_prompt(model, soul_raw)
        if refined_soul:
            save_prompt_file("SOUL.md", refined_soul)

    console.print("  [green bold]Profile setup complete.[/green bold]\n")
    if refined_users:
        console.print(Panel(refined_users, title="USERS.md", border_style="green", padding=(0, 1)))
    if refined_soul:
        console.print(Panel(refined_soul, title="SOUL.md", border_style="green", padding=(0, 1)))
    console.print()


# ─── Command handlers ─────────────────────────────

async def _cmd_help(uid: int, args: str):
    help_text = format_help_text(exclude=["login", "logout", "setpassword"])
    console.print(help_text)
    console.print()


async def _cmd_clear(uid: int, args: str):
    clear_context(uid)
    console.print("  [green]Context cleared.[/green]\n")


async def _cmd_status(uid: int, args: str):
    from openlama.core.context import _estimate_messages_tokens, build_context_bar
    from openlama.core.prompt_builder import build_full_system_prompt
    from openlama.database import now_ts

    user = get_user(uid)
    ctx = load_context(uid)
    settings = get_model_settings(uid, user.selected_model) if user.selected_model else None

    lines = []
    lines.append(f"  [bold]Session Status[/bold]\n")
    auth_left = max(0, user.auth_until - now_ts())
    lines.append(f"  Auth:    {'Valid' if auth_left else 'Expired'} ({auth_left}s)")
    lines.append(f"  Model:   {user.selected_model or '(none)'}")
    lines.append(f"  Think:   {'ON' if user.think_mode else 'OFF'}")

    if settings:
        lines.append(f"  Temp:    {settings.temperature}  |  top_p: {settings.top_p}")
        lines.append(f"  num_ctx: {settings.num_ctx}  |  num_predict: {settings.num_predict}")

    sp = build_full_system_prompt()
    est = _estimate_messages_tokens(sp, ctx)
    if settings:
        bar = build_context_bar(est, settings.num_ctx, len(ctx))
        lines.append(f"\n  {bar}")

    console.print("\n".join(lines))
    console.print()


async def _cmd_model(uid: int, args: str):
    if args:
        # Set model directly
        models = await list_models()
        if args in models:
            with db_conn() as conn:
                conn.execute("UPDATE users SET selected_model=? WHERE telegram_id=?", (args, uid))
            console.print(f"  Model changed to: [cyan]{args}[/cyan]\n")
        else:
            console.print(f"  [red]Model '{args}' not found.[/red]\n")
    else:
        user = get_user(uid)
        console.print(f"  Current model: [cyan]{user.selected_model or '(none)'}[/cyan]")
        await _select_model(uid)


async def _cmd_models(uid: int, args: str):
    try:
        models = await list_models()
    except Exception:
        models = []

    if not models:
        console.print("  [red]No models available.[/red]\n")
        return

    user = get_user(uid)
    table = Table(title="Available Models", show_lines=False, padding=(0, 2))
    table.add_column("#", style="dim", width=3)
    table.add_column("Model", style="cyan")
    table.add_column("", width=3)

    for i, m in enumerate(models, 1):
        marker = "[green]*[/green]" if m == user.selected_model else ""
        table.add_row(str(i), m, marker)

    console.print(table)
    console.print(f"  [dim]* = current model. Use /model <name> to switch.[/dim]\n")


async def _cmd_pull(uid: int, args: str):
    if not args:
        console.print("  Usage: /pull <model_name>")
        console.print("  Example: /pull gemma3:4b\n")
        return

    from openlama.onboarding import _pull_model_with_progress
    console.print(f"  Pulling {args}...\n")
    _pull_model_with_progress(args)
    console.print()


async def _cmd_settings(uid: int, args: str):
    user = get_user(uid)
    if not user.selected_model:
        console.print("  [yellow]No model selected.[/yellow]\n")
        return

    ms = get_model_settings(uid, user.selected_model)

    table = Table(title=f"Settings ({user.selected_model})", show_lines=True)
    table.add_column("Parameter", style="cyan")
    table.add_column("Value", style="green")
    table.add_column("Description", style="dim")

    table.add_row("temperature", str(ms.temperature), "Creativity (0.0 - 2.0)")
    table.add_row("top_p", str(ms.top_p), "Nucleus sampling (0.0 - 1.0)")
    table.add_row("top_k", str(ms.top_k), "Top-K sampling")
    table.add_row("num_ctx", str(ms.num_ctx), "Context window size")
    table.add_row("num_predict", str(ms.num_predict), "Max output tokens")
    table.add_row("keep_alive", str(ms.keep_alive), "Model keep-alive time")

    console.print(table)
    console.print(f"  [dim]Use /set <param> <value> to change. E.g., /set temperature 0.8[/dim]\n")


async def _cmd_set(uid: int, args: str):
    """Set a model parameter. Usage: /set <param> <value>"""
    parts = args.split(None, 1)
    if len(parts) < 2:
        console.print("  Usage: /set <param> <value>")
        console.print("  Example: /set temperature 0.8\n")
        return

    param, value = parts[0], parts[1]
    user = get_user(uid)
    if not user.selected_model:
        console.print("  [yellow]No model selected.[/yellow]\n")
        return

    valid_params = {"temperature", "top_p", "top_k", "num_ctx", "num_predict", "keep_alive"}
    if param not in valid_params:
        console.print(f"  [red]Unknown parameter: {param}[/red]")
        console.print(f"  Valid: {', '.join(sorted(valid_params))}\n")
        return

    from openlama.database import set_model_setting
    try:
        if param in ("top_k", "num_ctx", "num_predict"):
            val = int(value)
        elif param == "keep_alive":
            val = value
        else:
            val = float(value)
        set_model_setting(uid, user.selected_model, param, val)
        console.print(f"  [green]{param} = {val}[/green]\n")
    except ValueError:
        console.print(f"  [red]Invalid value: {value}[/red]\n")


async def _cmd_think(uid: int, args: str):
    user = get_user(uid)
    new_val = 0 if user.think_mode else 1
    update_user(uid, think_mode=new_val)
    console.print(f"  Think mode: [bold]{'ON' if new_val else 'OFF'}[/bold]\n")


async def _cmd_systemprompt(uid: int, args: str):
    from openlama.core.prompt_builder import _prompts_dir, save_prompt_file
    import subprocess
    import shutil

    d = _prompts_dir()
    files = ["SOUL.md", "USERS.md", "MEMORY.md", "SYSTEM.md"]

    if args and args in files:
        # Direct edit: /systemprompt SOUL.md
        _edit_prompt_file(d, args)
        return

    if args:
        # Try fuzzy match
        match = [f for f in files if args.lower() in f.lower()]
        if len(match) == 1:
            _edit_prompt_file(d, match[0])
            return

    # Show file list
    table = Table(title="Prompt Files", show_lines=False, padding=(0, 2))
    table.add_column("#", style="dim", width=3)
    table.add_column("File", style="cyan")
    table.add_column("Size", style="green", justify="right")
    table.add_column("Preview", style="dim", max_width=40)

    for i, name in enumerate(files, 1):
        p = d / name
        if p.exists():
            content = p.read_text(encoding="utf-8")
            size = f"{len(content)} chars"
            preview = content.replace("\n", " ")[:40]
        else:
            size = "empty"
            preview = "(not created)"
        table.add_row(str(i), name, size, preview)

    console.print(table)
    console.print()

    try:
        choice = Prompt.ask("  Select file to edit [1-4], or Enter to cancel")
    except (EOFError, KeyboardInterrupt):
        console.print()
        return

    choice = choice.strip()
    if not choice:
        return

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(files):
            _edit_prompt_file(d, files[idx])
    except ValueError:
        if choice in files:
            _edit_prompt_file(d, choice)


def _edit_prompt_file(prompts_dir, filename: str):
    """Open a prompt file in $EDITOR or inline editing."""
    import subprocess
    import shutil
    from openlama.core.prompt_builder import save_prompt_file

    p = prompts_dir / filename
    content = p.read_text(encoding="utf-8") if p.exists() else ""

    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")

    # Try to find an editor
    if not editor:
        for e in ["nano", "vim", "vi"]:
            if shutil.which(e):
                editor = e
                break

    if editor:
        console.print(f"  Opening {filename} in [cyan]{editor}[/cyan]...")
        # Ensure file exists
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_text("", encoding="utf-8")

        result = subprocess.run([editor, str(p)])
        if result.returncode == 0:
            new_content = p.read_text(encoding="utf-8")
            if new_content != content:
                console.print(f"  [green]{filename} saved ({len(new_content)} chars).[/green]\n")
            else:
                console.print(f"  [dim]No changes.[/dim]\n")
        else:
            console.print(f"  [red]Editor exited with error.[/red]\n")
    else:
        # Inline editing fallback
        console.print(Panel(
            content[:2000] + ("..." if len(content) > 2000 else ""),
            title=filename, border_style="blue", padding=(0, 1),
        ))
        console.print(f"\n  [dim]No editor found ($EDITOR not set).[/dim]")
        console.print(f"  [dim]Paste new content below. Send empty line to finish, Ctrl+C to cancel.[/dim]\n")

        lines = []
        try:
            while True:
                line = input()
                if line == "":
                    break
                lines.append(line)
        except (EOFError, KeyboardInterrupt):
            console.print("\n  [yellow]Cancelled.[/yellow]\n")
            return

        if lines:
            new_content = "\n".join(lines)
            save_prompt_file(filename, new_content)
            console.print(f"  [green]{filename} saved ({len(new_content)} chars).[/green]\n")
        else:
            console.print(f"  [dim]No changes.[/dim]\n")


async def _cmd_export(uid: int, args: str):
    items = load_context(uid)
    if not items:
        console.print("  [dim]No conversation history.[/dim]\n")
        return

    lines = []
    for i, item in enumerate(items, 1):
        lines.append(f"--- Turn {i} ---")
        lines.append(f"User: {item.get('u', '')}")
        lines.append(f"Assistant: {item.get('a', '')}")
        lines.append("")

    from openlama.config import DATA_DIR
    export_path = DATA_DIR / "conversation_export.txt"
    export_path.write_text("\n".join(lines), encoding="utf-8")
    console.print(f"  Exported {len(items)} turns to: [cyan]{export_path}[/cyan]\n")


async def _cmd_ollama(uid: int, args: str):
    from openlama.ollama_client import ollama_alive, check_ollama_update, get_running_models

    alive = await ollama_alive()
    ver_info = await check_ollama_update() if alive else {}
    running = await get_running_models() if alive else []

    lines = []
    lines.append(f"  [bold]Ollama Status[/bold]\n")
    lines.append(f"  Server:  {'Connected' if alive else 'Not reachable'}")
    if ver_info:
        lines.append(f"  Version: v{ver_info.get('current', '?')}")
        if ver_info.get("update_available"):
            lines.append(f"  Update:  v{ver_info['latest']} available")

    if running:
        lines.append(f"\n  Running models:")
        for m in running:
            name = m.get("name", "?")
            size = m.get("size", 0)
            lines.append(f"    {name} ({size / 1e9:.1f} GB)")

    console.print("\n".join(lines))
    console.print()


async def _cmd_skills(uid: int, args: str):
    from openlama.core.skills import list_skills
    skills = list_skills()
    if not skills:
        console.print("  [dim]No skills installed.[/dim]\n")
        return

    table = Table(title="Skills", show_lines=False, padding=(0, 2))
    table.add_column("Name", style="cyan")
    table.add_column("Description")
    table.add_column("Trigger", style="yellow")
    for s in skills:
        table.add_row(s["name"], s.get("description", ""), s.get("trigger", ""))
    console.print(table)
    console.print()


async def _cmd_mcp(uid: int, args: str):
    from openlama.core.mcp_client import list_server_configs, get_all_servers, get_all_mcp_tools
    configs = list_server_configs()
    running = get_all_servers()
    tools = get_all_mcp_tools()

    if not configs:
        console.print("  [dim]No MCP servers configured.[/dim]\n")
        return

    table = Table(title="MCP Servers", show_lines=False, padding=(0, 2))
    table.add_column("Name", style="cyan")
    table.add_column("Status")
    table.add_column("Command", style="dim")
    for name, conf in configs.items():
        status = "[green]Running[/green]" if name in running else "[red]Stopped[/red]"
        table.add_row(name, status, conf.get("command", ""))
    console.print(table)

    if tools:
        console.print(f"\n  [dim]{len(tools)} tool(s) available from MCP servers.[/dim]")
    console.print()


async def _cmd_cron(uid: int, args: str):
    """Show or manage cron jobs."""
    from openlama.database import list_cron_jobs, delete_cron_job
    import datetime

    parts = args.split(None, 1) if args else []
    sub = parts[0].lower() if parts else ""

    if sub == "delete" and len(parts) > 1:
        try:
            job_id = int(parts[1])
            if delete_cron_job(job_id):
                console.print(f"  [green]Task #{job_id} deleted.[/green]\n")
            else:
                console.print(f"  [red]Task #{job_id} not found.[/red]\n")
        except ValueError:
            console.print(f"  [red]Invalid ID.[/red]\n")
        return

    jobs = list_cron_jobs()
    if not jobs:
        console.print("  [dim]No scheduled tasks. Ask the AI to create one.[/dim]\n")
        return

    table = Table(title="Scheduled Tasks", show_lines=True)
    table.add_column("ID", style="cyan", width=4)
    table.add_column("Status", width=4)
    table.add_column("Schedule", style="yellow")
    table.add_column("Task")
    table.add_column("Next Run", style="dim")

    for j in jobs:
        status = "[green]ON[/green]" if j["enabled"] else "[red]OFF[/red]"
        next_ts = j.get("next_run", 0)
        next_str = datetime.datetime.fromtimestamp(next_ts).strftime("%m-%d %H:%M") if next_ts > 0 else "—"
        table.add_row(str(j["id"]), status, j["cron_expr"], j["task"][:40], next_str)

    console.print(table)
    console.print(f"  [dim]/cron delete <id> to remove a task.[/dim]\n")


async def _cmd_profile(uid: int, args: str):
    await _run_profile_setup(uid)


# Command dispatch table
CMD_HANDLERS = {
    "help": _cmd_help,
    "clear": _cmd_clear,
    "status": _cmd_status,
    "model": _cmd_model,
    "models": _cmd_models,
    "pull": _cmd_pull,
    "settings": _cmd_settings,
    "set": _cmd_set,
    "think": _cmd_think,
    "systemprompt": _cmd_systemprompt,
    "export": _cmd_export,
    "ollama": _cmd_ollama,
    "skills": _cmd_skills,
    "mcp": _cmd_mcp,
    "cron": _cmd_cron,
    "profile": _cmd_profile,
}


# ─── Slash command autocomplete ─────────────────────────────

def _show_command_list(prefix: str = ""):
    """Show matching commands for autocomplete."""
    groups = get_commands_by_category()
    category_labels = {
        "chat": "Chat", "model": "Model", "settings": "Settings",
        "system": "System", "admin": "Account",
    }
    exclude = {"login", "logout", "setpassword"}

    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column(style="cyan bold", min_width=16)
    table.add_column(style="dim")

    for cat in ["chat", "model", "settings", "system"]:
        cmds = groups.get(cat, [])
        cmds = [c for c in cmds if c["name"] not in exclude]
        if prefix:
            cmds = [c for c in cmds if c["name"].startswith(prefix)]
        if not cmds:
            continue
        table.add_row(f"[bold]{category_labels.get(cat, cat)}[/bold]", "")
        for c in cmds:
            table.add_row(f"  /{c['name']}", c["description"])

    if table.row_count > 0:
        console.print(table)
        console.print()


# ─── Main chat loop ─────────────────────────────

async def run_chat():
    """Main CLI chat loop."""
    init_db()
    init_tools()

    ok, msg = await ensure_ollama_running()
    if not ok:
        console.print(f"\n  [red]Ollama not reachable:[/red] {msg}")
        console.print("  Run [cyan]openlama doctor fix[/cyan] to resolve.\n")
        return

    uid = _resolve_user_id()

    if not await _ensure_model(uid):
        return

    from openlama.core.prompt_builder import is_profile_setup_done
    if not is_profile_setup_done():
        await _run_profile_setup(uid)

    # Header
    user = get_user(uid)
    status = _get_status_line(uid)

    console.print()
    console.print(Rule("[bold]openlama[/bold]", style="blue"))
    console.print(f"  [dim]{status}[/dim]")
    console.print(f"  [dim]Type / for commands, /quit to exit.[/dim]")
    console.print()

    while True:
        try:
            user_input = Prompt.ask("[bold green]You[/bold green]")
        except (EOFError, KeyboardInterrupt):
            console.print("\n  [dim]Goodbye.[/dim]\n")
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        # Quit
        if user_input.lower() in ("/quit", "/exit", "/q"):
            console.print("  [dim]Goodbye.[/dim]\n")
            break

        # Slash command
        if user_input.startswith("/"):
            parts = user_input[1:].split(None, 1)
            cmd_name = parts[0].lower() if parts else ""
            cmd_args = parts[1] if len(parts) > 1 else ""

            # Just "/" — show all commands
            if not cmd_name:
                _show_command_list()
                continue

            # Partial match — show filtered list
            handler = CMD_HANDLERS.get(cmd_name)
            if not handler:
                # Try prefix match
                matches = [n for n in CMD_HANDLERS if n.startswith(cmd_name)]
                if len(matches) == 1:
                    handler = CMD_HANDLERS[matches[0]]
                    cmd_name = matches[0]
                elif matches:
                    _show_command_list(cmd_name)
                    continue
                else:
                    console.print(f"  [red]Unknown command: /{cmd_name}[/red]")
                    console.print(f"  [dim]Type / to see available commands.[/dim]\n")
                    continue

            await handler(uid, cmd_args)
            continue

        # Regular chat message
        request = ChatRequest(user_id=uid, text=user_input, channel="cli")

        try:
            with console.status("[bold blue]Thinking...", spinner="dots"):
                response: ChatResponse = await chat(request)

            if response.content:
                console.print()
                try:
                    md = Markdown(response.content)
                    console.print(Panel(md, title="[bold blue]AI[/bold blue]", border_style="blue", padding=(1, 2)))
                except Exception:
                    console.print(f"  [blue]AI>[/blue] {response.content}")

            if response.images:
                for img_path in response.images:
                    console.print(f"  [dim]Image: {img_path}[/dim]")

            if response.context_bar:
                console.print(f"  [dim]{response.context_bar}[/dim]")
            console.print()

        except Exception as e:
            console.print(f"\n  [red]Error: {e}[/red]\n")
            logger.error("CLI chat error: %s", e, exc_info=True)


class CLIChannel(Channel):
    async def start(self):
        await run_chat()

    async def stop(self):
        pass
