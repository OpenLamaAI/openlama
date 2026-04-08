"""Admin handlers -- /ollama server management."""

from __future__ import annotations

import asyncio
import json
import platform
import shutil

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from openlama.auth import require_auth
from openlama.config import get_config
from openlama.ollama_client import (
    copy_model,
    ensure_ollama_running,
    get_model_capabilities,
    get_model_info,
    get_running_models,
    ollama_alive,
)
from openlama.utils.comfyui_client import comfyui_alive
from openlama.logger import get_logger

logger = get_logger("telegram.admin")


def ollama_menu_keyboard(show_install: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("📊 Status", callback_data="ollama:status"),
            InlineKeyboardButton("🖥 Loaded Models", callback_data="ollama:ps"),
        ],
        [
            InlineKeyboardButton("🔄 Check Connection", callback_data="ollama:check"),
            InlineKeyboardButton("ℹ️ Model Details", callback_data="ollama:info_prompt"),
        ],
    ]
    if show_install:
        rows.append([InlineKeyboardButton("📥 Install Ollama", callback_data="ollama:install")])
    rows.append([
        InlineKeyboardButton("📋 Copy", callback_data="ollama:copy_prompt"),
        InlineKeyboardButton("🏠 Menu", callback_data="cmd:menu"),
    ])
    return InlineKeyboardMarkup(rows)


async def ollama_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await require_auth(update)
    if not user:
        return

    if not context.args:
        await update.message.reply_text(
            "🖥 <b>Ollama Server Management</b>",
            parse_mode="HTML",
            reply_markup=ollama_menu_keyboard(),
        )
        return

    sub = context.args[0].lower()

    if sub == "status":
        await _show_status(update)
    elif sub == "ps":
        await _show_ps(update)
    elif sub == "check":
        await _do_check(update)
    elif sub == "info" and len(context.args) > 1:
        model = context.args[1]
        await _show_info(update, model)
    elif sub == "copy" and len(context.args) > 2:
        src, dst = context.args[1], context.args[2]
        await _do_copy(update, src, dst)
    else:
        await update.message.reply_text(
            "Usage:\n"
            "/ollama status — Server status\n"
            "/ollama ps — Loaded models\n"
            "/ollama check — Check connection\n"
            "/ollama info <model> — Model details\n"
            "/ollama copy <src> <dst> — Copy model"
        )


def _ollama_installed() -> bool:
    """Check if ollama binary exists."""
    return shutil.which("ollama") is not None


async def _show_status(update_or_query):
    from openlama.config import is_ollama_remote
    remote = is_ollama_remote()
    installed = remote or _ollama_installed()
    alive = await ollama_alive()

    if not installed:
        status = "❌ Not Installed"
    elif alive:
        status = "🟢 Online" + (" (remote)" if remote else "")
    else:
        status = "🔴 Offline" + (" (remote)" if remote else "")

    text = (
        f"🖥 <b>Ollama Server Status</b>\n\n"
        f"Status: {status}\n"
        f"Address: {get_config('ollama_base')}"
    )

    if not installed:
        text += (
            "\n\nOllama is not installed.\n"
            "Use the button below to auto-install, or install manually."
        )

    if alive:
        running = await get_running_models()
        if running:
            text += f"\nLoaded models: {len(running)}"
            for m in running:
                name = m.get("name", "?")
                size = m.get("size", 0)
                size_gb = f"{size / 1e9:.1f}GB" if size else "?"
                text += f"\n  • {name} ({size_gb})"
        else:
            text += "\nLoaded models: none"

    kb = ollama_menu_keyboard(show_install=not installed)
    if hasattr(update_or_query, 'message') and update_or_query.message:
        await update_or_query.message.reply_text(text, parse_mode="HTML", reply_markup=kb)
    else:
        await update_or_query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)


async def _show_ps(update_or_query):
    running = await get_running_models()
    if not running:
        text = "🖥 No models currently loaded."
    else:
        lines = ["🖥 <b>Currently Loaded Models</b>\n"]
        for m in running:
            name = m.get("name", "?")
            size = m.get("size", 0)
            size_gb = f"{size / 1e9:.1f}GB" if size else "?"
            expires = m.get("expires_at", "?")
            lines.append(f"• <b>{name}</b> ({size_gb})\n  Expires: {expires}")
        text = "\n".join(lines)

    if hasattr(update_or_query, 'message') and update_or_query.message:
        await update_or_query.message.reply_text(text, parse_mode="HTML", reply_markup=ollama_menu_keyboard())
    else:
        await update_or_query.edit_message_text(text, parse_mode="HTML", reply_markup=ollama_menu_keyboard())


async def _do_check(update_or_query):
    """Check Ollama connectivity."""
    alive = await ollama_alive()
    if alive:
        text = "✅ Ollama server connected successfully"
    else:
        text = "❌ Cannot connect to Ollama server. Check if the server is running."
    if hasattr(update_or_query, 'message') and update_or_query.message:
        await update_or_query.message.reply_text(text, reply_markup=ollama_menu_keyboard())
    else:
        await update_or_query.edit_message_text(text, reply_markup=ollama_menu_keyboard())


async def _show_info(update, model: str):
    try:
        info = await get_model_info(model)
    except Exception as e:
        await update.message.reply_text(f"Failed to get model info: {e}")
        return

    details = info.get("details", {})
    params = details.get("parameter_size", "?")
    quant = details.get("quantization_level", "?")
    family = details.get("family", "?")
    fmt = details.get("format", "?")

    caps = await get_model_capabilities(model)
    cap_text = ", ".join(caps) if caps else "none"

    template = (info.get("template") or "")[:200]

    await update.message.reply_text(
        f"ℹ️ <b>Model Info: {model}</b>\n\n"
        f"Family: {family}\n"
        f"Parameters: {params}\n"
        f"Quantization: {quant}\n"
        f"Format: {fmt}\n"
        f"Capabilities: {cap_text}\n\n"
        f"Template:\n<code>{template}</code>",
        parse_mode="HTML",
    )


async def _do_copy(update, src: str, dst: str):
    try:
        await copy_model(src, dst)
        await update.message.reply_text(f"✅ Model copied: {src} -> {dst}")
    except Exception as e:
        await update.message.reply_text(f"❌ Copy failed: {e}")


# ── Callback processing (called from handlers.py) ──

async def handle_ollama_callback(query, uid: int, data: str):
    if data == "ollama:status":
        await _show_status(query)
    elif data == "ollama:ps":
        await _show_ps(query)
    elif data == "ollama:check":
        await _do_check(query)
    elif data == "ollama:info_prompt":
        await query.edit_message_text(
            "ℹ️ To view model details:\n/ollama info <model_name>\n\nExample: /ollama info gemma4:26b",
            reply_markup=ollama_menu_keyboard(),
        )
    elif data == "ollama:copy_prompt":
        await query.edit_message_text(
            "📋 To copy a model:\n/ollama copy <source> <destination>\n\nExample: /ollama copy gemma4:26b mymodel:latest",
            reply_markup=ollama_menu_keyboard(),
        )
    elif data == "ollama:install":
        await _install_ollama(query)


async def _install_ollama(query):
    """Install Ollama via official install script."""
    if _ollama_installed():
        await query.edit_message_text("✅ Ollama is already installed.", reply_markup=ollama_menu_keyboard())
        return

    await query.edit_message_text("📥 Installing Ollama... (1-2 minutes)")

    system = platform.system().lower()

    if system == "windows":
        await query.edit_message_text(
            "Ollama must be installed manually on Windows.\n"
            "Download: https://ollama.com/download/windows",
            reply_markup=ollama_menu_keyboard(show_install=True),
        )
        return
    elif system == "darwin":
        cmd = "brew install ollama 2>&1"
    elif system == "linux":
        cmd = "curl -fsSL https://ollama.com/install.sh | sh 2>&1"
    else:
        await query.edit_message_text(
            f"❌ Unsupported OS: {system}\nInstall manually from https://ollama.com",
            reply_markup=ollama_menu_keyboard(),
        )
        return

    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)
        output = stdout.decode("utf-8", errors="replace")[-500:]

        if proc.returncode == 0 and _ollama_installed():
            await query.edit_message_text(
                f"✅ Ollama installation complete!\n\n<code>{output[-200:]}</code>\n\n"
                "Run 'ollama serve' on the server to start Ollama.",
                parse_mode="HTML",
                reply_markup=ollama_menu_keyboard(),
            )
        else:
            err = stderr.decode("utf-8", errors="replace")[-300:]
            await query.edit_message_text(
                f"❌ Installation failed\n\n<code>{err or output}</code>",
                parse_mode="HTML",
                reply_markup=ollama_menu_keyboard(show_install=True),
            )
    except asyncio.TimeoutError:
        await query.edit_message_text("❌ Installation timed out (3 min)", reply_markup=ollama_menu_keyboard(show_install=True))
    except Exception as e:
        await query.edit_message_text(f"❌ Installation error: {e}", reply_markup=ollama_menu_keyboard(show_install=True))


# ── ComfyUI Management ──────────────────────────────────


def comfyui_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Check Status", callback_data="comfyui:status"),
        ],
        [InlineKeyboardButton("🏠 Menu", callback_data="cmd:menu")],
    ])


async def show_comfyui_status(query):
    from openlama.utils.comfyui_client import setup_comfyui
    comfy_base = get_config("comfy_base")
    start_cmd = get_config("comfy_start_cmd", "")
    auto_stop = get_config("comfy_auto_stop", "true")

    status_info = await setup_comfyui()
    alive = status_info["connected"]
    status = "🟢 Running" if alive else "🔴 Stopped"

    text = (
        f"🎨 <b>ComfyUI Status</b>\n\n"
        f"Status: {status}\n"
        f"Address: {comfy_base}\n"
        f"Auto Start: {'✅' if start_cmd else '❌ Not configured'}\n"
        f"Auto Stop: {'✅' if auto_stop.lower() in ('true','1','yes') else '❌'}\n"
    )

    # Workflow validation
    wfs = status_info.get("available_workflows", [])
    text += f"\n<b>Workflows:</b> {len(wfs)}\n"

    txt2img = status_info.get("txt2img", {})
    t_name = txt2img.get("name", "?")
    if txt2img.get("valid"):
        text += f"  🖼 txt2img: ✅ {t_name}\n"
    else:
        missing = txt2img.get("missing", [])
        text += f"  🖼 txt2img: ❌ {t_name}\n"
        if missing:
            text += f"     Missing: {', '.join(missing[:3])}\n"

    img2img = status_info.get("img2img", {})
    i_name = img2img.get("name", "?")
    if img2img.get("valid"):
        text += f"  ✏️ img2img: ✅ {i_name}\n"
    else:
        missing = img2img.get("missing", [])
        text += f"  ✏️ img2img: ❌ {i_name}\n"
        if missing:
            text += f"     Missing: {', '.join(missing[:3])}\n"

    if alive:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(f"{comfy_base}/system_stats")
                if r.status_code == 200:
                    stats = r.json()
                    devices = stats.get("devices", [])
                    for d in devices:
                        name = d.get("name", "?")
                        vram_total = d.get("vram_total", 0)
                        vram_free = d.get("vram_free", 0)
                        vram_used = vram_total - vram_free
                        if vram_total > 0:
                            text += (
                                f"\n<b>GPU:</b> {name}\n"
                                f"VRAM: {vram_used / 1e9:.1f}GB / {vram_total / 1e9:.1f}GB "
                                f"({vram_used / vram_total * 100:.0f}%)"
                            )
        except Exception:
            pass

    await query.edit_message_text(text, parse_mode="HTML", reply_markup=comfyui_menu_keyboard())


async def handle_comfyui_callback(query, uid: int, data: str):
    if data == "comfyui:status":
        await show_comfyui_status(query)
