"""Cron scheduler — background task that executes scheduled jobs."""
from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Awaitable, Optional

from croniter import croniter

from openlama.database import (
    get_due_cron_jobs, update_cron_job, get_cron_job, list_cron_jobs,
)
from openlama.logger import get_logger

logger = get_logger("scheduler")

CHECK_INTERVAL = 60  # seconds

# Channel callback: async fn(chat_id, text) -> None
_channel_sender: Optional[Callable[[int, str], Awaitable[None]]] = None
_scheduler_task: Optional[asyncio.Task] = None


def set_channel_sender(fn: Callable[[int, str], Awaitable[None]]):
    """Register a callback for sending cron results to a channel."""
    global _channel_sender
    _channel_sender = fn


def compute_next_run(cron_expr: str, base_time: float = 0) -> int:
    """Compute next run timestamp from a cron expression (local timezone)."""
    from datetime import datetime
    base_dt = datetime.fromtimestamp(base_time) if base_time > 0 else datetime.now()
    try:
        cron = croniter(cron_expr, base_dt)
        next_dt = cron.get_next(datetime)
        return int(next_dt.timestamp())
    except Exception as e:
        logger.error("invalid cron expression '%s': %s", cron_expr, e)
        return 0


def validate_cron_expr(cron_expr: str) -> bool:
    """Check if a cron expression is valid."""
    try:
        croniter(cron_expr)
        return True
    except Exception:
        return False


async def execute_job(job: dict) -> str:
    """Execute a single cron job with AI. Returns the result text."""
    from openlama.core.prompt_builder import build_full_system_prompt
    from openlama.ollama_client import chat_with_ollama_full
    from openlama.tools import format_tools_for_ollama, execute_tool
    from openlama.database import get_user, get_model_settings
    from openlama.core.agent import handle_tool_calls
    from openlama.core.types import TokenUsage
    import json
    import re

    job_id = job["id"]
    task = job["task"]
    uid = job.get("created_by", 0) or 1

    logger.info("executing cron job #%d: %s", job_id, task[:60])

    # Get user's model
    user = get_user(uid)
    model = user.selected_model
    if not model:
        from openlama.config import get_config
        model = get_config("default_model")
    if not model:
        return f"[Cron #{job_id}] No model available."

    settings = get_model_settings(uid, model)

    # Build minimal context (no conversation history)
    system_prompt = build_full_system_prompt(num_ctx=settings.num_ctx)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "system", "content": (
            "## Scheduled Task Execution\n"
            "You are executing a scheduled task. Rules:\n"
            "- Execute the task described below and report the result.\n"
            "- Use available tools as needed (web_search, shell_command, etc.).\n"
            "- Be concise and factual in your response.\n"
            "- This is a one-shot execution with no conversation history.\n"
            f"\nTask: {task}\n"
            f"Schedule: {job['cron_expr']}\n"
        )},
        {"role": "user", "content": task},
    ]

    tools = format_tools_for_ollama(admin=True)

    from openlama.config import get_config_int as _gci
    job_timeout = _gci("cron_job_timeout", 180)

    try:
        async def _run_job():
            resp = await chat_with_ollama_full(model, messages, settings=settings, tools=tools, think=False)
            content = resp.get("content", "")
            tool_calls = resp.get("tool_calls", [])
            if tool_calls:
                content, _, _ = await handle_tool_calls(
                    uid, model, messages, tool_calls, settings,
                    think=False, tools=tools,
                )
            return content.strip() if content else "(no response)"

        result = await asyncio.wait_for(_run_job(), timeout=job_timeout)
        logger.info("cron job #%d completed: %d chars", job_id, len(result))
        return result

    except asyncio.TimeoutError:
        error_msg = f"[Cron #{job_id}] Timed out after {job_timeout}s"
        logger.error(error_msg)
        return error_msg
    except Exception as e:
        error_msg = f"[Cron #{job_id}] Execution error: {e}"
        logger.error(error_msg)
        return error_msg


async def _process_due_jobs():
    """Check for and execute due cron jobs."""
    now = int(time.time())
    due_jobs = get_due_cron_jobs(now)

    if not due_jobs:
        return

    logger.info("found %d due cron job(s)", len(due_jobs))

    for job in due_jobs:
        job_id = job["id"]
        try:
            # Execute
            result = await execute_job(job)

            # Update last_run and compute next_run
            next_run = compute_next_run(job["cron_expr"], now)
            update_cron_job(job_id, last_run=now, next_run=next_run)

            # Send result to channel
            if _channel_sender and job.get("chat_id"):
                header = f"📋 Scheduled Task #{job_id}\n({job['task'][:80]})\n\n"
                await _channel_sender(job["chat_id"], header + result)
            else:
                logger.info("cron job #%d result (no channel): %s", job_id, result[:200])

        except Exception as e:
            logger.error("cron job #%d failed: %s", job_id, e)
            # Still update next_run so it doesn't get stuck
            next_run = compute_next_run(job["cron_expr"], now)
            update_cron_job(job_id, next_run=next_run)


async def _daily_memory_flush():
    """Flush current context for all active users to daily memory.

    Runs once per day. Extracts topics from context items (no LLM call)
    and saves them to today's daily memory file.
    """
    from openlama.database import get_users_with_context, load_context, get_setting, set_setting
    from openlama.core.memory import extract_topics, save_daily_entry, cleanup_old_memories

    today = time.strftime("%Y-%m-%d")
    last_flush = get_setting("last_daily_flush") or ""
    if last_flush == today:
        return  # Already flushed today

    user_ids = get_users_with_context()
    if not user_ids:
        set_setting("last_daily_flush", today)
        return

    flushed = 0
    for uid in user_ids:
        ctx = load_context(uid)
        if not ctx:
            continue
        topics = extract_topics(ctx)
        if topics:
            save_daily_entry(topics, source="daily_flush")
            flushed += 1

    set_setting("last_daily_flush", today)
    if flushed:
        logger.info("daily memory flush: %d user(s) saved", flushed)

    # Run memory garbage collection alongside daily flush
    try:
        cleanup_old_memories()
    except Exception as e:
        logger.warning("Memory GC failed: %s", e)


def _is_flush_hour() -> bool:
    """Check if current time is midnight hour (00:xx)."""
    return time.localtime().tm_hour == 0


async def scheduler_loop():
    """Main scheduler loop — runs every 60 seconds."""
    logger.info("scheduler started (check interval: %ds)", CHECK_INTERVAL)
    while True:
        try:
            await _process_due_jobs()
        except Exception as e:
            logger.error("scheduler loop error: %s", e)

        # Daily memory flush at midnight
        if _is_flush_hour():
            try:
                await _daily_memory_flush()
            except Exception as e:
                logger.error("daily memory flush error: %s", e)

        await asyncio.sleep(CHECK_INTERVAL)


def start_scheduler():
    """Start the scheduler as a background asyncio task."""
    global _scheduler_task
    if _scheduler_task and not _scheduler_task.done():
        logger.info("scheduler already running")
        return
    _scheduler_task = asyncio.create_task(scheduler_loop())
    logger.info("scheduler background task created")


def stop_scheduler():
    """Stop the scheduler."""
    global _scheduler_task
    if _scheduler_task and not _scheduler_task.done():
        _scheduler_task.cancel()
        _scheduler_task = None
        logger.info("scheduler stopped")
