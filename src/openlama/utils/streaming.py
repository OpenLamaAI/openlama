"""Streaming response helper – progressive edit_message for Telegram."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from telegram import Message
from telegram.error import BadRequest, RetryAfter

from openlama.config import get_config_float, get_config_int, TELEGRAM_MAX_MSG
from openlama.utils.formatting import convert_markdown, split_message, format_think_response, chunks

logger = logging.getLogger("openlama.utils.streaming")


async def _send_with_entities(
    message: Message, text: str, entities, plain_text: str, is_edit: bool = False
):
    """Send/edit a message using entities, falling back to plain text."""
    parts = split_message(text, entities)

    for i, (chunk_text, chunk_entities) in enumerate(parts):
        try:
            if i == 0 and is_edit:
                await message.edit_text(chunk_text, entities=chunk_entities)
            elif i == 0:
                await message.reply_text(chunk_text, entities=chunk_entities)
            else:
                await message.get_bot().send_message(
                    chat_id=message.chat_id,
                    text=chunk_text,
                    entities=chunk_entities,
                )
        except Exception as e:
            logger.warning("Entity send failed (part %d): %s", i, e)
            # Fallback: plain text
            try:
                plain_parts = chunks(plain_text)
                fallback = plain_parts[i] if i < len(plain_parts) else chunk_text
                if i == 0 and is_edit:
                    await message.edit_text(fallback)
                elif i == 0:
                    await message.reply_text(fallback)
                else:
                    await message.get_bot().send_message(
                        chat_id=message.chat_id, text=fallback
                    )
            except Exception:
                pass


async def stream_response_to_message(
    message: Message,
    token_generator,
    think_mode: bool = False,
) -> dict:
    """
    Stream tokens from an async generator into a Telegram message via edits.

    Returns: {"content": str, "thinking": str, "tool_calls": list}
    """
    full_text = ""
    thinking_text = ""
    tool_calls = []
    last_edit_time = 0.0
    last_edit_len = 0
    in_thinking = False
    prompt_tokens = 0
    completion_tokens = 0

    streaming_edit_interval = get_config_float("streaming_edit_interval", 1.5)
    streaming_min_delta = get_config_int("streaming_min_delta", 30)

    async for chunk in token_generator:
        msg = chunk.get("message", {})

        # Capture token usage from final chunk
        if chunk.get("done"):
            prompt_tokens = chunk.get("prompt_eval_count", 0)
            completion_tokens = chunk.get("eval_count", 0)

        # Handle tool calls
        if msg.get("tool_calls"):
            logger.debug("Got tool_calls: %s", msg["tool_calls"])
            tool_calls.extend(msg["tool_calls"])
            continue

        # Handle thinking (Ollama native thinking field, e.g. Gemma 4)
        if think_mode and msg.get("thinking"):
            thinking_text += msg["thinking"]
            # Don't skip - there may also be content in the same chunk

        token = msg.get("content", "")
        if not token:
            if chunk.get("done"):
                break
            continue

        # Track thinking blocks (legacy <think> tag format)
        if think_mode:
            if "<think>" in token:
                in_thinking = True
                token = token.replace("<think>", "")
            if "</think>" in token:
                in_thinking = False
                token = token.replace("</think>", "")

            if in_thinking:
                thinking_text += token
                continue

        full_text += token

        # Throttled edits (plain text during streaming for speed)
        now = time.time()
        text_delta = len(full_text) - last_edit_len
        if text_delta >= streaming_min_delta and (now - last_edit_time) >= streaming_edit_interval:
            display = full_text + " ▍"
            if len(display) > TELEGRAM_MAX_MSG - 50:
                display = display[-(TELEGRAM_MAX_MSG - 50):]
            try:
                await message.edit_text(display)
                last_edit_time = now
                last_edit_len = len(full_text)
            except BadRequest as e:
                if "not modified" not in str(e).lower():
                    pass
            except RetryAfter as e:
                await asyncio.sleep(e.retry_after)
            except Exception:
                pass

    # Final formatted send (entity-based)
    if full_text:
        if think_mode and thinking_text:
            final_text, final_entities = format_think_response(thinking_text, full_text)
        else:
            final_text, final_entities = convert_markdown(full_text)

        await _send_with_entities(message, final_text, final_entities, full_text, is_edit=True)

    elif not tool_calls:
        try:
            await message.edit_text("Response is empty.")
        except Exception:
            pass

    return {
        "content": full_text.strip(),
        "thinking": thinking_text.strip(),
        "tool_calls": tool_calls,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }
