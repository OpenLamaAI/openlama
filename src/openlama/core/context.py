"""Context management — load, save, compress."""
from __future__ import annotations

from openlama.database import load_context, save_context, clear_context, get_model_settings
from openlama.ollama_client import summarize_context
from openlama.config import get_config_float
from openlama.logger import get_logger

logger = get_logger("context")


def _estimate_tokens(char_count: int) -> int:
    return max(1, char_count // 3)


def _estimate_messages_tokens(system_prompt: str, ctx_items: list[dict], user_text: str = "") -> int:
    total = len(system_prompt) + len(user_text)
    for item in ctx_items:
        total += len(item.get("u", "")) + len(item.get("a", ""))
    return _estimate_tokens(total)


def build_context_bar(used_tokens: int, max_tokens: int, turn_count: int) -> str:
    pct = min(used_tokens / max_tokens * 100, 100) if max_tokens > 0 else 0
    width = 20
    filled = int(pct / 100 * width)
    bar = "\u2588" * filled + "\u2591" * (width - filled)
    return f"\U0001f4ca {bar} {pct:.1f}% ({used_tokens:,}/{max_tokens:,} tokens)  |  turns: {turn_count}"


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

    try:
        summary = await summarize_context(model, old_text)
        logger.info("compressed %d turns \u2192 summary (%d chars), keeping %d recent", len(old_items), len(summary), len(recent_items))
        return recent_items, summary
    except Exception as e:
        logger.error("summarize failed: %s", e)
        return ctx_items, ""
