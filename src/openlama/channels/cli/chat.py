"""CLI chat channel — Rich TUI with async message queue and dynamic command search."""
from __future__ import annotations

import asyncio
import os
import sys

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text
from rich.table import Table

import itertools
from io import StringIO

from prompt_toolkit import PromptSession, print_formatted_text
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.history import FileHistory
from prompt_toolkit.formatted_text import HTML, ANSI
from prompt_toolkit.application import run_in_terminal, in_terminal
from prompt_toolkit.key_binding import KeyBindings

from openlama.channels.base import Channel
from openlama.core.types import ChatRequest, ChatResponse
from openlama.core.agent import chat
from openlama.core.commands import COMMANDS, get_commands_by_category, format_help_text
from openlama.config import get_config, DATA_DIR
from openlama.database import (
    init_db, get_user, get_allowed_ids, get_model_settings,
    load_context, clear_context, save_context, update_user,
)
from openlama.tools import init_tools
from openlama.ollama_client import (
    ensure_ollama_running, list_models, delete_model, unload_model,
    get_model_capabilities, summarize_context,
)
from openlama.logger import get_logger

logger = get_logger("cli.chat")

console = Console(force_terminal=True)

CLI_FALLBACK_UID = 1

# Cached values
_bot_username_cache: str | None = None

# Shared prompt session — set during run_chat(), used by sub-commands
_session: PromptSession | None = None

# Sentinel to signal quit
_QUIT = object()

# ─── Safe Rich output via prompt_toolkit ─────────────────────────────

# Pre-render console: renders Rich objects to ANSI strings in memory
_render_console = Console(file=StringIO(), force_terminal=True, color_system="truecolor")

# Bottom toolbar spinner state
_spinner_frames = itertools.cycle("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏")
_status = {"text": ""}


def _toolbar():
    """Bottom toolbar — shows spinner when worker is processing."""
    if _status["text"]:
        return HTML(f" {next(_spinner_frames)} <b>{_status['text']}</b>")
    return HTML(" <ansigray>Type / for commands, /quit to exit</ansigray>")


async def aprint(renderable="", **kwargs):
    """Print a Rich renderable safely.

    When the prompt is active, pre-renders Rich to ANSI string, then
    uses run_in_terminal() to suspend the prompt, print, and restore.
    Falls back to console.print() during setup (before the main loop).
    """
    app = _session.app if _session and hasattr(_session, "app") and _session.app else None
    if app and app._is_running:
        from prompt_toolkit.application.current import set_app
        _render_console.width = console.width or 80
        _render_console.file = StringIO()
        _render_console.print(renderable, **kwargs)
        ansi_str = _render_console.file.getvalue()
        with set_app(app):
            await run_in_terminal(lambda: print_formatted_text(ANSI(ansi_str), end=""))
    else:
        console.print(renderable, **kwargs)


# ─── SlashCompleter ─────────────────────────────

class SlashCompleter(Completer):
    """Dynamic slash command completer.

    Activates only when input starts with "/". Filters commands in real-time
    as the user types, showing description alongside each match.
    """

    _EXCLUDE = {"login", "logout", "setpassword"}

    def __init__(self):
        self._commands: list[dict] = []
        self._refresh()

    def _refresh(self):
        self._commands = [
            c for c in COMMANDS if c["name"] not in self._EXCLUDE
        ]

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor

        # Only activate when input starts with "/"
        if not text.startswith("/"):
            return

        # Strip the leading "/" to get the prefix
        prefix = text[1:].lower()

        for cmd in self._commands:
            name = cmd["name"]
            if name.startswith(prefix):
                # Yield completion: replace everything after "/"
                yield Completion(
                    text=name,
                    start_position=-len(prefix),
                    display=f"/{name}",
                    display_meta=cmd.get("description", ""),
                )


# ─── Async prompt helper ─────────────────────────────

# Worker prompt session — used inside in_terminal() for sub-command input
_worker_session: PromptSession | None = None


async def _async_prompt(message: str = "", **kwargs) -> str:
    """Prompt for sub-command input.

    When the main prompt is active, suspends it via app.run_in_terminal()
    and uses a separate worker session. Otherwise uses synchronous input().
    """
    global _worker_session
    app = _session.app if _session and hasattr(_session, "app") and _session.app else None
    if app and app._is_running:
        from prompt_toolkit.application.current import set_app
        if _worker_session is None:
            _worker_session = PromptSession()
        with set_app(app):
            async with in_terminal():
                return await _worker_session.prompt_async(message, **kwargs)
    # Fallback for setup (before the main loop)
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: input(message))


async def _async_prompt_simple(label: str = "> ") -> str:
    """Simple async prompt without completions."""
    return await _async_prompt(label, completer=None)


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

    global _bot_username_cache
    if _bot_username_cache is None:
        token = get_config("telegram_bot_token")
        _bot_username_cache = ""
        if token:
            try:
                import httpx
                r = httpx.get(f"https://api.telegram.org/bot{token}/getMe", timeout=3)
                if r.status_code == 200:
                    _bot_username_cache = r.json().get("result", {}).get("username", "")
            except Exception:
                pass
    bot_name = _bot_username_cache

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
        update_user(uid, selected_model=default)
        return True

    return await _select_model(uid)


async def _select_model(uid: int) -> bool:
    try:
        models = await list_models()
    except Exception:
        models = []

    if not models:
        await aprint("  [red]No models available.[/red] Run 'ollama pull <model>' first.")
        return False

    await aprint()
    for i, m in enumerate(models, 1):
        await aprint(f"  [cyan]{i}[/cyan]. {m}")

    try:
        choice = await _async_prompt_simple(f"\n  Select model [1-{len(models)}]: ")
        idx = int(choice.strip()) - 1
        if 0 <= idx < len(models):
            selected = models[idx]
            update_user(uid, selected_model=selected)
            await aprint(f"  Model: [cyan]{selected}[/cyan]\n")
            return True
    except (ValueError, EOFError, KeyboardInterrupt):
        pass

    return False


# ─── Profile setup ─────────────────────────────

async def _ask_until_valid(panel_title: str, panel_body: str, min_chars: int = 10) -> str:
    await aprint(Panel(panel_body, title=panel_title, border_style="blue", padding=(1, 2)))

    while True:
        try:
            text = await _async_prompt_simple("  > ")
        except (EOFError, KeyboardInterrupt):
            return ""
        text = text.strip()
        if not text:
            return ""
        if len(text) >= min_chars:
            return text
        await aprint(f"  [yellow]Too short ({len(text)} chars). Min {min_chars} characters.[/yellow]")


async def _run_profile_setup(uid: int):
    from openlama.core.agent import PROFILE_QUESTIONS
    from openlama.core.prompt_builder import save_prompt_file, is_profile_setup_done, _has_real_content, _prompts_dir
    from openlama.core.onboarding import (
        LANGUAGES, check_model_available, refine_users_prompt, refine_soul_prompt,
    )

    await aprint()
    await aprint(Rule("[bold]Profile Setup[/bold]", style="blue"))
    await aprint()

    d = _prompts_dir()
    language = "English"

    # Step 1: Language
    if not _has_real_content(d / "USERS.md"):
        await aprint(Panel(
            "Select your primary language.",
            title="[bold]Step 1/3[/bold] — Language",
            border_style="blue", padding=(1, 2),
        ))
        for i, (code, name) in enumerate(LANGUAGES, 1):
            await aprint(f"  [cyan]{i:2d}[/cyan]. {name} ({code})")
        await aprint(f"  [dim]Or type a language name[/dim]")

        try:
            lang_input = await _async_prompt_simple("  > ")
        except (EOFError, KeyboardInterrupt):
            return

        lang_input = lang_input.strip() or "1"
        try:
            idx = int(lang_input) - 1
            if 0 <= idx < len(LANGUAGES):
                language = LANGUAGES[idx][1]
            else:
                language = "English"
        except ValueError:
            language = lang_input if lang_input else "English"
        await aprint(f"  [green]Language: {language}[/green]\n")

    # Step 2: USERS.md
    if not _has_real_content(d / "USERS.md"):
        raw = await _ask_until_valid(
            "[bold]Step 2/3[/bold] — About You",
            PROFILE_QUESTIONS["users"] + f"\n\n(Language: {language})",
        )
        if raw:
            save_prompt_file("USERS.md", f"# User Profile\n\nLanguage: {language}\n\n{raw}")
            await aprint("  [green]Saved.[/green]\n")
        else:
            await aprint("  [dim]Skipped.[/dim]\n")
    else:
        await aprint("  [dim]Step 2/3 — Already set.[/dim]\n")

    # Step 3: SOUL.md
    if not _has_real_content(d / "SOUL.md"):
        raw = await _ask_until_valid(
            "[bold]Step 3/3[/bold] — Agent Identity",
            PROFILE_QUESTIONS["soul"],
        )
        if raw:
            save_prompt_file("SOUL.md", f"# Agent Identity\n\n{raw}")
            await aprint("  [green]Saved.[/green]\n")
        else:
            await aprint("  [dim]Skipped.[/dim]\n")
    else:
        await aprint("  [dim]Step 3/3 — Already set.[/dim]\n")

    if not is_profile_setup_done():
        await aprint("  [yellow]Incomplete. Redo with /profile[/yellow]\n")
        return

    # AI refinement
    ok, model, _ = await check_model_available()
    if not ok or not model:
        save_prompt_file("USERS.md", "")
        save_prompt_file("SOUL.md", "")
        await aprint("  [yellow]No model available. Run 'openlama setup' to install a model.[/yellow]\n")
        return

    await aprint("  [bold]Refining prompts with AI...[/bold]")
    _status["text"] = "Refining user profile..."
    users_raw = (d / "USERS.md").read_text(encoding="utf-8") if (d / "USERS.md").exists() else ""
    refined_users = await refine_users_prompt(model, users_raw, language)
    if refined_users:
        save_prompt_file("USERS.md", refined_users)

    _status["text"] = "Refining agent identity..."
    soul_raw = (d / "SOUL.md").read_text(encoding="utf-8") if (d / "SOUL.md").exists() else ""
    refined_soul = await refine_soul_prompt(model, soul_raw)
    if refined_soul:
        save_prompt_file("SOUL.md", refined_soul)
    _status["text"] = ""

    await aprint("  [green bold]Profile setup complete.[/green bold]\n")
    if refined_users:
        await aprint(Panel(refined_users, title="USERS.md", border_style="green", padding=(0, 1)))
    if refined_soul:
        await aprint(Panel(refined_soul, title="SOUL.md", border_style="green", padding=(0, 1)))
    await aprint()


# ─── Command handlers ─────────────────────────────

async def _cmd_help(uid: int, args: str):
    help_text = format_help_text(exclude=["login", "logout", "setpassword"])
    await aprint(help_text)

async def _cmd_clear(uid: int, args: str):
    # Save current context to daily memory before clearing
    ctx = load_context(uid)
    if ctx:
        from openlama.core.memory import extract_topics, save_daily_entry
        topics = extract_topics(ctx)
        if topics:
            save_daily_entry(topics, source="context_clear")
    clear_context(uid)
    await aprint("  [green]Context cleared.[/green]\n")


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
    if auth_left > 0:
        hours, remainder = divmod(auth_left, 3600)
        mins = remainder // 60
        auth_str = f"Valid ({hours}h {mins}m)"
    else:
        auth_str = "Expired"
    model_name = user.selected_model or "(none)"
    lines.append(f"  Auth:    {auth_str}")
    lines.append(f"  Model:   {model_name}")
    lines.append(f"  Think:   {'ON' if user.think_mode else 'OFF'}")

    if settings:
        lines.append(f"  Temp:    {settings.temperature}  |  top_p: {settings.top_p}")
        lines.append(f"  num_ctx: {settings.num_ctx}  |  num_predict: {settings.num_predict}")

    sp = build_full_system_prompt()
    est = _estimate_messages_tokens(sp, ctx)
    if settings:
        bar = build_context_bar(est, settings.num_ctx, len(ctx))
        lines.append(f"\n  {bar}")

    await aprint("\n".join(lines))
    await aprint()


async def _cmd_model(uid: int, args: str):
    if args:
        models = await list_models()
        if args in models:
            user = get_user(uid)
            old_model = user.selected_model
            update_user(uid, selected_model=args)
            if old_model and old_model != args:
                await unload_model(old_model)
            caps = await get_model_capabilities(args)
            cap_str = f" ({', '.join(caps)})" if caps else ""
            await aprint(f"  Model changed to: [cyan]{args}[/cyan]{cap_str}\n")
        else:
            await aprint(f"  [red]Model '{args}' not found.[/red]\n")
    else:
        user = get_user(uid)
        await aprint(f"  Current model: [cyan]{user.selected_model or '(none)'}[/cyan]")
        await _select_model(uid)


async def _cmd_models(uid: int, args: str):
    try:
        models = await list_models()
    except Exception:
        models = []

    if not models:
        await aprint("  [red]No models available.[/red]\n")
        return

    user = get_user(uid)
    table = Table(title="Available Models", show_lines=False, padding=(0, 2))
    table.add_column("#", style="dim", width=3)
    table.add_column("Model", style="cyan")
    table.add_column("Capabilities", style="dim")
    table.add_column("Active", width=3, justify="center")

    for i, m in enumerate(models, 1):
        marker = "[green]*[/green]" if m == user.selected_model else ""
        caps = await get_model_capabilities(m)
        cap_badges = []
        if "vision" in caps or "image" in caps or "multimodal" in caps:
            cap_badges.append("vision")
        if "tools" in caps:
            cap_badges.append("tools")
        if "thinking" in caps:
            cap_badges.append("think")
        cap_str = ", ".join(cap_badges) if cap_badges else "text"
        table.add_row(str(i), m, cap_str, marker)

    await aprint(table)
    await aprint(f"  [dim]* = current model. Use /model <name> to switch.[/dim]\n")


async def _cmd_pull(uid: int, args: str):
    if not args:
        await aprint("  Usage: /pull <model_name>")
        await aprint("  Example: /pull gemma3:4b\n")
        return

    from openlama.onboarding import _pull_model_with_progress
    await aprint(f"  Pulling {args}...\n")
    _pull_model_with_progress(args)
    await aprint()


async def _cmd_settings(uid: int, args: str):
    user = get_user(uid)
    if not user.selected_model:
        await aprint("  [yellow]No model selected.[/yellow]\n")
        return

    ms = get_model_settings(uid, user.selected_model)

    table = Table(title=f"Settings ({user.selected_model})", show_lines=True)
    table.add_column("Parameter", style="cyan")
    table.add_column("Value", style="green")
    table.add_column("Description", style="dim")

    table.add_row("temperature", str(ms.temperature), "Creativity (0.0 - 2.0)")
    table.add_row("top_p", str(ms.top_p), "Nucleus sampling (0.0 - 1.0)")
    table.add_row("top_k", str(ms.top_k), "Top-K sampling (1 - 200)")
    table.add_row("num_ctx", str(ms.num_ctx), "Context window size (1024 - 262144)")
    table.add_row("num_predict", str(ms.num_predict), "Max output tokens (128 - 16384)")
    table.add_row("repeat_penalty", str(getattr(ms, "repeat_penalty", 1.1)), "Repetition penalty (0.5 - 2.0)")
    table.add_row("seed", str(getattr(ms, "seed", 0)), "Random seed (0 = random)")
    table.add_row("keep_alive", str(ms.keep_alive), "Model keep-alive time")

    await aprint(table)
    await aprint(f"  [dim]Use /set <param> <value> to change. E.g., /set temperature 0.8[/dim]\n")


async def _cmd_set(uid: int, args: str):
    """Set a model parameter. Usage: /set <param> <value>"""
    parts = args.split(None, 1)
    if len(parts) < 2:
        await aprint("  Usage: /set <param> <value>")
        await aprint("  Example: /set temperature 0.8\n")
        return

    param, value = parts[0], parts[1]
    user = get_user(uid)
    if not user.selected_model:
        await aprint("  [yellow]No model selected.[/yellow]\n")
        return

    # Parameter definitions with type and range
    param_defs = {
        "temperature":    {"type": float, "min": 0.0,  "max": 2.0},
        "top_p":          {"type": float, "min": 0.0,  "max": 1.0},
        "top_k":          {"type": int,   "min": 1,    "max": 200},
        "num_ctx":        {"type": int,   "min": 1024, "max": 262144},
        "num_predict":    {"type": int,   "min": 128,  "max": 16384},
        "repeat_penalty": {"type": float, "min": 0.5,  "max": 2.0},
        "seed":           {"type": int,   "min": 0,    "max": 999999},
        "keep_alive":     {"type": str},
    }

    if param not in param_defs:
        await aprint(f"  [red]Unknown parameter: {param}[/red]")
        await aprint(f"  Valid: {', '.join(sorted(param_defs))}\n")
        return

    pdef = param_defs[param]
    from openlama.database import set_model_setting
    try:
        if param == "keep_alive":
            from openlama.ollama_client import _normalize_keep_alive
            val = _normalize_keep_alive(value)
        elif pdef["type"] is str:
            val = value
        elif pdef["type"] is int:
            val = int(value)
        else:
            val = float(value)

        # Range validation
        if pdef["type"] is not str and ("min" in pdef or "max" in pdef):
            lo, hi = pdef.get("min"), pdef.get("max")
            if lo is not None and val < lo or hi is not None and val > hi:
                await aprint(f"  [red]{param} must be between {lo} and {hi}.[/red]\n")
                return

        set_model_setting(uid, user.selected_model, param, val)
        await aprint(f"  [green]{param} = {val}[/green]\n")
    except ValueError:
        await aprint(f"  [red]Invalid value: {value}[/red]\n")


async def _cmd_think(uid: int, args: str):
    user = get_user(uid)
    if args.lower() in ("on", "1", "true"):
        new_val = 1
    elif args.lower() in ("off", "0", "false"):
        new_val = 0
    else:
        new_val = 0 if user.think_mode else 1
    update_user(uid, think_mode=new_val)
    await aprint(f"  Think mode: [bold]{'ON' if new_val else 'OFF'}[/bold]\n")


async def _cmd_systemprompt(uid: int, args: str):
    from openlama.core.prompt_builder import _prompts_dir, save_prompt_file
    import subprocess
    import shutil

    d = _prompts_dir()
    files = ["SOUL.md", "USERS.md", "MEMORY.md", "SYSTEM.md"]

    if args and args in files:
        await _edit_prompt_file(d, args)
        return

    if args:
        match = [f for f in files if args.lower() in f.lower()]
        if len(match) == 1:
            await _edit_prompt_file(d, match[0])
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

    await aprint(table)
    await aprint()

    try:
        choice = await _async_prompt_simple("  Select file to edit [1-4], or Enter to cancel: ")
    except (EOFError, KeyboardInterrupt):
        await aprint()
        return

    choice = choice.strip()
    if not choice:
        return

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(files):
            await _edit_prompt_file(d, files[idx])
    except ValueError:
        if choice in files:
            await _edit_prompt_file(d, choice)


async def _edit_prompt_file(prompts_dir, filename: str):
    """Open a prompt file in $EDITOR or inline editing."""
    import subprocess
    import shutil
    from openlama.core.prompt_builder import save_prompt_file

    p = prompts_dir / filename
    content = p.read_text(encoding="utf-8") if p.exists() else ""

    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")

    if not editor:
        for e in ["nano", "vim", "vi"]:
            if shutil.which(e):
                editor = e
                break

    if editor:
        await aprint(f"  Opening {filename} in [cyan]{editor}[/cyan]...")
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_text("", encoding="utf-8")

        result = subprocess.run([editor, str(p)])
        if result.returncode == 0:
            new_content = p.read_text(encoding="utf-8")
            if new_content != content:
                await aprint(f"  [green]{filename} saved ({len(new_content)} chars).[/green]\n")
            else:
                await aprint(f"  [dim]No changes.[/dim]\n")
        else:
            await aprint(f"  [red]Editor exited with error.[/red]\n")
    else:
        await aprint(Panel(
            content[:2000] + ("..." if len(content) > 2000 else ""),
            title=filename, border_style="blue", padding=(0, 1),
        ))
        await aprint(f"\n  [dim]No editor found ($EDITOR not set).[/dim]")
        await aprint(f"  [dim]Paste new content below. Send empty line to finish, Ctrl+C to cancel.[/dim]\n")

        lines = []
        try:
            while True:
                line = await _async_prompt_simple("  ")
                if line == "":
                    break
                lines.append(line)
        except (EOFError, KeyboardInterrupt):
            await aprint("\n  [yellow]Cancelled.[/yellow]\n")
            return

        if lines:
            new_content = "\n".join(lines)
            save_prompt_file(filename, new_content)
            await aprint(f"  [green]{filename} saved ({len(new_content)} chars).[/green]\n")
        else:
            await aprint(f"  [dim]No changes.[/dim]\n")


async def _cmd_export(uid: int, args: str):
    items = load_context(uid)
    if not items:
        await aprint("  [dim]No conversation history.[/dim]\n")
        return

    lines = []
    for i, item in enumerate(items, 1):
        lines.append(f"--- Turn {i} ---")
        lines.append(f"User: {item.get('u', '')}")
        lines.append(f"Assistant: {item.get('a', '')}")
        lines.append("")

    export_path = DATA_DIR / "conversation_export.txt"
    export_path.write_text("\n".join(lines), encoding="utf-8")
    await aprint(f"  Exported {len(items)} turns to: [cyan]{export_path}[/cyan]\n")


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

    await aprint("\n".join(lines))
    await aprint()


async def _cmd_skills(uid: int, args: str):
    from openlama.core.skills import list_skills
    skills = list_skills()
    if not skills:
        await aprint("  [dim]No skills installed.[/dim]\n")
        return

    table = Table(title="Skills", show_lines=False, padding=(0, 2))
    table.add_column("Name", style="cyan")
    table.add_column("Description")
    table.add_column("Trigger", style="yellow")
    for s in skills:
        table.add_row(s["name"], s.get("description", ""), s.get("trigger", ""))
    await aprint(table)
    await aprint()


async def _cmd_mcp(uid: int, args: str):
    from openlama.core.mcp_client import list_server_configs, get_all_servers, get_all_mcp_tools
    configs = list_server_configs()
    running = get_all_servers()
    tools = get_all_mcp_tools()

    if not configs:
        await aprint("  [dim]No MCP servers configured.[/dim]\n")
        return

    table = Table(title="MCP Servers", show_lines=False, padding=(0, 2))
    table.add_column("Name", style="cyan")
    table.add_column("Status")
    table.add_column("Command", style="dim")
    for name, conf in configs.items():
        status = "[green]Running[/green]" if name in running else "[red]Stopped[/red]"
        table.add_row(name, status, conf.get("command", ""))
    await aprint(table)

    if tools:
        await aprint(f"\n  [dim]{len(tools)} tool(s) available from MCP servers.[/dim]")
    await aprint()


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
                await aprint(f"  [green]Task #{job_id} deleted.[/green]\n")
            else:
                await aprint(f"  [red]Task #{job_id} not found.[/red]\n")
        except ValueError:
            await aprint(f"  [red]Invalid ID.[/red]\n")
        return

    jobs = list_cron_jobs()
    if not jobs:
        await aprint("  [dim]No scheduled tasks. Ask the AI to create one.[/dim]\n")
        return

    table = Table(title="Scheduled Tasks", show_lines=True)
    table.add_column("ID", style="cyan", width=4)
    table.add_column("Status", width=6)
    table.add_column("Schedule", style="yellow")
    table.add_column("Task")
    table.add_column("Next Run", style="dim")

    for j in jobs:
        status = "[green]ON[/green]" if j["enabled"] else "[red]OFF[/red]"
        next_ts = j.get("next_run", 0)
        next_str = datetime.datetime.fromtimestamp(next_ts).strftime("%m-%d %H:%M") if next_ts > 0 else "—"
        table.add_row(str(j["id"]), status, j["cron_expr"], j["task"][:40], next_str)

    await aprint(table)
    await aprint(f"  [dim]/cron delete <id> to remove a task.[/dim]\n")


async def _cmd_profile(uid: int, args: str):
    await _run_profile_setup(uid)


async def _cmd_rm(uid: int, args: str):
    """Delete a model from Ollama."""
    if args:
        try:
            await delete_model(args)
            user = get_user(uid)
            if user.selected_model == args:
                update_user(uid, selected_model="")
                await aprint(f"  [green]Deleted: {args} (was active, cleared selection)[/green]\n")
            else:
                await aprint(f"  [green]Deleted: {args}[/green]\n")
        except Exception as e:
            await aprint(f"  [red]Delete failed: {e}[/red]\n")
        return

    try:
        models = await list_models()
    except Exception:
        models = []

    if not models:
        await aprint("  [dim]No models to delete.[/dim]\n")
        return

    user = get_user(uid)
    for i, m in enumerate(models, 1):
        marker = " [green](active)[/green]" if m == user.selected_model else ""
        await aprint(f"  [cyan]{i}[/cyan]. {m}{marker}")

    try:
        choice = await _async_prompt_simple("\n  Select model to delete (number or name), Enter to cancel: ")
    except (EOFError, KeyboardInterrupt):
        await aprint()
        return

    choice = choice.strip()
    if not choice:
        return

    target = None
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(models):
            target = models[idx]
    except ValueError:
        if choice in models:
            target = choice

    if not target:
        await aprint(f"  [red]Invalid selection.[/red]\n")
        return

    try:
        confirm = await _async_prompt_simple(f"  Delete '{target}'? (y/N): ")
    except (EOFError, KeyboardInterrupt):
        await aprint()
        return

    if confirm.strip().lower() != "y":
        await aprint("  [dim]Cancelled.[/dim]\n")
        return

    try:
        await delete_model(target)
        if user.selected_model == target:
            update_user(uid, selected_model="")
        await aprint(f"  [green]Deleted: {target}[/green]\n")
    except Exception as e:
        await aprint(f"  [red]Delete failed: {e}[/red]\n")


async def _cmd_compress(uid: int, args: str):
    """Compress conversation context by summarizing older turns."""
    from openlama.core.context import _estimate_tokens
    from openlama.database import save_context

    user = get_user(uid)
    if not user.selected_model:
        await aprint("  [yellow]No model selected.[/yellow]\n")
        return

    ctx_items = load_context(uid)
    if len(ctx_items) < 2:
        await aprint("  [dim]Not enough context to compress (minimum 2 turns).[/dim]\n")
        return

    split_at = max(1, len(ctx_items) * 2 // 3)
    old_items = ctx_items[:split_at]
    recent_items = ctx_items[split_at:]

    old_text = "\n".join(
        f"User: {it.get('u', '')}\nAssistant: {it.get('a', '')}" for it in old_items
    )

    before_tokens = _estimate_tokens(
        sum(len(it.get("u", "")) + len(it.get("a", "")) for it in ctx_items)
    )

    _status["text"] = "Compressing context..."
    try:
        summary = await summarize_context(user.selected_model, old_text)
    except Exception as e:
        _status["text"] = ""
        await aprint(f"  [red]Compression failed: {e}[/red]\n")
        return
    _status["text"] = ""

    # Save compressed content to daily memory
    from openlama.core.memory import save_daily_entry
    try:
        save_daily_entry(summary, source="context_compression")
    except Exception:
        pass

    compressed = [{"u": "[Context Summary]", "a": summary}] + recent_items
    save_context(uid, compressed)

    after_tokens = _estimate_tokens(
        sum(len(it.get("u", "")) + len(it.get("a", "")) for it in compressed)
    )
    saved = before_tokens - after_tokens
    pct = saved / max(before_tokens, 1) * 100

    await aprint(f"\n  [bold]Context compressed[/bold]")
    await aprint(f"  Before:     {len(ctx_items)} turns, ~{before_tokens:,} tokens")
    await aprint(f"  After:      {len(compressed)} turns, ~{after_tokens:,} tokens")
    await aprint(f"  Saved:      ~{saved:,} tokens ({pct:.0f}%)")
    await aprint(f"  Summarized: {len(old_items)} turns -> 1 summary")
    await aprint(f"  Kept:       {len(recent_items)} recent turns\n")


async def _cmd_session(uid: int, args: str):
    """View and extend session."""
    from openlama.database import now_ts
    from openlama.config import get_config_int

    user = get_user(uid)
    auth_left = max(0, user.auth_until - now_ts())

    if args.lower() == "extend":
        session_ttl = get_config_int("session_ttl_sec", 86400)
        new_until = now_ts() + session_ttl
        update_user(uid, auth_until=new_until)
        hours = session_ttl // 3600
        await aprint(f"  [green]Session extended by {hours} hours.[/green]\n")
        return

    if auth_left > 0:
        hours, remainder = divmod(auth_left, 3600)
        mins = remainder // 60
        auth_str = f"Valid ({hours}h {mins}m remaining)"
    else:
        auth_str = "[red]Expired[/red]"

    await aprint(f"\n  [bold]Session[/bold]")
    await aprint(f"  Status:  {auth_str}")
    await aprint(f"  Model:   {user.selected_model or '(none)'}")
    await aprint(f"  Think:   {'ON' if user.think_mode else 'OFF'}")
    await aprint(f"\n  [dim]Use /session extend to extend by 24h.[/dim]\n")


async def _cmd_settings_interactive(uid: int, args: str):
    """Interactive settings — navigate with numbers, adjust values."""
    user = get_user(uid)
    if not user.selected_model:
        await aprint("  [yellow]No model selected.[/yellow]\n")
        return

    # Parameter config matching Telegram's PARAM_CONFIG
    params = [
        {"key": "temperature",    "label": "Temperature",    "type": float, "min": 0.0,  "max": 2.0,    "step": 0.1},
        {"key": "top_p",          "label": "Top P",          "type": float, "min": 0.0,  "max": 1.0,    "step": 0.05},
        {"key": "top_k",          "label": "Top K",          "type": int,   "min": 1,    "max": 200,    "step": 5},
        {"key": "num_ctx",        "label": "Context Size",   "type": int,   "presets": [2048, 4096, 8192, 16384, 32768, 65536, 131072]},
        {"key": "num_predict",    "label": "Max Tokens",     "type": int,   "presets": [256, 512, 1024, 2048, 4096, 8192]},
        {"key": "repeat_penalty", "label": "Repeat Penalty", "type": float, "min": 0.5,  "max": 2.0,    "step": 0.1},
        {"key": "seed",           "label": "Seed",           "type": int,   "min": 0,    "max": 999999, "step": 1},
        {"key": "keep_alive",     "label": "Keep Alive",     "type": str, "presets": ["30s", "1m", "5m", "15m", "30m", "1h", "24h"]},
    ]

    from openlama.database import set_model_setting, reset_model_settings

    while True:
        ms = get_model_settings(uid, user.selected_model)

        table = Table(title=f"Settings ({user.selected_model})", show_lines=True, padding=(0, 1))
        table.add_column("#", style="dim", width=3)
        table.add_column("Parameter", style="cyan")
        table.add_column("Value", style="green", justify="right")
        table.add_column("Range", style="dim")

        for i, p in enumerate(params, 1):
            val = getattr(ms, p["key"], None)
            if val is None:
                val = p.get("min", 0)

            if p.get("presets"):
                range_str = " | ".join(str(v) for v in p["presets"])
            elif "min" in p and "max" in p:
                range_str = f"{p['min']} ~ {p['max']}"
            else:
                range_str = "string"

            table.add_row(str(i), p["label"], str(val), range_str)

        await aprint(table)
        await aprint()
        await aprint("  [dim]Enter number to edit, [bold]r[/bold] to reset all, Enter to exit.[/dim]")

        try:
            choice = await _async_prompt_simple("  > ")
        except (EOFError, KeyboardInterrupt):
            break

        choice = choice.strip().lower()
        if not choice:
            break

        if choice == "r":
            reset_model_settings(uid, user.selected_model)
            await aprint("  [green]All settings reset to defaults.[/green]\n")
            continue

        try:
            idx = int(choice) - 1
        except ValueError:
            await aprint("  [red]Invalid selection.[/red]\n")
            continue

        if not (0 <= idx < len(params)):
            await aprint("  [red]Invalid number.[/red]\n")
            continue

        p = params[idx]
        current = getattr(ms, p["key"], None)

        if p.get("presets"):
            # Show preset selection
            presets = p["presets"]
            await aprint(f"\n  [bold]{p['label']}[/bold] (current: [green]{current}[/green])")
            for pi, pv in enumerate(presets, 1):
                marker = " [green]*[/green]" if pv == current else ""
                await aprint(f"    [cyan]{pi}[/cyan]. {pv:,}{marker}")

            try:
                pchoice = await _async_prompt_simple(f"  Select [1-{len(presets)}] or type value: ")
            except (EOFError, KeyboardInterrupt):
                continue

            pchoice = pchoice.strip()
            if not pchoice:
                continue

            try:
                pi = int(pchoice) - 1
                if 0 <= pi < len(presets):
                    new_val = presets[pi]
                else:
                    new_val = int(pchoice)
            except ValueError:
                await aprint("  [red]Invalid value.[/red]\n")
                continue

            set_model_setting(uid, user.selected_model, p["key"], new_val)
            await aprint(f"  [green]{p['label']} = {new_val:,}[/green]\n")

        elif p["type"] is str:
            await aprint(f"\n  [bold]{p['label']}[/bold] (current: [green]{current}[/green])")
            try:
                new_val = await _async_prompt_simple(f"  New value: ")
            except (EOFError, KeyboardInterrupt):
                continue
            new_val = new_val.strip()
            if new_val:
                set_model_setting(uid, user.selected_model, p["key"], new_val)
                await aprint(f"  [green]{p['label']} = {new_val}[/green]\n")

        else:
            # Numeric with +/- step
            step = p.get("step", 1)
            lo, hi = p.get("min", 0), p.get("max", 999999)
            await aprint(f"\n  [bold]{p['label']}[/bold] (current: [green]{current}[/green], range: {lo} ~ {hi})")
            await aprint(f"  [dim]+/- to adjust by {step}, or type a value directly.[/dim]")

            try:
                vchoice = await _async_prompt_simple(f"  > ")
            except (EOFError, KeyboardInterrupt):
                continue

            vchoice = vchoice.strip()
            if not vchoice:
                continue

            if vchoice == "+":
                new_val = min(current + step, hi)
            elif vchoice == "-":
                new_val = max(current - step, lo)
            else:
                try:
                    new_val = p["type"](vchoice)
                except ValueError:
                    await aprint("  [red]Invalid value.[/red]\n")
                    continue

            if isinstance(new_val, (int, float)):
                new_val = max(lo, min(hi, new_val))

            set_model_setting(uid, user.selected_model, p["key"], new_val)
            fmt = f"  [green]{p['label']} = {new_val}[/green]\n"
            await aprint(fmt)


# Command dispatch table
CMD_HANDLERS = {
    "help": _cmd_help,
    "clear": _cmd_clear,
    "status": _cmd_status,
    "model": _cmd_model,
    "models": _cmd_models,
    "pull": _cmd_pull,
    "rm": _cmd_rm,
    "settings": _cmd_settings_interactive,
    "set": _cmd_set,
    "think": _cmd_think,
    "systemprompt": _cmd_systemprompt,
    "compress": _cmd_compress,
    "session": _cmd_session,
    "export": _cmd_export,
    "ollama": _cmd_ollama,
    "skills": _cmd_skills,
    "mcp": _cmd_mcp,
    "cron": _cmd_cron,
    "profile": _cmd_profile,
}


# ─── Slash command autocomplete (Rich fallback — used by _show_command_list) ───

async def _show_command_list(prefix: str = ""):
    """Show matching commands as a Rich table (fallback for non-completion contexts)."""
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
        await aprint(table)
        await aprint()


# ─── Input processing ─────────────────────────────

async def _process_input(uid: int, user_input: str):
    """Process a single user input — command or chat message."""
    user_input = user_input.strip()
    if not user_input:
        return

    # Command handling
    if user_input.startswith("/"):
        cleaned = user_input.lstrip("/")

        parts = cleaned.split(None, 1)
        cmd_name = parts[0].lower() if parts else ""
        cmd_args = parts[1] if len(parts) > 1 else ""

        # Just "/" — show all commands
        if not cmd_name:
            await _show_command_list()
            return

        # Exact match
        handler = CMD_HANDLERS.get(cmd_name)
        if not handler:
            # Prefix match
            matches = [n for n in CMD_HANDLERS if n.startswith(cmd_name)]
            if len(matches) == 1:
                handler = CMD_HANDLERS[matches[0]]
                cmd_name = matches[0]
            elif matches:
                await _show_command_list(cmd_name)
                return
            else:
                await aprint(f"  [red]Unknown command: /{cmd_name}[/red]")
                await aprint(f"  [dim]Type / to see available commands.[/dim]\n")
                return

        try:
            await handler(uid, cmd_args)
        except Exception as e:
            await aprint(f"\n  [red]Error in /{cmd_name}: {e}[/red]\n")
            logger.error("Command /%s error: %s", cmd_name, e, exc_info=True)
        return

    # Regular chat message
    request = ChatRequest(user_id=uid, text=user_input, channel="cli")

    try:
        _status["text"] = "Thinking..."
        response: ChatResponse = await chat(request)
        _status["text"] = ""

        if response.content:
            try:
                await aprint(Rule(" AI ", style="blue"))
                await aprint(Markdown(response.content))
                await aprint(Rule(style="blue"))
            except Exception:
                await aprint(f"  [blue]AI>[/blue] {response.content}")

        if response.images:
            for img_path in response.images:
                await aprint(f"  [dim]Image: {img_path}[/dim]")

        if response.context_bar:
            await aprint(f"  [dim]{response.context_bar}[/dim]")

    except Exception as e:
        _status["text"] = ""
        await aprint(f"\n  [red]Error: {e}[/red]\n")
        logger.error("CLI chat error: %s", e, exc_info=True)


# ─── Async Input + Worker architecture ─────────────────────────────

def _build_prompt_message() -> HTML:
    """Build the prompt message with a top ruler line."""
    width = console.width or 80
    ruler = "─" * width
    return HTML(f"<ansigray>{ruler}</ansigray>\n<b><ansigreen>❯</ansigreen></b> ")


async def _input_loop(queue: asyncio.Queue, session: PromptSession):
    """Async input loop — reads from prompt_toolkit, pushes to queue."""
    while True:
        try:
            text = await session.prompt_async(
                _build_prompt_message(),
            )
        except EOFError:
            await queue.put(_QUIT)
            break
        except KeyboardInterrupt:
            await queue.put(_QUIT)
            break

        text = text.strip()
        if not text:
            continue

        # Check for quit commands before queueing
        if text.startswith("/"):
            cleaned = text.lstrip("/").lower()
            if cleaned in ("quit", "exit", "q"):
                await queue.put(_QUIT)
                break

        await queue.put(text)


async def _worker_loop(queue: asyncio.Queue, uid: int):
    """Worker loop — pulls messages from queue and processes sequentially."""
    while True:
        msg = await queue.get()

        if msg is _QUIT:
            await aprint("  [dim]Goodbye.[/dim]\n")
            break

        # Show queue depth if messages are waiting
        pending = queue.qsize()
        if pending > 0:
            await aprint(f"  [dim]({pending} more queued)[/dim]")

        # Visual separator before output
        await aprint(Rule(style="dim"))
        await _process_input(uid, msg)
        await aprint(Rule(style="dim"))

        queue.task_done()


# ─── Main chat loop ─────────────────────────────

async def run_chat():
    """Main CLI chat loop with async message queue."""
    global _session

    init_db()
    init_tools()

    # Register compress notification for TUI toolbar
    from openlama.core.context import set_compress_notify

    async def _on_compress(status: str):
        if status == "start":
            _status["text"] = "Compressing context..."
        elif status == "done":
            _status["text"] = ""
            await aprint("  [dim]Context auto-compressed.[/dim]")
        elif status == "failed":
            _status["text"] = ""

    set_compress_notify(_on_compress)

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
    status = _get_status_line(uid)

    console.print()
    console.print(Rule("[bold]openlama[/bold]", style="blue"))
    console.print(f"  [dim]{status}[/dim]")
    console.print(f"  [dim]Type / for commands (Tab to autocomplete), /quit to exit.[/dim]")
    console.print()

    # Show recent conversation history
    ctx = load_context(uid)
    if ctx:
        recent = ctx[-5:]  # last 5 turns
        console.print(f"  [dim]── Recent conversation ({len(ctx)} turns total) ──[/dim]")
        for item in recent:
            u = item.get("u", "")
            a = item.get("a", "")
            if u:
                short_u = u[:80] + ("..." if len(u) > 80 else "")
                console.print(f"  [green]You:[/green] [dim]{short_u}[/dim]")
            if a:
                short_a = a[:120] + ("..." if len(a) > 120 else "")
                console.print(f"  [blue]AI:[/blue]  [dim]{short_a}[/dim]")
        console.print()

    # Key bindings — fix Korean IME truncation on Enter
    kb = KeyBindings()

    @kb.add("enter")
    def _handle_enter(event):
        """Insert a trailing space to commit IME composition before accepting."""
        buf = event.current_buffer
        buf.insert_text(" ")
        buf.validate_and_handle()

    # Setup prompt session with bottom toolbar for spinner
    history_path = str(DATA_DIR / "chat_history")
    _session = PromptSession(
        history=FileHistory(history_path),
        completer=SlashCompleter(),
        complete_while_typing=True,
        bottom_toolbar=_toolbar,
        refresh_interval=0.1,
        key_bindings=kb,
    )

    queue: asyncio.Queue = asyncio.Queue()

    # Run input and worker concurrently.
    # aprint() uses set_app() to propagate the app context to run_in_terminal.
    input_task = asyncio.create_task(_input_loop(queue, _session))
    worker_task = asyncio.create_task(_worker_loop(queue, uid))

    done, pending = await asyncio.wait(
        [input_task, worker_task],
        return_when=asyncio.FIRST_COMPLETED,
    )

    if input_task in done and worker_task not in done:
        if queue.empty():
            await queue.put(_QUIT)
        await worker_task

    if worker_task in done and input_task not in done:
        input_task.cancel()
        try:
            await input_task
        except asyncio.CancelledError:
            pass

    _session = None


class CLIChannel(Channel):
    async def start(self):
        await run_chat()

    async def stop(self):
        pass
