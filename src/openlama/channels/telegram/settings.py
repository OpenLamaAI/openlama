"""Settings handlers -- /settings, /systemprompt, /think."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from openlama.auth import require_auth
from openlama.config import DEFAULT_MODEL_PARAMS, DEFAULT_SYSTEM_PROMPT
from openlama.database import (
    get_model_settings,
    get_user,
    is_authed,
    reset_model_settings,
    set_model_setting,
    update_user,
)
from openlama.ollama_client import get_model_max_context


# ── Settings keyboard ────────────────────────────────────

PARAM_CONFIG = {
    "temperature": {
        "min": 0.0, "max": 2.0, "step": 0.1, "fmt": ".1f", "label": "🌡 Temperature",
        "desc": "Creativity control. Lower = more consistent, higher = more diverse",
    },
    "top_p": {
        "min": 0.0, "max": 1.0, "step": 0.05, "fmt": ".2f", "label": "🎯 Top P",
        "desc": "Cumulative probability threshold. Lower = only confident tokens",
    },
    "top_k": {
        "min": 1, "max": 200, "step": 5, "fmt": "d", "label": "🔢 Top K",
        "desc": "Candidate token count. Lower = focused, higher = diverse",
    },
    "num_ctx": {
        "min": 1024, "max": 262144, "step": None, "fmt": "d", "label": "📏 Context Size",
        "presets": [2048, 4096, 8192, 16384, 32768, 65536, 131072],
        "desc": "Input context size (tokens). Larger = longer conversations, more VRAM",
    },
    "num_predict": {
        "min": 128, "max": 16384, "step": None, "fmt": "d", "label": "📝 Max Tokens",
        "presets": [256, 512, 1024, 2048, 4096, 8192],
        "desc": "Max response length (tokens). Larger = more detailed responses",
    },
    "repeat_penalty": {
        "min": 0.5, "max": 2.0, "step": 0.1, "fmt": ".1f", "label": "🔄 Repeat Penalty",
        "desc": "Repetition suppression. 1.0=none, higher = less repetition",
    },
    "seed": {
        "min": 0, "max": 999999, "step": 1, "fmt": "d", "label": "🎲 Seed",
        "desc": "Random seed. Same value = same result. 0 = random",
    },
}



def settings_keyboard(uid: int, model: str) -> InlineKeyboardMarkup:
    ms = get_model_settings(uid, model)
    user = get_user(uid)
    rows = []

    for key, cfg in PARAM_CONFIG.items():
        val = getattr(ms, key)
        fmt = cfg["fmt"]
        label = cfg["label"]
        display = f"{val:{fmt}}" if isinstance(fmt, str) else str(val)

        if cfg.get("presets"):
            rows.append([InlineKeyboardButton(f"{label}: {display}", callback_data=f"set_preset:{key}")])
        else:
            rows.append([
                InlineKeyboardButton("➖", callback_data=f"set_dec:{key}"),
                InlineKeyboardButton(f"{label}: {display}", callback_data="noop"),
                InlineKeyboardButton("➕", callback_data=f"set_inc:{key}"),
            ])

    # Keep alive
    rows.append([InlineKeyboardButton(f"⏱ Keep Alive: {ms.keep_alive}", callback_data="set_preset:keep_alive")])

    # Token stats toggle
    from openlama.config import get_config
    show_stats = get_config("show_token_stats", "true").lower() in ("true", "1", "yes")
    stats_label = "📊 Token Stats: ON" if show_stats else "📊 Token Stats: OFF"
    rows.append([InlineKeyboardButton(stats_label, callback_data="toggle:show_token_stats")])

    rows.append([
        InlineKeyboardButton("🔄 Reset", callback_data="set_reset"),
        InlineKeyboardButton("🏠 Menu", callback_data="cmd:menu"),
    ])
    return InlineKeyboardMarkup(rows)


def _build_ctx_presets(max_ctx: int = 0) -> list[int]:
    """Build context size presets, adding model-specific large values."""
    base = [2048, 4096, 8192, 16384, 32768, 65536]
    if max_ctx > 65536:
        candidates = [131072, 262144]
        for v in candidates:
            if v <= max_ctx and v not in base:
                base.append(v)
    return base


def preset_keyboard(param: str, max_ctx: int = 0) -> InlineKeyboardMarkup:
    if param == "num_ctx":
        presets = _build_ctx_presets(max_ctx)
        rows = []
        for i in range(0, len(presets), 3):
            row = [InlineKeyboardButton(f"{v:,}", callback_data=f"set_val:num_ctx:{v}") for v in presets[i:i+3]]
            rows.append(row)
    elif param == "num_predict":
        presets = PARAM_CONFIG["num_predict"]["presets"]
        rows = [[InlineKeyboardButton(str(v), callback_data=f"set_val:num_predict:{v}") for v in presets[:3]],
                [InlineKeyboardButton(str(v), callback_data=f"set_val:num_predict:{v}") for v in presets[3:]]]
    elif param == "keep_alive":
        presets = ["0", "5m", "15m", "30m", "1h", "24h", "-1"]
        rows = [[InlineKeyboardButton(v, callback_data=f"set_val:keep_alive:{v}") for v in presets[:4]],
                [InlineKeyboardButton(v, callback_data=f"set_val:keep_alive:{v}") for v in presets[4:]]]
    else:
        return InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Back", callback_data="cmd:settings")]])

    rows.append([InlineKeyboardButton("⬅ Back", callback_data="cmd:settings")])
    return InlineKeyboardMarkup(rows)


# ── Command handlers ──────────────────────────────────────

async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await require_auth(update)
    if not user:
        return

    if not user.selected_model:
        await update.message.reply_text("Please select a model first: /models")
        return

    desc_lines = [f"⚙️ <b>Model Settings: {user.selected_model}</b>\n"]
    for key, cfg in PARAM_CONFIG.items():
        desc_lines.append(f"<b>{cfg['label']}</b>: {cfg.get('desc', '')}")
    desc_lines.append(f"\n<b>⏱ Keep Alive</b>: Model memory retention time (0=immediate release, -1=permanent)")

    await update.message.reply_text(
        "\n".join(desc_lines),
        parse_mode="HTML",
        reply_markup=settings_keyboard(user.telegram_id, user.selected_model),
    )


async def systemprompt_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show prompt file list for editing."""
    user = await require_auth(update)
    if not user:
        return

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

    await update.message.reply_text(
        "📋 <b>Prompt Files</b>\n\n"
        "Select a file to view and edit.\n"
        "To edit: view the file, copy the content, modify it, and send it back.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def think_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await require_auth(update)
    if not user:
        return

    arg = (context.args[0] if context.args else "").lower()
    uid = user.telegram_id

    if arg == "on":
        update_user(uid, think_mode=1)
        await update.message.reply_text("💭 Think Mode ON\nReasoning process will be shown in responses.")
    elif arg == "off":
        update_user(uid, think_mode=0)
        await update.message.reply_text("💭 Think Mode OFF")
    else:
        current = "ON 💭" if user.think_mode else "OFF"
        await update.message.reply_text(
            f"💭 <b>Think Mode: {current}</b>\n\n"
            f"Usage:\n"
            f"• /think on — Show reasoning\n"
            f"• /think off — Hide reasoning",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("💭 ON", callback_data="cmd:think_on"),
                    InlineKeyboardButton("💬 OFF", callback_data="cmd:think_off"),
                ],
                [InlineKeyboardButton("🏠 Menu", callback_data="cmd:menu")],
            ]),
        )


# ── Callback processing (called from handlers.py) ──

async def handle_settings_callback(query, uid: int, data: str, user):
    """Handle set_inc, set_dec, set_val, set_preset, set_reset callbacks."""
    model = user.selected_model
    if not model:
        await query.edit_message_text("Please select a model first: /models")
        return

    if data == "set_reset":
        reset_model_settings(uid, model)
        await query.edit_message_text(
            f"⚙️ <b>Model Settings: {model}</b>\n🔄 Reset complete",
            parse_mode="HTML",
            reply_markup=settings_keyboard(uid, model),
        )
        return

    if data == "toggle:show_token_stats":
        from openlama.config import get_config
        from openlama.database import set_setting
        current = get_config("show_token_stats", "true").lower() in ("true", "1", "yes")
        set_setting("show_token_stats", "false" if current else "true")
        new_label = "OFF" if current else "ON"
        await query.edit_message_text(
            f"⚙️ <b>Model Settings: {model}</b>\n📊 Token Stats: {new_label}",
            parse_mode="HTML",
            reply_markup=settings_keyboard(uid, model),
        )
        return

    if data.startswith("set_preset:"):
        param = data.split(":", 1)[1]
        extra_info = ""
        max_ctx = 0

        cfg = PARAM_CONFIG.get(param)
        if cfg:
            extra_info = f"\n💡 {cfg.get('desc', '')}"

        if param == "num_ctx":
            try:
                max_ctx = await get_model_max_context(model)
                if max_ctx > 0:
                    extra_info += f"\n📌 Model max context: <b>{max_ctx:,}</b> tokens"
                else:
                    extra_info += "\n📌 Model max context: info unavailable"
            except Exception:
                pass
        elif param == "keep_alive":
            extra_info = "\n💡 Model memory retention time. 0=immediate release, -1=permanent"
        label = cfg["label"] if cfg else param
        await query.edit_message_text(
            f"⚙️ <b>Select {label} Value</b>{extra_info}",
            parse_mode="HTML",
            reply_markup=preset_keyboard(param, max_ctx=max_ctx),
        )
        return

    if data.startswith("set_val:"):
        parts = data.split(":", 2)
        param, raw_val = parts[1], parts[2]

        if param == "keep_alive":
            set_model_setting(uid, model, "keep_alive", raw_val)
        else:
            cfg = PARAM_CONFIG.get(param)
            if cfg:
                val = float(raw_val) if "." in cfg["fmt"] else int(raw_val)
                set_model_setting(uid, model, param, val)

        await query.edit_message_text(
            f"⚙️ <b>Model Settings: {model}</b>",
            parse_mode="HTML",
            reply_markup=settings_keyboard(uid, model),
        )
        return

    if data.startswith("set_inc:") or data.startswith("set_dec:"):
        action, param = data.split(":", 1)
        cfg = PARAM_CONFIG.get(param)
        if not cfg or not cfg.get("step"):
            return

        ms = get_model_settings(uid, model)
        current = getattr(ms, param)
        step = cfg["step"]

        if action == "set_inc":
            new_val = min(current + step, cfg["max"])
        else:
            new_val = max(current - step, cfg["min"])

        if isinstance(step, float):
            new_val = round(new_val, 2)

        set_model_setting(uid, model, param, new_val)
        await query.edit_message_text(
            f"⚙️ <b>Model Settings: {model}</b>",
            parse_mode="HTML",
            reply_markup=settings_keyboard(uid, model),
        )
