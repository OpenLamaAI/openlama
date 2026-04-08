"""Telegram handlers -- commands, callbacks, chat, media.

This is the Telegram channel layer. Core chat logic (Ollama calls, tool loop,
context management) lives in openlama.core.agent. This module handles:
- Telegram-specific I/O (messages, keyboards, callbacks)
- Streaming edits
- Media processing (images, audio, video, documents)
- Formatting (markdown -> entities)
"""

from __future__ import annotations

import asyncio
import base64
import io
import re
import time
from pathlib import Path
from typing import Optional

from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from openlama.auth import hash_password, require_auth, verify_password
from openlama.config import (
    DEFAULT_SYSTEM_PROMPT,
    MODEL_PAGE_SIZE,
    get_config,
    get_config_int,
)
from openlama.database import (
    UserState,
    add_allowed_id,
    clear_context,
    get_admin_password_hash,
    get_allowed_ids,
    get_model_settings,
    get_user,
    is_allowed,
    is_authed,
    is_login_locked,
    load_context,
    now_ts,
    save_context,
    set_admin_password_hash,
    update_user,
)
from openlama.ollama_client import (
    chat_stream,
    delete_model,
    ensure_ollama_running,
    fetch_models,
    get_model_capabilities,
    get_model_display_map,
    get_model_max_context,
    get_pull_state,
    model_supports_images,
    model_supports_thinking,
    model_supports_tools,
    pull_model_stream,
    set_pull_state,
    summarize_context,
    unload_model,
)
from openlama.core.agent import chat as agent_chat, handle_tool_calls, PROFILE_QUESTIONS
from openlama.core.types import ChatRequest, ChatResponse
from openlama.core.prompt_builder import is_profile_setup_done, save_prompt_file, generate_system_prompt, build_full_system_prompt
from openlama.core.context import _estimate_tokens, _estimate_messages_tokens, build_context_bar
from openlama.tools import format_tools_for_ollama
from openlama.utils.file_processor import (
    detect_file_type,
    process_audio,
    process_pdf,
    process_text_file,
    process_video,
)
from openlama.utils.formatting import convert_markdown, split_message, chunks, reply_llm_answer
from openlama.utils.streaming import stream_response_to_message
from openlama.logger import get_logger

logger = get_logger("telegram.handlers")


def _save_and_clear(uid: int):
    """Save current context to daily memory, then clear."""
    ctx = load_context(uid)
    if ctx:
        from openlama.core.memory import extract_topics, save_daily_entry
        topics = extract_topics(ctx)
        if topics:
            save_daily_entry(topics, source="context_clear")
    clear_context(uid)


# ══════════════════════════════════════════════════════════
# Keyboard builders
# ══════════════════════════════════════════════════════════

def main_menu_keyboard(is_logged_in: bool = False) -> InlineKeyboardMarkup:
    """Build the main menu button keyboard."""
    if not is_logged_in:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🔑 Login", callback_data="cmd:login")],
            [InlineKeyboardButton("📖 Help", callback_data="cmd:help")],
        ])

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🤖 Select Model", callback_data="cmd:models"),
            InlineKeyboardButton("📊 Current Model", callback_data="cmd:model"),
        ],
        [
            InlineKeyboardButton("⚙️ Settings", callback_data="cmd:settings"),
            InlineKeyboardButton("💬 System Prompt", callback_data="cmd:systemprompt"),
        ],
        [
            InlineKeyboardButton("🧠 Think Mode", callback_data="cmd:think_toggle"),
            InlineKeyboardButton("📊 Context", callback_data="cmd:context_status"),
        ],
        [
            InlineKeyboardButton("📥 Install Model", callback_data="cmd:pull_prompt"),
            InlineKeyboardButton("🗂 Delete Model", callback_data="cmd:rm"),
        ],
        [
            InlineKeyboardButton("🖥 Ollama Mgmt", callback_data="cmd:ollama"),
            InlineKeyboardButton("🎨 ComfyUI Mgmt", callback_data="cmd:comfyui"),
        ],
        [
            InlineKeyboardButton("📋 Session Mgmt", callback_data="cmd:session"),
            InlineKeyboardButton("📤 Export Chat", callback_data="cmd:export"),
        ],
        [
            InlineKeyboardButton("📖 Help", callback_data="cmd:help"),
            InlineKeyboardButton("🔓 Logout", callback_data="cmd:logout"),
        ],
    ])


def model_keyboard(models: list[str], page: int = 0, display_map: dict | None = None) -> InlineKeyboardMarkup:
    total_pages = max(1, (len(models) + MODEL_PAGE_SIZE - 1) // MODEL_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    chunk = models[page * MODEL_PAGE_SIZE: (page + 1) * MODEL_PAGE_SIZE]

    rows = [
        [InlineKeyboardButton((display_map or {}).get(m, m), callback_data=f"model:{m}")]
        for m in chunk
    ]

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀ Prev", callback_data=f"models_page:{page - 1}"))
    nav.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next ▶", callback_data=f"models_page:{page + 1}"))
    rows.append(nav)
    rows.append([
        InlineKeyboardButton("🗑 Clear Context", callback_data="clear_ctx"),
        InlineKeyboardButton("🏠 Menu", callback_data="cmd:menu"),
    ])
    return InlineKeyboardMarkup(rows)


def rm_model_keyboard(models: list[str], page: int = 0, selected_model: str = "", display_map: dict | None = None) -> InlineKeyboardMarkup:
    total_pages = max(1, (len(models) + MODEL_PAGE_SIZE - 1) // MODEL_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    chunk = models[page * MODEL_PAGE_SIZE: (page + 1) * MODEL_PAGE_SIZE]

    rows = []
    for m in chunk:
        label = (display_map or {}).get(m, m)
        if m == selected_model:
            label = f"✅ {label}"
        rows.append([InlineKeyboardButton(label, callback_data=f"rm_model:{m}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀ Prev", callback_data=f"rm_page:{page - 1}"))
    nav.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next ▶", callback_data=f"rm_page:{page + 1}"))
    rows.append(nav)
    rows.append([
        InlineKeyboardButton("Cancel", callback_data="rm_cancel"),
        InlineKeyboardButton("🏠 Menu", callback_data="cmd:menu"),
    ])
    return InlineKeyboardMarkup(rows)


# ══════════════════════════════════════════════════════════
# Help text
# ══════════════════════════════════════════════════════════

HELP_TEXT = """<b>📖 Openlama User Guide</b>

<b>🔐 Authentication</b>
• /login — Password authentication
• /logout — Log out
• /setpassword — Change admin password

<b>🤖 Model Management</b>
• /models — List / select models
• /model — Current model info
• /pull &lt;model&gt; — Install model
• /pullstatus — Installation progress
• /rm — Delete model

<b>⚙️ Settings</b>
• /settings — Model parameters
• /systemprompt — System prompt
• /think — Toggle reasoning mode

<b>💬 Context</b>
• /clear — Clear conversation context
• /compress — Compress context (summarize)
• /export — Export conversation history
• /session — View/extend auth session

<b>🖥 System</b>
• /ollama — Ollama server management
• /skills — List installed skills
• /mcp — MCP server status
• /cron — Scheduled tasks

<b>💡 Usage</b>
• Text → AI responds using selected model
• Image → Vision analysis (👁 vision models)
• PDF/document → Content analysis
• Audio/voice → Speech-to-text transcription (STT)
• Video → Frame extraction analysis
• ZIP → Skill installation or content analysis

<b>🔧 Available Tools</b> (tool-supported models)
• 🔍 Web search  • 🌐 URL fetch  • 🕐 Date/time
• 💻 Code execution (Python/Node/Shell)
• 📁 File read/write  • 🖥 Shell commands
• 🔀 Git  • 📊 Process manager  • 🖥 tmux
• 🧮 Calculator  • 🎨 Image gen/edit (ComfyUI)
• 🧠 Memory (long-term + daily episodic search)
• 📋 Cron scheduler  • 🛠 Skill creator
• 🎤 Whisper STT  • 🔄 Self-update
• 📝 Obsidian notes  • 📡 MCP tools
"""


# ══════════════════════════════════════════════════════════
# Context status helpers (from context_status.py)
# ══════════════════════════════════════════════════════════

def _bar(pct: float, width: int = 20) -> str:
    filled = int(pct / 100 * width)
    return "█" * filled + "░" * (width - filled)


async def build_context_status(uid: int, user) -> tuple[str, InlineKeyboardMarkup]:
    """Build detailed context status text and keyboard."""
    model = user.selected_model or ""
    ms = get_model_settings(uid, model) if model else None
    num_ctx = ms.num_ctx if ms else 8192

    active_items = load_context(uid)

    # Calculate tokens
    sys_prompt_len = len(user.system_prompt or "")
    sys_tokens = _estimate_tokens(sys_prompt_len) if sys_prompt_len else 0

    total_ctx_chars = 0
    turn_details = []
    for i, item in enumerate(active_items):
        u_text = item.get("u", "")
        a_text = item.get("a", "")
        u_tokens = _estimate_tokens(len(u_text))
        a_tokens = _estimate_tokens(len(a_text))
        turn_tokens = u_tokens + a_tokens
        total_ctx_chars += len(u_text) + len(a_text)

        preview = u_text[:40].replace("\n", " ")
        if len(u_text) > 40:
            preview += "..."

        turn_details.append({
            "index": i + 1,
            "u_tokens": u_tokens,
            "a_tokens": a_tokens,
            "total": turn_tokens,
            "preview": preview,
        })

    total_tokens = sys_tokens + _estimate_tokens(total_ctx_chars)
    pct = min(total_tokens / num_ctx * 100, 100) if num_ctx > 0 else 0

    lines = [
        f"📊 <b>Context Status</b>\n",
        f"<b>Model:</b> {model or '(none selected)'}",
        f"<b>Max Context:</b> {num_ctx:,} tokens",
        f"<b>In Use (est.):</b> ~{total_tokens:,} tokens ({pct:.1f}%)",
        f"<b>Active Turns:</b> {len(active_items)}",
        f"\n{_bar(pct)} {pct:.0f}%\n",
    ]

    if sys_tokens > 0:
        lines.append(f"  💬 System prompt: ~{sys_tokens:,} tokens")

    if turn_details:
        lines.append("\n<b>Turn Structure:</b>")
        for td in turn_details:
            lines.append(
                f"  {td['index']}. 👤{td['u_tokens']}t + 🤖{td['a_tokens']}t = <b>{td['total']}t</b>"
                f"\n      <code>{td['preview']}</code>"
            )
    else:
        lines.append("\n<i>No saved context</i>")

    if pct >= 80:
        lines.append(f"\n⚠️ Context {pct:.0f}% used — auto-compression will run soon")
    elif pct >= 60:
        lines.append(f"\n💡 Context {pct:.0f}% — compression threshold (60%) reached")

    text = "\n".join(lines)

    buttons = []
    if len(active_items) >= 2:
        buttons.append(InlineKeyboardButton("🗜 Compress Context", callback_data="ctx:compress"))
    buttons.append(InlineKeyboardButton("🗑 Clear", callback_data="clear_ctx"))
    kb = InlineKeyboardMarkup([
        buttons,
        [InlineKeyboardButton("🔄 Refresh", callback_data="cmd:context_status")],
        [InlineKeyboardButton("🏠 Menu", callback_data="cmd:menu")],
    ])

    return text, kb


async def compress_context(uid: int, user) -> str:
    """Manually compress context: summarize older 2/3, keep recent 1/3."""
    model = user.selected_model
    if not model:
        return "No model selected."

    ctx_items = load_context(uid)
    if len(ctx_items) < 2:
        return "Not enough context to compress. (minimum 2 turns required)"

    split_at = max(1, len(ctx_items) * 2 // 3)
    old_items = ctx_items[:split_at]
    recent_items = ctx_items[split_at:]

    old_text = "\n".join(
        f"User: {it.get('u', '')}\nAssistant: {it.get('a', '')}" for it in old_items
    )

    before_tokens = _estimate_tokens(sum(len(it.get("u", "")) + len(it.get("a", "")) for it in ctx_items))

    try:
        summary = await summarize_context(model, old_text)
    except Exception as e:
        return f"Compression failed: {e}"

    # Save compressed content to daily memory
    try:
        from openlama.core.memory import save_daily_entry
        save_daily_entry(summary, source="context_compression")
    except Exception:
        pass

    compressed = [{"u": "[Context Summary]", "a": summary}] + recent_items
    save_context(uid, compressed)

    after_tokens = _estimate_tokens(sum(len(it.get("u", "")) + len(it.get("a", "")) for it in compressed))
    saved = before_tokens - after_tokens

    return (
        f"🗜 Context compression complete\n\n"
        f"• Before: {len(ctx_items)} turns, ~{before_tokens:,} tokens\n"
        f"• After: {len(compressed)} turns, ~{after_tokens:,} tokens\n"
        f"• Saved: ~{saved:,} tokens ({saved / max(before_tokens, 1) * 100:.0f}%)\n"
        f"• Summarized: {len(old_items)} turns -> 1 summary turn\n"
        f"• Kept: {len(recent_items)} turns"
    )


# ══════════════════════════════════════════════════════════
# Password / login flow
# ══════════════════════════════════════════════════════════

async def _handle_password_flow(update: Update, user: UserState, text: str) -> bool:
    """Handle password-related state flows. Returns True if handled."""
    uid = user.telegram_id
    session_ttl = get_config_int("session_ttl_sec", 86400)
    login_max_fails = get_config_int("login_max_fails", 5)
    login_lock_sec = get_config_int("login_lock_sec", 600)

    if user.state == "await_password":
        if is_login_locked(user):
            await update.message.reply_text(f"Login locked: {user.login_lock_until - now_ts()}s remaining")
            return True

        stored_hash = get_admin_password_hash()
        if not stored_hash:
            await update.message.reply_text("Server password not set")
            return True

        if verify_password(text, stored_hash):
            update_user(uid, auth_until=now_ts() + session_ttl, state="", login_fail_count=0, login_lock_until=0)

            # AllowList: auto-register on first successful login
            allowed = get_allowed_ids()
            if not allowed:
                # First user ever -- add to allow list
                add_allowed_id(uid)
                logger.info("First login: added uid=%d to allow list.", uid)
            elif uid not in allowed:
                add_allowed_id(uid)
                logger.info("Auto-registered uid=%d to allow list.", uid)

            selected = user.selected_model
            if not selected:
                try:
                    ok, _ = await ensure_ollama_running()
                    if ok:
                        models = await fetch_models()
                        default_model = get_config("default_model")
                        selected = default_model if default_model in models else (models[0] if models else "")
                        update_user(uid, selected_model=selected)
                except Exception:
                    pass

            # Check profile setup — skip already completed steps
            if not is_profile_setup_done():
                from openlama.core.prompt_builder import _has_real_content, _prompts_dir
                from openlama.core.onboarding import LANGUAGES
                d = _prompts_dir()
                if not _has_real_content(d / "USERS.md"):
                    lang_list = "\n".join(f"  {i}. {name}" for i, (_, name) in enumerate(LANGUAGES, 1))
                    update_user(uid, state="await_profile_language")
                    await update.message.reply_text(
                        f"Authentication successful. Model: {selected or '(none selected)'}\n\n"
                        f"--- Profile Setup (Step 1/3) ---\n"
                        f"Select your language:\n{lang_list}\n\n"
                        f"Reply with a number or type a language name.",
                        reply_markup=main_menu_keyboard(True),
                    )
                elif not _has_real_content(d / "SOUL.md"):
                    update_user(uid, state="await_profile_soul")
                    await update.message.reply_text(
                        f"Authentication successful. Model: {selected or '(none selected)'}\n\n"
                        f"--- Profile Setup (Step 3/3) ---\n"
                        f"{PROFILE_QUESTIONS['soul']}",
                        reply_markup=main_menu_keyboard(True),
                    )
            else:
                await update.message.reply_text(
                    f"✅ Authentication successful\nCurrent model: {selected or '(none selected)'}",
                    reply_markup=main_menu_keyboard(True),
                )
        else:
            fail = user.login_fail_count + 1
            if fail >= login_max_fails:
                update_user(uid, state="", login_fail_count=0, login_lock_until=now_ts() + login_lock_sec)
                await update.message.reply_text(f"❌ Too many failures. Locked for {login_lock_sec}s")
            else:
                update_user(uid, login_fail_count=fail)
                await update.message.reply_text(f"❌ Wrong password ({fail}/{login_max_fails})")
        return True

    if user.state == "await_current_password_for_change":
        stored_hash = get_admin_password_hash()
        if not stored_hash or not verify_password(text, stored_hash):
            update_user(uid, state="")
            await update.message.reply_text("Current password incorrect. Try /setpassword again")
            return True
        update_user(uid, state="await_new_password")
        await update.message.reply_text("Enter new password (minimum 8 characters)")
        return True

    if user.state == "await_new_password":
        if len(text) < 8:
            await update.message.reply_text("Must be at least 8 characters")
            return True
        set_admin_password_hash(hash_password(text))
        update_user(uid, state="")
        await update.message.reply_text("✅ Password changed successfully")
        return True

    # Prompt file editing
    if user.state.startswith("await_prompt_edit|"):
        fname = user.state.split("|", 1)[1]
        allowed_files = {"SOUL.md", "USERS.md", "MEMORY.md"}
        if fname not in allowed_files:
            update_user(uid, state="")
            return True
        save_prompt_file(fname, text)
        update_user(uid, state="")
        await update.message.reply_text(
            f"✅ {fname} updated ({len(text)} chars).",
            reply_markup=main_menu_keyboard(True),
        )
        return True

    return False


# ══════════════════════════════════════════════════════════
# Profile setup onboarding flow
# ══════════════════════════════════════════════════════════

async def _handle_profile_setup(update: Update, user: UserState, text: str) -> bool:
    """Handle profile setup flow: language -> user info -> agent identity -> AI refinement."""
    uid = user.telegram_id

    # If profile is already complete (e.g. set via CLI), clear stale state
    if user.state.startswith("await_profile") and is_profile_setup_done():
        update_user(uid, state="")
        return False

    if user.state == "await_profile_language":
        from openlama.core.onboarding import LANGUAGES
        text = text.strip()
        # Try numeric selection
        try:
            idx = int(text) - 1
            if 0 <= idx < len(LANGUAGES):
                language = LANGUAGES[idx][1]
            else:
                language = "English"
        except ValueError:
            language = text if text else "English"

        # Store language temporarily in user state
        update_user(uid, state=f"await_profile_users|{language}")
        await update.message.reply_text(
            f"Language: {language}\n\n{PROFILE_QUESTIONS['users']}"
        )
        return True

    if user.state.startswith("await_profile_users"):
        if len(text.strip()) < 10:
            await update.message.reply_text(
                "Too short. Please share at least 10 characters about yourself."
            )
            return True
        # Extract language from state
        parts = user.state.split("|", 1)
        language = parts[1] if len(parts) > 1 else "English"
        save_prompt_file("USERS.md", f"# User Profile\n\nLanguage: {language}\n\n{text}")
        update_user(uid, state="await_profile_soul")
        await update.message.reply_text(
            f"User profile saved.\n\n{PROFILE_QUESTIONS['soul']}"
        )
        return True

    if user.state == "await_profile_soul":
        if len(text.strip()) < 10:
            await update.message.reply_text(
                "Too short. Please provide at least 10 characters about the agent identity."
            )
            return True
        save_prompt_file("SOUL.md", f"# Agent Identity\n\n{text}")
        update_user(uid, state="")

        # AI refinement
        from openlama.core.onboarding import check_model_available, refine_users_prompt, refine_soul_prompt
        from openlama.core.prompt_builder import _prompts_dir
        ok, model, _ = await check_model_available()

        if not ok or not model:
            # No model — rollback
            save_prompt_file("USERS.md", "")
            save_prompt_file("SOUL.md", "")
            await update.message.reply_text(
                "No model available. Please install a model first.\n"
                "Run: openlama setup",
                reply_markup=main_menu_keyboard(True),
            )
            return True

        await update.message.reply_text("Refining your profile with AI...")

        d = _prompts_dir()

        # Read and detect language
        users_raw = (d / "USERS.md").read_text(encoding="utf-8") if (d / "USERS.md").exists() else ""
        language = "English"
        for line in users_raw.split("\n"):
            if line.strip().startswith("Language:"):
                language = line.split(":", 1)[1].strip()
                break

        refined_users = await refine_users_prompt(model, users_raw, language)
        if refined_users:
            save_prompt_file("USERS.md", refined_users)

        soul_raw = (d / "SOUL.md").read_text(encoding="utf-8") if (d / "SOUL.md").exists() else ""
        refined_soul = await refine_soul_prompt(model, soul_raw)
        if refined_soul:
            save_prompt_file("SOUL.md", refined_soul)

        generate_system_prompt()

        # Show results
        result_msg = "Profile setup complete!\n\n"
        if refined_users:
            result_msg += f"--- USERS.md ---\n{refined_users}\n\n"
        if refined_soul:
            result_msg += f"--- SOUL.md ---\n{refined_soul}"

        await update.message.reply_text(
            result_msg,
            reply_markup=main_menu_keyboard(True),
        )
        return True

    return False


# ══════════════════════════════════════════════════════════
# Chat flow helpers
# ══════════════════════════════════════════════════════════

def _build_messages(
    system_prompt: str,
    ctx_items: list[dict],
    user_text: str,
    summary: str = "",
) -> list[dict]:
    """Build the messages array for Ollama."""
    messages = [{"role": "system", "content": system_prompt}]
    if summary:
        messages.append({"role": "system", "content": f"Previous conversation summary:\n{summary}"})
    for item in ctx_items:
        messages.append({"role": "user", "content": item.get("u", "")})
        messages.append({"role": "assistant", "content": item.get("a", "")})
    messages.append({"role": "user", "content": user_text})
    return messages


async def _maybe_summarize(
    uid: int, model: str, ctx_items: list[dict],
    num_ctx: int = 8192, system_prompt: str = "", user_text: str = "",
) -> tuple[list[dict], str]:
    """If context approaches num_ctx limit, summarize older turns."""
    if not ctx_items or len(ctx_items) < 3:
        return ctx_items, ""

    threshold = int(num_ctx * 0.7)
    est_tokens = _estimate_messages_tokens(system_prompt, ctx_items, user_text)

    logger.info("context est_tokens=%d, threshold=%d (num_ctx=%d)", est_tokens, threshold, num_ctx)

    if est_tokens < threshold:
        return ctx_items, ""

    split_at = max(1, len(ctx_items) * 2 // 3)
    old_items = ctx_items[:split_at]
    recent_items = ctx_items[split_at:]

    old_text = "\n".join(
        f"User: {it.get('u', '')}\nAssistant: {it.get('a', '')}" for it in old_items
    )

    try:
        summary = await summarize_context(model, old_text)
        logger.info("compressed %d turns -> summary (%d chars), keeping %d recent", len(old_items), len(summary), len(recent_items))

        # Save compressed content to daily memory
        try:
            from openlama.core.memory import save_daily_entry
            save_daily_entry(summary, source="context_compression")
        except Exception as me:
            logger.warning("failed to save daily memory: %s", me)

        return recent_items, summary
    except Exception as e:
        logger.error("summarize failed: %s", e)
        return ctx_items, ""


async def _do_chat(
    update: Update,
    user: UserState,
    user_text: str,
    images: Optional[list[str]] = None,
    file_context: str = "",
):
    """Core Telegram chat function -- streaming + tools + think mode.

    Uses per-user lock to queue concurrent messages.
    """
    uid = user.telegram_id
    lock = _get_user_lock(uid)
    async with lock:
        await _do_chat_inner(update, user, user_text, images, file_context)


async def _do_chat_inner(
    update: Update,
    user: UserState,
    user_text: str,
    images: Optional[list[str]] = None,
    file_context: str = "",
):
    uid = user.telegram_id
    model = user.selected_model

    ok, msg = await ensure_ollama_running()
    if not ok:
        await update.message.reply_text(f"Ollama connection failed: {msg}")
        return

    # Build prompt
    if file_context:
        full_text = f"{file_context}\n\n{user_text}" if user_text else file_context
    else:
        full_text = user_text

    system_prompt = build_full_system_prompt()
    settings = get_model_settings(uid, model)
    think = bool(user.think_mode) and await model_supports_thinking(model)

    # Context -- auto-compact based on num_ctx
    ctx_items = load_context(uid)
    notify_msg = None
    if len(ctx_items) >= 3:
        pre_len = len(ctx_items)
        ctx_items, summary = await _maybe_summarize(
            uid, model, ctx_items,
            num_ctx=settings.num_ctx,
            system_prompt=system_prompt,
            user_text=full_text,
        )
        if summary and len(ctx_items) < pre_len:
            try:
                notify_msg = await update.message.reply_text(
                    f"🗜 Context auto-compressed: {pre_len} → {len(ctx_items) + 1} turns"
                )
            except Exception:
                pass
    else:
        summary = ""

    # Tools -- filter based on model capabilities
    tools = None
    has_tools = await model_supports_tools(model)
    if has_tools:
        caps = await get_model_capabilities(model)
        has_vision = any(c in caps for c in ("vision", "image", "multimodal"))
        all_tools = format_tools_for_ollama(admin=True)

        tools = []
        for t in all_tools:
            tname = t["function"]["name"]
            if tname == "image_edit" and not has_vision:
                continue
            tools.append(t)

    logger.info("model=%s, has_tools=%s, tools_count=%d, think=%s",
                model, has_tools, len(tools) if tools else 0, think)

    # Augment system prompt with current date/time
    final_system = system_prompt
    from datetime import datetime, timezone, timedelta
    kst = timezone(timedelta(hours=9))
    today = datetime.now(kst).strftime("%Y-%m-%d %H:%M KST")
    final_system += f"\n\nCurrent date/time: {today}"

    messages = _build_messages(final_system, ctx_items, full_text, summary)

    # Send placeholder
    placeholder = await update.message.reply_text("💬 Thinking...")
    result = {}

    try:
        # Stream response
        gen = chat_stream(model, messages, images=images, settings=settings, tools=tools, think=think)
        result = await stream_response_to_message(placeholder, gen, think_mode=think)

        answer = result["content"]
        thinking = result.get("thinking", "")
        tool_calls = result.get("tool_calls", [])
        prompt_tokens = result.get("prompt_tokens", 0)
        completion_tokens = result.get("completion_tokens", 0)
        logger.info("stream result: content_len=%d, thinking_len=%d, tool_calls=%d, tokens=%d+%d",
                     len(answer), len(thinking), len(tool_calls), prompt_tokens, completion_tokens)

        # Handle tool calls (multi-turn loop via core agent)
        if tool_calls:
            # Set chat context for cron tool
            try:
                from openlama.tools.cron_tool import set_chat_context
                set_chat_context(update.effective_chat.id, uid)
            except Exception:
                pass
            await placeholder.edit_text("🔧 Running tools...")
            messages_with_assistant = messages + [{"role": "assistant", "content": answer}]

            async def _on_progress(status_text: str):
                try:
                    await placeholder.edit_text(status_text)
                except Exception:
                    pass

            answer, tool_image_paths, tool_usage = await handle_tool_calls(
                uid, model, messages_with_assistant, tool_calls, settings, think,
                tools=tools, on_progress=_on_progress,
            )
            prompt_tokens += tool_usage.prompt_tokens
            completion_tokens += tool_usage.completion_tokens
            logger.info("tool result answer_len=%d, total_tokens=%d+%d",
                         len(answer), prompt_tokens, completion_tokens)

            # Send generated images via Telegram
            for img_path in tool_image_paths:
                try:
                    p = Path(img_path)
                    if p.exists() and p.stat().st_size > 0:
                        with open(p, "rb") as f:
                            await update.message.reply_photo(photo=f)
                        logger.info("sent tool image: %s", img_path)
                except Exception as img_err:
                    logger.error("failed to send image %s: %s", img_path, img_err)

            # Display final answer (entity-based)
            try:
                text, entities = convert_markdown(answer)
                parts = split_message(text, entities)
                first_text, first_ents = parts[0]
                await placeholder.edit_text(first_text, entities=first_ents)
                for chunk_text, chunk_ents in parts[1:]:
                    await update.message.reply_text(chunk_text, entities=chunk_ents)
            except Exception:
                plain_parts = chunks(answer)
                await placeholder.edit_text(plain_parts[0])
                for part in plain_parts[1:]:
                    await update.message.reply_text(part)

        if not answer:
            answer = "Response is empty."

    except Exception as e:
        err_str = str(e).lower()
        # Auto-trim on context overflow (400 errors)
        if "400" in str(e) and len(messages) > 3:
            logger.warning("Telegram: context overflow, trimming and retrying")
            for retry in range(3):
                system_msg = messages[0]
                user_msg = messages[-1]
                context_msgs = messages[1:-1]
                if len(context_msgs) <= 2:
                    messages = [system_msg, user_msg]
                    save_context(uid, [])
                    ctx_items = []
                else:
                    half = max(2, len(context_msgs) // 2)
                    context_msgs = context_msgs[half:]
                    messages = [system_msg] + context_msgs + [user_msg]
                    keep = len(context_msgs) // 2
                    ctx_items = ctx_items[-keep:] if keep > 0 else []
                    save_context(uid, ctx_items)

                try:
                    await placeholder.edit_text("🔄 Retrying with trimmed context...")
                    gen = chat_stream(model, messages, images=images, settings=settings, tools=tools, think=think)
                    result = await stream_response_to_message(placeholder, gen, think_mode=think)
                    answer = result["content"]
                    prompt_tokens = result.get("prompt_tokens", 0)
                    completion_tokens = result.get("completion_tokens", 0)
                    tool_calls = []
                    break
                except Exception:
                    if retry == 2:
                        logger.error("chat error after retries: %s", e, exc_info=True)
                        await placeholder.edit_text(f"Model response failed: {e}")
                        return
        else:
            logger.error("chat error: %s", e, exc_info=True)
            await placeholder.edit_text(f"Model response failed: {e}")
            return

    # Save context — include tool call history if any
    tool_names = []
    if tool_calls:
        for tc in tool_calls:
            fn = tc.get("function", {})
            tool_names.append(fn.get("name", "unknown"))

    ctx_user = full_text
    ctx_answer = answer
    if tool_names:
        ctx_answer = f"[Tools used: {', '.join(tool_names)}]\n{answer}"
    if images:
        ctx_user = f"[image] {user_text}"

    ctx_entry = {"u": ctx_user[:10000], "a": ctx_answer[:10000]}
    ctx_items.append(ctx_entry)
    save_context(uid, ctx_items)

    # Show context usage bar (if enabled)
    try:
        show_bar = get_config("show_token_stats", "true").lower() in ("true", "1", "yes")
        if show_bar:
            # Use streaming prompt_tokens (base context, excludes tool rounds)
            # This is the actual token count Ollama used for the initial request
            base_prompt = result.get("prompt_tokens", 0) if result else 0
            base_completion = result.get("completion_tokens", 0) if result else 0
            if base_prompt > 0:
                context_used = base_prompt + base_completion
                status_bar = build_context_bar(context_used, settings.num_ctx, len(ctx_items))
            else:
                # Fallback to estimation
                ctx_est = _estimate_messages_tokens(final_system, ctx_items)
                status_bar = build_context_bar(ctx_est, settings.num_ctx, len(ctx_items))
            # Line 2: total request tokens (including tool rounds)
            total_req = prompt_tokens + completion_tokens
            if total_req > 0:
                status_bar += f"\n💬 This request: {prompt_tokens:,} in + {completion_tokens:,} out = {total_req:,}"
            await update.message.reply_text(status_bar)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════
# Command handlers
# ══════════════════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = get_user(uid)
    logged_in = is_authed(user)
    await update.message.reply_text(
        "🤖 <b>Openlama</b>\n\n"
        + ("✅ Authenticated\nUse the menu below." if logged_in else "🔑 Please authenticate with /login."),
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(logged_in),
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = get_user(uid)
    logged_in = is_authed(user)
    await update.message.reply_text(
        HELP_TEXT,
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(logged_in),
    )


async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = get_user(uid)
    if is_authed(user):
        await update.message.reply_text(
            "Already authenticated.",
            reply_markup=main_menu_keyboard(True),
        )
        return
    if is_login_locked(user):
        await update.message.reply_text(f"Login locked: {user.login_lock_until - now_ts()}s remaining")
        return
    update_user(uid, state="await_password")
    await update.message.reply_text("🔑 Enter admin password.")


async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    update_user(uid, auth_until=0, state="")
    _save_and_clear(uid)
    await update.message.reply_text(
        "🔓 Logged out",
        reply_markup=main_menu_keyboard(False),
    )


async def setpassword(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await require_auth(update)
    if not user:
        return
    update_user(user.telegram_id, state="await_current_password_for_change")
    await update.message.reply_text("Enter your current password.")


async def models_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await require_auth(update)
    if not user:
        return

    ok, msg = await ensure_ollama_running()
    if not ok:
        await update.message.reply_text(f"Ollama connection failed: {msg}")
        return

    try:
        models = await fetch_models()
    except Exception as e:
        await update.message.reply_text(f"Failed to fetch models: {e}")
        return

    if not models:
        await update.message.reply_text("No models installed. Use /pull to install one.")
        return

    display_map = await get_model_display_map(models)
    await update.message.reply_text(
        "🤖 <b>Select Model</b>\n"
        "👁 Vision | 🔧 Tools | 💭 Think | 💬 Text Only",
        parse_mode="HTML",
        reply_markup=model_keyboard(models, 0, display_map),
    )


async def model_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await require_auth(update)
    if not user:
        return

    selected = user.selected_model or "(none selected)"
    if not user.selected_model:
        await update.message.reply_text(
            f"Current model: {selected}\nSelect a model with /models.",
            reply_markup=main_menu_keyboard(True),
        )
        return

    try:
        caps = await get_model_capabilities(user.selected_model)
        cap_badges = []
        if any(c in caps for c in ("vision", "image", "multimodal")):
            cap_badges.append("👁 Image Input")
        if "tools" in caps:
            cap_badges.append("🔧 Tool Calling")
        if "thinking" in caps:
            cap_badges.append("💭 Think Mode")
        if "audio" in caps:
            cap_badges.append("🎵 Audio Input")
        cap_text = "\n".join(f"  • {b}" for b in cap_badges) if cap_badges else "  • 💬 Text Only"

        ms = get_model_settings(user.telegram_id, user.selected_model)
        await update.message.reply_text(
            f"🤖 <b>Current Model: {selected}</b>\n\n"
            f"<b>Capabilities:</b>\n{cap_text}\n\n"
            f"<b>Parameters:</b>\n"
            f"  • temperature: {ms.temperature}\n"
            f"  • num_ctx: {ms.num_ctx}\n"
            f"  • num_predict: {ms.num_predict}\n"
            f"  • think: {'ON' if user.think_mode else 'OFF'}",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(True),
        )
    except Exception:
        await update.message.reply_text(f"Current model: {selected}")


async def pull_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await require_auth(update)
    if not user:
        return

    if not context.args:
        await update.message.reply_text(
            "📥 <b>Install Model</b>\n\n"
            "Usage: /pull &lt;model&gt;\n\n"
            "Examples:\n"
            "• /pull gemma4:26b\n"
            "• /pull gemma4:e4b\n"
            "• /pull llama3.1:8b\n"
            "• /pull qwen2.5:14b",
            parse_mode="HTML",
        )
        return

    model = " ".join(context.args).strip()
    uid = user.telegram_id

    st = get_pull_state(uid)
    if st and st.get("status") == "running":
        await update.message.reply_text(f"Installation already in progress: {st.get('model')} /pullstatus")
        return

    set_pull_state(uid, status="queued", model=model, progress=0, detail="queued")
    asyncio.create_task(pull_model_stream(uid, model))
    await update.message.reply_text(f"📥 Installation started: {model}\nCheck progress: /pullstatus")


async def pullstatus_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await require_auth(update)
    if not user:
        return

    st = get_pull_state(user.telegram_id)
    if not st:
        await update.message.reply_text("No installation history.")
        return

    status_emoji = {"queued": "⏳", "running": "⬇️", "done": "✅", "failed": "❌"}.get(st.get("status", ""), "❓")
    progress = st.get("progress", 0)
    bar_len = 20
    filled = int(bar_len * progress / 100)
    bar = "█" * filled + "░" * (bar_len - filled)

    await update.message.reply_text(
        f"{status_emoji} <b>Model Installation Status</b>\n\n"
        f"Model: {st.get('model', '-')}\n"
        f"Status: {st.get('status', '-')}\n"
        f"Progress: [{bar}] {progress}%\n"
        f"Detail: {st.get('detail', '-')}",
        parse_mode="HTML",
    )


async def rm_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await require_auth(update)
    if not user:
        return

    ok, msg = await ensure_ollama_running()
    if not ok:
        await update.message.reply_text(f"Ollama connection failed: {msg}")
        return

    if context.args:
        model = " ".join(context.args).strip()
        try:
            await delete_model(model)
        except Exception as e:
            await update.message.reply_text(f"Delete failed: {e}")
            return
        if user.selected_model == model:
            update_user(user.telegram_id, selected_model="")
        await update.message.reply_text(f"🗑 Deleted: {model}")
        return

    try:
        models = await fetch_models()
    except Exception as e:
        await update.message.reply_text(f"Failed to fetch models: {e}")
        return

    if not models:
        await update.message.reply_text("No models to delete.")
        return

    display_map = await get_model_display_map(models)
    await update.message.reply_text(
        "🗑 <b>Select a model to delete</b>\n✅ Currently selected model",
        parse_mode="HTML",
        reply_markup=rm_model_keyboard(models, 0, user.selected_model, display_map),
    )


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = get_user(uid)
    auth_left = max(0, user.auth_until - now_ts())
    ms = get_model_settings(uid, user.selected_model) if user.selected_model else None

    text = (
        f"📋 <b>Session Status</b>\n\n"
        f"Auth: {'✅ Valid' if auth_left else '❌ Expired'} ({auth_left}s)\n"
        f"Model: {user.selected_model or '(none selected)'}\n"
        f"System Prompt: {'Custom' if user.system_prompt else 'Default'}\n"
        f"Think Mode: {'ON 💭' if user.think_mode else 'OFF'}"
    )
    if ms:
        text += (
            f"\n\n<b>Model Parameters:</b>\n"
            f"  temperature: {ms.temperature} | top_p: {ms.top_p}\n"
            f"  num_ctx: {ms.num_ctx} | num_predict: {ms.num_predict}"
        )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(is_authed(user)),
    )


async def clear_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    _save_and_clear(uid)
    await update.message.reply_text(
        "🗑 Context cleared",
        reply_markup=main_menu_keyboard(is_authed(get_user(uid))),
    )


async def export_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await require_auth(update)
    if not user:
        return

    items = load_context(user.telegram_id)
    if not items:
        await update.message.reply_text("No conversation history to export.")
        return

    lines = []
    for i, item in enumerate(items, 1):
        lines.append(f"--- Turn {i} ---")
        lines.append(f"User: {item.get('u', '')}")
        lines.append(f"Assistant: {item.get('a', '')}")
        lines.append("")

    content = "\n".join(lines)
    buf = io.BytesIO(content.encode("utf-8"))
    buf.name = "conversation_export.txt"
    await update.message.reply_document(document=buf, caption="📤 Conversation Export")


# ══════════════════════════════════════════════════════════
# Message handlers (with per-user queue)
# ══════════════════════════════════════════════════════════

_user_locks: dict[int, asyncio.Lock] = {}


def _get_user_lock(uid: int) -> asyncio.Lock:
    if uid not in _user_locks:
        _user_locks[uid] = asyncio.Lock()
    return _user_locks[uid]


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return

    uid = update.effective_user.id
    text = (update.message.text or "").strip()
    user = get_user(uid)

    # Password flows
    if await _handle_password_flow(update, user, text):
        return

    # Profile setup flows
    if await _handle_profile_setup(update, user, text):
        return

    if not is_authed(user):
        await update.message.reply_text("Authentication required: /login", reply_markup=main_menu_keyboard(False))
        return

    # AllowList check
    if not is_allowed(uid):
        logger.info("Blocked message from uid=%d (not in allow list)", uid)
        return

    if not user.selected_model:
        await update.message.reply_text("Please select a model first: /models", reply_markup=main_menu_keyboard(True))
        return

    # Block agent if profile onboarding not complete
    if not is_profile_setup_done():
        from openlama.core.prompt_builder import _has_real_content, _prompts_dir
        from openlama.core.onboarding import LANGUAGES
        d = _prompts_dir()
        if not _has_real_content(d / "USERS.md"):
            lang_list = "\n".join(f"  {i}. {name}" for i, (_, name) in enumerate(LANGUAGES, 1))
            update_user(uid, state="await_profile_language")
            await update.message.reply_text(
                "Profile setup required (Step 1/3).\n\n"
                f"Select your language:\n{lang_list}\n\n"
                f"Reply with a number or type a language name.",
            )
        elif not _has_real_content(d / "SOUL.md"):
            update_user(uid, state="await_profile_soul")
            await update.message.reply_text(
                "One more step (Step 3/3).\n\n"
                f"{PROFILE_QUESTIONS['soul']}",
            )
        return

    # Group chat: only respond if mentioned or replied to
    if update.message.chat.type in ("group", "supergroup"):
        bot_username = (await context.bot.get_me()).username
        is_mentioned = bot_username and f"@{bot_username}" in text
        is_reply = (
            update.message.reply_to_message
            and update.message.reply_to_message.from_user
            and update.message.reply_to_message.from_user.is_bot
        )
        if not is_mentioned and not is_reply:
            return
        if bot_username:
            text = text.replace(f"@{bot_username}", "").strip()

    await _do_chat(update, user, text)


async def on_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle images, audio, video."""
    if not update.message or not update.effective_user:
        return

    uid = update.effective_user.id
    user = get_user(uid)

    if not is_authed(user):
        await update.message.reply_text("Authentication required: /login")
        return
    if not is_allowed(uid):
        return
    if not user.selected_model:
        await update.message.reply_text("Please select a model first: /models")
        return

    # Determine file type and get file
    file_id = None
    file_type = "unknown"

    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        file_type = "image"
    elif update.message.audio:
        file_id = update.message.audio.file_id
        file_type = "audio"
    elif update.message.voice:
        file_id = update.message.voice.file_id
        file_type = "audio"
    elif update.message.video:
        file_id = update.message.video.file_id
        file_type = "video"
    elif update.message.video_note:
        file_id = update.message.video_note.file_id
        file_type = "video"
    elif update.message.document:
        file_id = update.message.document.file_id
        mime = update.message.document.mime_type or ""
        fname = update.message.document.file_name or ""
        if mime.startswith("image/"):
            file_type = "image"
        elif mime.startswith("audio/"):
            file_type = "audio"
        elif mime.startswith("video/"):
            file_type = "video"
        else:
            file_type = detect_file_type(mime, fname)

    if not file_id:
        await update.message.reply_text("File not found.")
        return

    caption = (update.message.caption or "").strip()

    # Check model capabilities
    if file_type == "image":
        supports, reason = await model_supports_images(user.selected_model)
        if not supports:
            await update.message.reply_text(
                f"Current model does not support images.\n"
                f"Model: {user.selected_model}\nReason: {reason}\n\n"
                f"Select a 👁 model from /models."
            )
            return

    try:
        tg_file = await context.bot.get_file(file_id)
        file_bytes = bytes(await tg_file.download_as_bytearray())
    except Exception as e:
        await update.message.reply_text(f"File download failed: {e}")
        return

    # Process by type
    if file_type == "image":
        image_b64 = base64.b64encode(file_bytes).decode("utf-8")
        prompt = caption or "Analyze this image."

        # Save to temp for image_edit tool
        upload_dir = Path(get_config("upload_temp_dir"))
        try:
            upload_dir.mkdir(parents=True, exist_ok=True)
            for old in upload_dir.glob(f"{uid}_*"):
                old.unlink(missing_ok=True)
            ext = ".png"
            if file_bytes[:3] == b'\xff\xd8\xff':
                ext = ".jpg"
            elif file_bytes[:4] == b'\x89PNG':
                ext = ".png"
            elif file_bytes[:4] == b'RIFF':
                ext = ".webp"
            tmp_path = upload_dir / f"{uid}_{int(time.time())}{ext}"
            tmp_path.write_bytes(file_bytes)
            prompt += f"\n[Uploaded image path: {tmp_path}]"
        except Exception as e:
            logger.warning("failed to save temp image: %s", e)

        await _do_chat(update, user, prompt, images=[image_b64])

    elif file_type == "audio":
        from openlama.utils.file_processor import transcribe_audio
        doc = update.message.document
        audio_fname = doc.file_name if doc else "audio.ogg"
        await update.message.reply_text("🎤 Transcribing audio...")
        transcript = transcribe_audio(file_bytes, audio_fname)
        if transcript.startswith("["):
            # Error or no speech
            await update.message.reply_text(transcript)
            return
        file_context = f"[Voice/Audio transcription]\n{transcript}"
        prompt = caption or transcript
        await _do_chat(update, user, prompt, file_context=file_context if caption else "")

    elif file_type == "video":
        frames = process_video(file_bytes, max_frames=8)
        if not frames:
            await update.message.reply_text("Video frame extraction failed. Check if ffmpeg is installed.")
            return
        prompt = caption or f"Analyze this video. ({len(frames)} frames total)"
        await _do_chat(update, user, prompt, images=frames)

    else:
        await update.message.reply_text("Unsupported file format.")


async def _handle_archive(update: Update, user, file_bytes: bytes, fname: str, caption: str):
    """Handle ZIP archive uploads — extract and check for skills or pass contents to AI."""
    from openlama.utils.file_processor import extract_archive
    from openlama.core.skills import save_skill, _skills_dir
    import shutil

    status, extracted_dir = extract_archive(file_bytes, fname)
    if extracted_dir is None:
        await update.message.reply_text(f"Archive error: {status}")
        return

    try:
        # Check for SKILL.md files — install as skills
        skill_files = list(extracted_dir.rglob("SKILL.md"))
        if skill_files:
            skills_base = _skills_dir()
            skills_base.mkdir(parents=True, exist_ok=True)
            installed = []
            for sf in skill_files:
                skill_dir = sf.parent
                skill_name = skill_dir.name
                dest = skills_base / skill_name
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(skill_dir, dest)
                installed.append(skill_name)

            from openlama.core.skills import _invalidate_cache
            _invalidate_cache()

            names = ", ".join(installed)
            await update.message.reply_text(
                f"✅ Skill{'s' if len(installed) > 1 else ''} installed: {names}\n"
                f"Use /skills to see all installed skills."
            )
            return

        # No skills found — list contents and pass to AI
        all_files = [str(f.relative_to(extracted_dir)) for f in extracted_dir.rglob("*") if f.is_file()]
        file_list = "\n".join(f"  • {f}" for f in all_files[:50])

        # Read text files for context
        text_parts = []
        for f in extracted_dir.rglob("*"):
            if f.is_file() and f.stat().st_size < 100000:
                try:
                    content = f.read_text(encoding="utf-8")
                    rel = f.relative_to(extracted_dir)
                    text_parts.append(f"[{rel}]\n```\n{content[:10000]}\n```")
                except (UnicodeDecodeError, Exception):
                    continue
            if len(text_parts) >= 10:
                break

        file_context = f"[Archive: {fname}]\nFiles ({len(all_files)}):\n{file_list}"
        if text_parts:
            file_context += "\n\n" + "\n\n".join(text_parts)

        prompt = caption or "Analyze the contents of this archive."
        await _do_chat(update, user, prompt, file_context=file_context[:50000])

    finally:
        shutil.rmtree(extracted_dir, ignore_errors=True)


async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle non-image documents (PDF, text, code, archives)."""
    if not update.message or not update.effective_user or not update.message.document:
        return

    uid = update.effective_user.id
    user = get_user(uid)

    if not is_authed(user):
        await update.message.reply_text("Authentication required: /login")
        return
    if not is_allowed(uid):
        return
    if not user.selected_model:
        await update.message.reply_text("Please select a model first: /models")
        return

    doc = update.message.document
    mime = doc.mime_type or ""
    fname = doc.file_name or ""
    file_type = detect_file_type(mime, fname)
    caption = (update.message.caption or "").strip()

    # Image documents are handled by on_media
    if file_type == "image":
        await on_media(update, context)
        return

    try:
        tg_file = await context.bot.get_file(doc.file_id)
        file_bytes = bytes(await tg_file.download_as_bytearray())
    except Exception as e:
        await update.message.reply_text(f"File download failed: {e}")
        return

    if file_type == "pdf":
        supports_img, _ = await model_supports_images(user.selected_model)
        if supports_img:
            images = process_pdf(file_bytes, max_pages=10)
            if not images:
                await update.message.reply_text("PDF processing failed. Check if PyMuPDF is installed.")
                return
            prompt = caption or f"Analyze this PDF document. ({len(images)} pages total)"
            await _do_chat(update, user, prompt, images=images)
        else:
            try:
                import fitz
                doc_pdf = fitz.open(stream=file_bytes, filetype="pdf")
                text_parts = []
                for page in doc_pdf:
                    text_parts.append(page.get_text())
                doc_pdf.close()
                pdf_text = "\n".join(text_parts)[:50000]
                file_context = f"[PDF Document: {fname}]\n```\n{pdf_text}\n```"
                prompt = caption or "Analyze the content of this document."
                await _do_chat(update, user, prompt, file_context=file_context)
            except ImportError:
                await update.message.reply_text("PyMuPDF is required for PDF processing.")
            except Exception as e:
                await update.message.reply_text(f"PDF text extraction failed: {e}")
        return

    if file_type == "text":
        file_context = f"[File: {fname}]\n{process_text_file(file_bytes, fname)}"
        prompt = caption or "Analyze the content of this file."
        await _do_chat(update, user, prompt, file_context=file_context)
        return

    if file_type == "audio":
        await on_media(update, context)
        return

    if file_type == "video":
        await on_media(update, context)
        return

    if file_type == "archive":
        await _handle_archive(update, user, file_bytes, fname, caption)
        return

    # Unknown file type -- check if binary or text
    from openlama.utils.file_processor import is_binary
    if is_binary(file_bytes):
        await update.message.reply_text(
            f"Unsupported binary file: {fname}\n\n"
            "Supported formats: images, PDF, text/code, audio, video, ZIP archives."
        )
        return

    # Likely text — try to decode
    try:
        text_content = file_bytes.decode("utf-8", errors="replace")[:30000]
        file_context = f"[File: {fname}]\n```\n{text_content}\n```"
        prompt = caption or "Review the content of this file."
        await _do_chat(update, user, prompt, file_context=file_context)
    except Exception:
        await update.message.reply_text("Unsupported file format.")


# ══════════════════════════════════════════════════════════
# Callback query handler
# ══════════════════════════════════════════════════════════

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not update.effective_user:
        return
    await q.answer()

    uid = update.effective_user.id
    data = q.data or ""

    if data == "noop":
        return

    # ── Login button (no auth required) ──
    if data == "cmd:login":
        user = get_user(uid)
        if is_authed(user):
            await q.edit_message_text("Already authenticated.", reply_markup=main_menu_keyboard(True))
            return
        update_user(uid, state="await_password")
        await q.edit_message_text("🔑 Enter admin password.")
        return

    if data == "cmd:help":
        user = get_user(uid)
        await q.edit_message_text(HELP_TEXT, parse_mode="HTML", reply_markup=main_menu_keyboard(is_authed(user)))
        return

    # ── Auth required callbacks ──
    user = get_user(uid)
    if not is_authed(user):
        await q.edit_message_text("Session expired. /login", reply_markup=main_menu_keyboard(False))
        return

    # ── Menu ──
    if data == "cmd:menu":
        await q.edit_message_text(
            "🤖 <b>Openlama</b>\n\nSelect an option.",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(True),
        )
        return

    # ── Clear context ──
    if data == "clear_ctx":
        _save_and_clear(uid)
        await q.edit_message_text("🗑 Context cleared", reply_markup=main_menu_keyboard(True))
        return

    # ── Context status ──
    if data == "cmd:context_status":
        text, kb = await build_context_status(uid, user)
        await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
        return

    # ── Context compress ──
    if data == "ctx:compress":
        await q.edit_message_text("🗜 Compressing context...")
        result_text = await compress_context(uid, user)
        user = get_user(uid)
        status_text, kb = await build_context_status(uid, user)
        await q.edit_message_text(
            f"{result_text}\n\n{'─' * 30}\n\n{status_text}",
            parse_mode="HTML",
            reply_markup=kb,
        )
        return

    # ── Model selection ──
    if data.startswith("model:"):
        model = data.split(":", 1)[1]
        old_model = user.selected_model
        update_user(uid, selected_model=model)
        if old_model and old_model != model:
            await unload_model(old_model)

        caps = await get_model_capabilities(model)
        max_ctx = await get_model_max_context(model)

        cap_lines = []
        has_vision = any(c in caps for c in ("vision", "image", "multimodal"))
        has_tools = "tools" in caps
        has_thinking = "thinking" in caps

        if has_vision:
            cap_lines.append("  👁 Image/PDF analysis, image editing")
        if has_tools:
            cap_lines.append("  🔧 Tool use (web search, code exec, files, Git, image gen, etc.)")
        if has_thinking:
            cap_lines.append("  💭 Reasoning display (Think Mode)")
        if "audio" in caps:
            cap_lines.append("  🎵 Audio input analysis")
        if not cap_lines:
            cap_lines.append("  💬 Text conversation only")

        warnings = []
        if not has_tools:
            warnings.append("⚠️ No tool support — web search/code exec etc. unavailable")
        if not has_vision:
            warnings.append("⚠️ No vision support — image analysis/editing unavailable")

        text = (
            f"✅ Selected model: <b>{model}</b>\n\n"
            f"<b>Capabilities:</b>\n" + "\n".join(cap_lines)
        )
        if max_ctx > 0:
            text += f"\n  📏 Max context: {max_ctx:,} tokens"
        if warnings:
            text += "\n\n" + "\n".join(warnings)
        text += "\n\nSend a message and this model will respond."

        await q.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(True),
        )
        return

    # ── Model pages ──
    if data.startswith("models_page:"):
        page = int(data.split(":", 1)[1])
        ok, msg = await ensure_ollama_running()
        if not ok:
            await q.edit_message_text(f"Ollama connection failed: {msg}")
            return
        models = await fetch_models()
        display_map = await get_model_display_map(models)
        await q.edit_message_text(
            "🤖 <b>Select Model</b>\n"
            "👁 Vision | 🔧 Tools | 💭 Think | 💬 Text",
            parse_mode="HTML",
            reply_markup=model_keyboard(models, page, display_map),
        )
        return

    # ── Delete model ──
    if data.startswith("rm_model:"):
        model = data.split(":", 1)[1]
        ok, msg = await ensure_ollama_running()
        if not ok:
            await q.edit_message_text(f"Ollama connection failed: {msg}")
            return
        try:
            await delete_model(model)
        except Exception as e:
            await q.edit_message_text(f"Delete failed: {e}")
            return
        if user.selected_model == model:
            update_user(uid, selected_model="")
        await q.edit_message_text(f"🗑 Deleted: {model}", reply_markup=main_menu_keyboard(True))
        return

    if data.startswith("rm_page:"):
        page = int(data.split(":", 1)[1])
        ok, msg = await ensure_ollama_running()
        if not ok:
            await q.edit_message_text(f"Ollama connection failed: {msg}")
            return
        models = await fetch_models()
        display_map = await get_model_display_map(models)
        await q.edit_message_reply_markup(
            reply_markup=rm_model_keyboard(models, page, user.selected_model, display_map)
        )
        return

    if data == "rm_cancel":
        await q.edit_message_text("Model deletion cancelled.", reply_markup=main_menu_keyboard(True))
        return

    # ── Command shortcuts ──
    if data == "cmd:models":
        ok, msg = await ensure_ollama_running()
        if not ok:
            await q.edit_message_text(f"Ollama connection failed: {msg}")
            return
        try:
            models = await fetch_models()
        except Exception as e:
            await q.edit_message_text(f"Failed to fetch models: {e}")
            return
        if not models:
            await q.edit_message_text("No models installed.", reply_markup=main_menu_keyboard(True))
            return
        display_map = await get_model_display_map(models)
        await q.edit_message_text(
            "🤖 <b>Select Model</b>\n"
            "👁 Vision | 🔧 Tools | 💭 Think | 💬 Text",
            parse_mode="HTML",
            reply_markup=model_keyboard(models, 0, display_map),
        )
        return

    if data == "cmd:model":
        selected = user.selected_model or "(none selected)"
        await q.edit_message_text(f"📊 Current model: {selected}", reply_markup=main_menu_keyboard(True))
        return

    if data == "cmd:settings":
        if not user.selected_model:
            await q.edit_message_text("Please select a model first: /models", reply_markup=main_menu_keyboard(True))
            return
        from openlama.channels.telegram.settings import settings_keyboard
        await q.edit_message_text(
            f"⚙️ <b>Model Settings: {user.selected_model}</b>",
            parse_mode="HTML",
            reply_markup=settings_keyboard(uid, user.selected_model),
        )
        return

    if data == "cmd:systemprompt":
        from openlama.core.prompt_builder import _prompts_dir
        d = _prompts_dir()
        files = ["SOUL.md", "USERS.md", "MEMORY.md"]
        buttons = []
        for name in files:
            p = d / name
            exists = p.exists() and p.stat().st_size > 0
            label = f"{'📄' if exists else '📝'} {name}"
            buttons.append([InlineKeyboardButton(label, callback_data=f"prompt_view:{name}")])
        buttons.append([InlineKeyboardButton("🏠 Menu", callback_data="cmd:menu")])
        await q.edit_message_text(
            "📋 <b>Prompt Files</b>\n\n"
            "Select a file to view and edit.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    if data.startswith("prompt_view:"):
        fname = data.split(":", 1)[1]
        from openlama.core.prompt_builder import _prompts_dir
        p = _prompts_dir() / fname
        if p.exists():
            content = p.read_text(encoding="utf-8")
            # Telegram message limit ~4096 chars
            if len(content) > 3500:
                content = content[:3500] + "\n\n... (truncated)"
        else:
            content = "(empty)"

        await q.edit_message_text(
            f"📄 <b>{fname}</b>\n\n"
            f"<code>{content}</code>\n\n"
            f"To edit: copy the content above, modify it, and send it as a message.\n"
            f"The next message you send will overwrite this file.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✏️ Edit this file", callback_data=f"prompt_edit:{fname}")],
                [InlineKeyboardButton("⬅️ Back", callback_data="cmd:systemprompt")],
            ]),
        )
        return

    if data.startswith("prompt_edit:"):
        fname = data.split(":", 1)[1]
        update_user(uid, state=f"await_prompt_edit|{fname}")
        await q.edit_message_text(
            f"✏️ <b>Editing {fname}</b>\n\n"
            f"Send the new content as your next message.\n"
            f"It will replace the entire file.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Cancel", callback_data="cmd:systemprompt")],
            ]),
        )
        return

    if data == "cmd:think_toggle":
        new_val = 0 if user.think_mode else 1
        update_user(uid, think_mode=new_val)
        status = "ON 💭" if new_val else "OFF"
        await q.edit_message_text(f"💭 Think Mode: {status}", reply_markup=main_menu_keyboard(True))
        return

    if data == "cmd:think_on":
        update_user(uid, think_mode=1)
        await q.edit_message_text("💭 Think Mode ON", reply_markup=main_menu_keyboard(True))
        return

    if data == "cmd:think_off":
        update_user(uid, think_mode=0)
        await q.edit_message_text("💭 Think Mode OFF", reply_markup=main_menu_keyboard(True))
        return

    if data == "cmd:status":
        auth_left = max(0, user.auth_until - now_ts())
        await q.edit_message_text(
            f"📋 <b>Session Status</b>\n\n"
            f"Auth: {'✅ Valid' if auth_left else '❌ Expired'} ({auth_left}s)\n"
            f"Model: {user.selected_model or '(none selected)'}\n"
            f"Think: {'ON 💭' if user.think_mode else 'OFF'}",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(True),
        )
        return

    if data == "cmd:logout":
        update_user(uid, auth_until=0, state="")
        _save_and_clear(uid)
        await q.edit_message_text("🔓 Logged out", reply_markup=main_menu_keyboard(False))
        return

    if data == "cmd:export":
        items = load_context(uid)
        if not items:
            await q.edit_message_text("No conversation history to export.", reply_markup=main_menu_keyboard(True))
            return
        lines = []
        for i, item in enumerate(items, 1):
            lines.append(f"--- Turn {i} ---\nUser: {item.get('u', '')}\nAssistant: {item.get('a', '')}\n")
        content = "\n".join(lines)
        buf = io.BytesIO(content.encode("utf-8"))
        buf.name = "conversation_export.txt"
        await q.message.reply_document(document=buf, caption="📤 Conversation History")
        return

    if data == "cmd:pull_prompt":
        await q.edit_message_text(
            "📥 <b>Install Model</b>\n\n"
            "Use /pull &lt;model_name&gt; to install.\n\n"
            "Examples:\n"
            "• /pull gemma4:26b\n"
            "• /pull gemma4:e4b\n"
            "• /pull llama3.1:8b",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(True),
        )
        return

    if data == "cmd:rm":
        ok, msg = await ensure_ollama_running()
        if not ok:
            await q.edit_message_text(f"Ollama connection failed: {msg}")
            return
        try:
            models = await fetch_models()
        except Exception as e:
            await q.edit_message_text(f"Failed to fetch models: {e}")
            return
        if not models:
            await q.edit_message_text("No models to delete.", reply_markup=main_menu_keyboard(True))
            return
        display_map = await get_model_display_map(models)
        await q.edit_message_text(
            "🗑 <b>Select Model to Delete</b>\n✅ Currently selected",
            parse_mode="HTML",
            reply_markup=rm_model_keyboard(models, 0, user.selected_model, display_map),
        )
        return

    if data == "cmd:ollama":
        from openlama.channels.telegram.admin import ollama_menu_keyboard
        await q.edit_message_text(
            "🖥 <b>Ollama Server Management</b>",
            parse_mode="HTML",
            reply_markup=ollama_menu_keyboard(),
        )
        return

    # ── ComfyUI management ──
    if data == "cmd:comfyui":
        from openlama.channels.telegram.admin import show_comfyui_status
        await show_comfyui_status(q)
        return

    if data.startswith("comfyui:"):
        from openlama.channels.telegram.admin import handle_comfyui_callback
        await handle_comfyui_callback(q, uid, data)
        return

    # ── Session management ──
    if data == "cmd:session":
        auth_left = max(0, user.auth_until - now_ts())
        hours = auth_left // 3600
        mins = (auth_left % 3600) // 60
        ms = None
        if user.selected_model:
            ms = get_model_settings(uid, user.selected_model)

        text = (
            f"📋 <b>Session Management</b>\n\n"
            f"🔐 Auth: {'✅ Valid' if auth_left > 0 else '❌ Expired'}\n"
            f"⏱ Remaining: {hours}h {mins}m\n"
            f"🤖 Model: {user.selected_model or '(none selected)'}\n"
            f"💬 System Prompt: {'Custom' if user.system_prompt else 'Default'}\n"
            f"🧠 Think Mode: {'ON' if user.think_mode else 'OFF'}"
        )
        if ms:
            text += (
                f"\n\n<b>Model Parameters:</b>\n"
                f"  temperature: {ms.temperature} | top_p: {ms.top_p}\n"
                f"  num_ctx: {ms.num_ctx:,} | num_predict: {ms.num_predict:,}"
            )

        await q.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🔄 Extend Session (+24h)", callback_data="session:extend"),
                    InlineKeyboardButton("🗑 Clear Context", callback_data="clear_ctx"),
                ],
                [InlineKeyboardButton("🏠 Menu", callback_data="cmd:menu")],
            ]),
        )
        return

    if data == "session:extend":
        session_ttl = get_config_int("session_ttl_sec", 86400)
        new_until = now_ts() + session_ttl
        update_user(uid, auth_until=new_until)
        hours = session_ttl // 3600
        await q.edit_message_text(
            f"✅ Session extended by {hours} hours.",
            reply_markup=main_menu_keyboard(True),
        )
        return

    # ── Ollama admin callbacks ──
    if data.startswith("ollama:"):
        from openlama.channels.telegram.admin import handle_ollama_callback
        await handle_ollama_callback(q, uid, data)
        return

    # ── Settings callbacks ──
    if data.startswith("set_"):
        from openlama.channels.telegram.settings import handle_settings_callback
        await handle_settings_callback(q, uid, data, user)
        return


# ══════════════════════════════════════════════════════════
# Post-init: register bot commands
# ══════════════════════════════════════════════════════════

async def post_init(app):
    await app.bot.set_my_commands([
        BotCommand("start", "Start / Main menu"),
        BotCommand("help", "User guide"),
        BotCommand("login", "Password authentication"),
        BotCommand("logout", "Log out"),
        BotCommand("models", "List / select models"),
        BotCommand("model", "Current model info"),
        BotCommand("pull", "Install model (/pull name)"),
        BotCommand("pullstatus", "Installation progress"),
        BotCommand("rm", "Delete model"),
        BotCommand("settings", "Model parameter settings"),
        BotCommand("systemprompt", "System prompt settings"),
        BotCommand("think", "Think mode on/off"),
        BotCommand("clear", "Clear context"),
        BotCommand("status", "Session status"),
        BotCommand("ollama", "Ollama server management"),
        BotCommand("export", "Export conversation"),
        BotCommand("setpassword", "Change password"),
    ])


# ══════════════════════════════════════════════════════════
# Handler registration
# ══════════════════════════════════════════════════════════

def register_all_handlers(app: Application):
    """Register all command, callback, and message handlers."""
    from openlama.channels.telegram.settings import systemprompt_cmd, think_cmd, settings_cmd
    from openlama.channels.telegram.admin import ollama_cmd

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("login", login))
    app.add_handler(CommandHandler("logout", logout))
    app.add_handler(CommandHandler("setpassword", setpassword))
    app.add_handler(CommandHandler("models", models_cmd))
    app.add_handler(CommandHandler("model", model_cmd))
    app.add_handler(CommandHandler("pull", pull_cmd))
    app.add_handler(CommandHandler("pullstatus", pullstatus_cmd))
    app.add_handler(CommandHandler("rm", rm_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("clear", clear_cmd))
    app.add_handler(CommandHandler("settings", settings_cmd))
    app.add_handler(CommandHandler("systemprompt", systemprompt_cmd))
    app.add_handler(CommandHandler("think", think_cmd))
    app.add_handler(CommandHandler("ollama", ollama_cmd))
    app.add_handler(CommandHandler("export", export_cmd))

    # Callbacks (inline keyboards)
    app.add_handler(CallbackQueryHandler(on_callback))

    # Media and documents
    app.add_handler(MessageHandler(
        (filters.PHOTO | filters.Document.IMAGE) & ~filters.COMMAND, on_media
    ))
    app.add_handler(MessageHandler(
        filters.Document.ALL & ~filters.Document.IMAGE & ~filters.COMMAND, on_document
    ))
    app.add_handler(MessageHandler(
        (filters.AUDIO | filters.VOICE) & ~filters.COMMAND, on_media
    ))
    app.add_handler(MessageHandler(
        (filters.VIDEO | filters.VIDEO_NOTE) & ~filters.COMMAND, on_media
    ))

    # Text (last -- catch-all)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
