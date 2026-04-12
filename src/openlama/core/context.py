"""Context management — load, save, compress."""
from __future__ import annotations

import asyncio
import re

from openlama.database import load_context, save_context, clear_context, get_model_settings
from openlama.ollama_client import summarize_context
from openlama.config import get_config_float, get_config_int
from openlama.logger import get_logger

logger = get_logger("context")

# Regex for CJK characters (Chinese, Japanese, Korean + fullwidth)
_CJK_RE = re.compile(r'[\u3000-\u9fff\uac00-\ud7af\uff00-\uffef]')


def _estimate_tokens(text_or_charcount: str | int) -> int:
    """Estimate token count with language awareness.

    Accepts either a text string (for language-aware estimation) or
    an integer character count (legacy fallback: uses chars/3 ratio).

    CJK characters: ~1.5 chars per token (each char is usually one token)
    Latin/ASCII: ~4 chars per token (words average ~4 chars + space)
    Mixed content: weighted average of both.
    """
    if isinstance(text_or_charcount, int):
        # Legacy fallback for callers passing character count
        return max(1, text_or_charcount // 3)
    text = text_or_charcount
    if not text:
        return 1  # minimum 1
    cjk_count = len(_CJK_RE.findall(text))
    latin_count = len(text) - cjk_count
    return max(1, int(cjk_count / 1.5 + latin_count / 4))


def _estimate_messages_tokens(system_prompt: str, ctx_items: list[dict], user_text: str = "") -> int:
    """Estimate total tokens for system prompt + context + user text."""
    parts = [system_prompt, user_text]
    for item in ctx_items:
        parts.append(item.get("u", ""))
        parts.append(item.get("a", ""))
    total_text = "".join(parts)
    return _estimate_tokens(total_text)


def build_context_bar(used_tokens: int, max_tokens: int, turn_count: int) -> str:
    pct = min(used_tokens / max_tokens * 100, 100) if max_tokens > 0 else 0
    width = 20
    filled = int(pct / 100 * width)
    bar = "\u2588" * filled + "\u2591" * (width - filled)
    return f"\U0001f4ca {bar} {pct:.1f}% ({used_tokens:,}/{max_tokens:,} tokens)  |  turns: {turn_count}"


# Callback for compress notifications — set by channel handlers
_compress_notify: callable | None = None


def set_compress_notify(fn):
    """Set callback for compress start/end notifications.
    fn(status: str) — "start" or "done" or "failed".
    """
    global _compress_notify
    _compress_notify = fn


def truncate_tool_result(result: str, max_size: int | None = None) -> str:
    """Truncate tool result to prevent context bloat, preserving start and end."""
    if max_size is None:
        max_size = get_config_int("max_tool_result_size", 3000)
    if len(result) <= max_size:
        return result
    half = max_size // 2 - 50
    truncated = len(result) - max_size
    return (
        result[:half]
        + f"\n\n... [{truncated} chars truncated] ...\n\n"
        + result[-half:]
    )


def validate_token_budget(messages: list[dict], num_ctx: int, num_predict: int = 2048) -> list[dict]:
    """Trim context messages if estimated tokens exceed budget before sending to API."""
    # Estimate total tokens from all messages
    total_text = "".join(m.get("content", "") for m in messages)
    total = _estimate_tokens(total_text)

    # Reserve tokens for model output, then apply safety margin
    available = max(num_ctx - num_predict, num_ctx // 2)  # guard against num_predict > num_ctx
    budget = int(available * 0.85)

    if total <= budget:
        return messages

    # Keep system messages and trim oldest context
    original_count = len(messages)
    system_msgs = [m for m in messages if m["role"] == "system"]
    other_msgs = [m for m in messages if m["role"] != "system"]

    while total > budget and len(other_msgs) > 2:
        other_msgs.pop(0)
        total_text = "".join(m.get("content", "") for m in system_msgs + other_msgs)
        total = _estimate_tokens(total_text)

    result = system_msgs + other_msgs
    if len(result) < original_count:
        logger.info("Pre-send trim: %d→%d messages (budget=%d tokens)", original_count, len(result), budget)
    return result


def enforce_turn_limit(ctx_items: list[dict], max_turns: int | None = None) -> list[dict]:
    """Remove oldest turns to enforce maximum turn count."""
    if max_turns is None:
        max_turns = get_config_int("max_context_turns", 100)
    if len(ctx_items) > max_turns:
        trimmed = len(ctx_items) - max_turns
        logger.info("Trimming %d oldest turns (limit=%d)", trimmed, max_turns)
        return ctx_items[-max_turns:]
    return ctx_items


async def maybe_compress(
    uid: int, model: str, ctx_items: list[dict],
    num_ctx: int = 8192, system_prompt: str = "", user_text: str = "",
) -> tuple[list[dict], str]:
    """Compress context if approaching limit. Returns (items, summary)."""
    if not ctx_items or len(ctx_items) < 3:
        return ctx_items, ""

    threshold_pct = get_config_float("context_compress_threshold", 0.7)
    threshold = int(num_ctx * threshold_pct)
    est_tokens = _estimate_messages_tokens(system_prompt, ctx_items, user_text)

    logger.info("est_tokens=%d, threshold=%d (num_ctx=%d, pct=%.0f%%)", est_tokens, threshold, num_ctx, threshold_pct * 100)

    if est_tokens < threshold:
        return ctx_items, ""

    split_at = max(1, len(ctx_items) * 2 // 3)
    old_items = ctx_items[:split_at]
    recent_items = ctx_items[split_at:]

    old_text = "\n".join(
        f"User: {it.get('u', '')}\nAssistant: {it.get('a', '')}" for it in old_items
    )

    # Notify: compression starting
    if _compress_notify:
        try:
            await _compress_notify("start")
        except Exception:
            pass

    try:
        compress_timeout = get_config_int("context_compress_timeout", 30)
        summary = await asyncio.wait_for(
            summarize_context(model, old_text),
            timeout=compress_timeout,
        )
        logger.info("compressed %d turns → summary (%d chars), keeping %d recent", len(old_items), len(summary), len(recent_items))

        # Auto-save compressed content to daily memory
        try:
            from openlama.core.memory import save_daily_entry
            save_daily_entry(summary, source="context_compression")
        except Exception as e:
            logger.warning("failed to save daily memory on compression: %s", e)

        if _compress_notify:
            try:
                await _compress_notify("done")
            except Exception:
                pass

        return recent_items, summary
    except asyncio.TimeoutError:
        logger.warning("Context compression timed out after %ds, keeping original", compress_timeout)
        if _compress_notify:
            try:
                await _compress_notify("failed")
            except Exception:
                pass
        return ctx_items, ""
    except Exception as e:
        logger.error("summarize failed: %s", e)
        if _compress_notify:
            try:
                await _compress_notify("failed")
            except Exception:
                pass
        return ctx_items, ""
