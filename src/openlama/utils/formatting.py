"""Markdown-to-Telegram conversion using telegramify-markdown (entity-based)."""

from __future__ import annotations

import html
import logging
from typing import Optional

from telegram import MessageEntity, Update
from telegram.constants import ParseMode

import telegramify_markdown
from telegramify_markdown import convert as _tm_convert, split_entities

from openlama.config import TELEGRAM_MAX_MSG

logger = logging.getLogger("openlama.utils.formatting")

# ── Configure telegramify-markdown ───────────────────────
# Customize heading symbols (Korean-friendly)
telegramify_markdown.config.get_runtime_config().markdown_symbol.heading_level_1 = "📌"
telegramify_markdown.config.get_runtime_config().markdown_symbol.heading_level_2 = "✏"
telegramify_markdown.config.get_runtime_config().markdown_symbol.heading_level_3 = "📚"


def convert_markdown(md_text: str) -> tuple[str, list[MessageEntity]]:
    """Convert markdown to (text, entities) for Telegram entity-based sending.

    Returns a tuple of (plain_text, telegram_entities) that can be passed
    directly to send_message(text=..., entities=...).
    """
    if not md_text:
        return ("", [])

    text, tm_entities = _tm_convert(md_text)

    # Convert telegramify_markdown.MessageEntity → telegram.MessageEntity
    tg_entities = []
    for e in tm_entities:
        kwargs = {
            "type": e.type,
            "offset": e.offset,
            "length": e.length,
        }
        if e.url:
            kwargs["url"] = e.url
        if e.language:
            kwargs["language"] = e.language
        if e.custom_emoji_id:
            kwargs["custom_emoji_id"] = e.custom_emoji_id
        tg_entities.append(MessageEntity(**kwargs))

    return (text, tg_entities)


def split_message(
    text: str, entities: list[MessageEntity], max_len: int = TELEGRAM_MAX_MSG
) -> list[tuple[str, list[MessageEntity]]]:
    """Split a (text, entities) pair into chunks fitting Telegram's limit.

    Uses telegramify-markdown's split_entities which handles UTF-16 offsets
    and entity boundary clipping correctly.
    """
    if not text:
        return [("", [])]

    # Convert telegram.MessageEntity → telegramify_markdown.MessageEntity for splitting
    TmEntity = telegramify_markdown.MessageEntity
    tm_entities = []
    for e in entities:
        tm_entities.append(TmEntity(
            type=e.type,
            offset=e.offset,
            length=e.length,
            url=getattr(e, "url", None),
            language=getattr(e, "language", None),
            custom_emoji_id=getattr(e, "custom_emoji_id", None),
        ))

    raw_chunks = split_entities(text, tm_entities, max_len)

    # Convert back to telegram.MessageEntity
    result = []
    for chunk_text, chunk_tm_ents in raw_chunks:
        chunk_tg_ents = []
        for e in chunk_tm_ents:
            kwargs = {"type": e.type, "offset": e.offset, "length": e.length}
            if e.url:
                kwargs["url"] = e.url
            if e.language:
                kwargs["language"] = e.language
            if e.custom_emoji_id:
                kwargs["custom_emoji_id"] = e.custom_emoji_id
            chunk_tg_ents.append(MessageEntity(**kwargs))
        result.append((chunk_text, chunk_tg_ents))

    return result if result else [("", [])]


def format_think_response(thinking: str, answer: str) -> tuple[str, list[MessageEntity]]:
    """Format thinking-mode response with thinking section prefix + answer entities."""
    parts_text = ""
    parts_entities: list[MessageEntity] = []

    if thinking:
        # Truncate thinking and add as blockquote prefix
        trimmed = thinking.strip()
        if len(trimmed) > 500:
            trimmed = trimmed[:500] + "..."
        think_prefix = f"💭 Reasoning\n{trimmed}\n\n"
        # Add blockquote entity for the thinking section
        parts_text = think_prefix
        parts_entities.append(MessageEntity(
            type=MessageEntity.BLOCKQUOTE,
            offset=0,
            length=len(think_prefix.rstrip()),
        ))
        parts_entities.append(MessageEntity(
            type=MessageEntity.BOLD,
            offset=3,
            length=9,  # "Reasoning"
        ))

    # Convert the answer
    answer_text, answer_entities = convert_markdown(answer)

    # Shift answer entity offsets by the prefix length
    prefix_len = len(parts_text)
    for e in answer_entities:
        shifted = MessageEntity(
            type=e.type,
            offset=e.offset + prefix_len,
            length=e.length,
            url=getattr(e, "url", None),
            language=getattr(e, "language", None),
            custom_emoji_id=getattr(e, "custom_emoji_id", None),
        )
        parts_entities.append(shifted)

    parts_text += answer_text
    return (parts_text, parts_entities)


# ── Legacy HTML functions (kept for backward compatibility) ──

def chunks(text: str, size: int = TELEGRAM_MAX_MSG) -> list[str]:
    """Split plain text into chunks (simple fallback)."""
    if not text:
        return [""]
    out: list[str] = []
    while len(text) > size:
        cut = text.rfind("\n", 0, size)
        if cut <= 0:
            cut = size
        out.append(text[:cut])
        text = text[cut:].lstrip("\n")
    if text:
        out.append(text)
    return out


async def reply_llm_answer(update: Update, answer: str, thinking: Optional[str] = None):
    """Send LLM answer with entity-based formatting, fallback to plain text."""
    if not update.message:
        return

    try:
        if thinking:
            text, entities = format_think_response(thinking, answer)
        else:
            text, entities = convert_markdown(answer)

        for chunk_text, chunk_entities in split_message(text, entities):
            await update.message.reply_text(
                chunk_text,
                entities=chunk_entities,
            )
        return
    except Exception as e:
        logger.warning("Entity-based send failed: %s", e)

    # Fallback: plain text
    for part in chunks(answer):
        await update.message.reply_text(part)
