"""Cron manager tool — create, list, delete, enable/disable scheduled tasks."""
from __future__ import annotations

import time

from openlama.tools.registry import register_tool
from openlama.database import (
    create_cron_job, list_cron_jobs, delete_cron_job, update_cron_job, get_cron_job,
)
from openlama.core.scheduler import compute_next_run, validate_cron_expr, execute_job


# Current chat context — set by channel handlers before tool execution
_current_chat_id: int = 0
_current_user_id: int = 0


def set_chat_context(chat_id: int, user_id: int):
    """Set current chat context for cron job creation."""
    global _current_chat_id, _current_user_id
    _current_chat_id = chat_id
    _current_user_id = user_id


async def _cron_manager(args: dict) -> str:
    action = args.get("action", "list")

    if action == "list":
        jobs = list_cron_jobs()
        if not jobs:
            return "No scheduled tasks. Use 'create' action to add one."

        lines = ["Scheduled Tasks:"]
        for j in jobs:
            status = "ON" if j["enabled"] else "OFF"
            next_ts = j.get("next_run", 0)
            if next_ts > 0:
                import datetime
                next_str = datetime.datetime.fromtimestamp(next_ts).strftime("%Y-%m-%d %H:%M")
            else:
                next_str = "not set"
            lines.append(
                f"  #{j['id']} [{status}] {j['cron_expr']} — {j['task'][:60]}"
                f"\n       next: {next_str} | channel: {j['channel']}"
            )
        return "\n".join(lines)

    if action == "create":
        cron_expr = args.get("cron_expr", "").strip()
        task = args.get("task", "").strip()
        chat_id = args.get("chat_id", 0)

        if not cron_expr:
            return "cron_expr is required. Use standard cron format (e.g., '0 10 * * *' for daily at 10:00, '*/10 * * * *' for every 10 minutes)."
        if not task:
            return "task description is required."

        if not validate_cron_expr(cron_expr):
            return (
                f"Invalid cron expression: '{cron_expr}'\n"
                "Format: minute hour day month weekday\n"
                "Examples:\n"
                "  0 10 * * *     Daily at 10:00\n"
                "  */10 * * * *   Every 10 minutes\n"
                "  0 9 * * 1-5    Weekdays at 09:00\n"
                "  0 */2 * * *    Every 2 hours"
            )

        next_run = compute_next_run(cron_expr)
        # Use provided chat_id or fall back to current context
        resolved_chat_id = int(chat_id) if chat_id else _current_chat_id
        job_id = create_cron_job(
            cron_expr=cron_expr,
            task=task,
            channel="telegram",
            chat_id=resolved_chat_id,
            created_by=_current_user_id,
            next_run=next_run,
        )

        import datetime
        next_str = datetime.datetime.fromtimestamp(next_run).strftime("%Y-%m-%d %H:%M") if next_run else "?"

        return (
            f"Scheduled task created (ID: #{job_id})\n"
            f"  Schedule: {cron_expr}\n"
            f"  Task: {task}\n"
            f"  Next run: {next_str}"
        )

    if action == "delete":
        job_id = args.get("job_id", 0)
        if not job_id:
            return "job_id is required."
        try:
            job_id = int(job_id)
        except (ValueError, TypeError):
            return f"Invalid job_id: {job_id}"
        if delete_cron_job(job_id):
            return f"Scheduled task #{job_id} deleted."
        return f"Task #{job_id} not found."

    if action == "enable":
        job_id = args.get("job_id", 0)
        try:
            job_id = int(job_id)
        except (ValueError, TypeError):
            return f"Invalid job_id: {job_id}"
        job = get_cron_job(job_id)
        if not job:
            return f"Task #{job_id} not found."
        next_run = compute_next_run(job["cron_expr"])
        update_cron_job(job_id, enabled=1, next_run=next_run)
        return f"Task #{job_id} enabled."

    if action == "disable":
        job_id = args.get("job_id", 0)
        try:
            job_id = int(job_id)
        except (ValueError, TypeError):
            return f"Invalid job_id: {job_id}"
        if not get_cron_job(job_id):
            return f"Task #{job_id} not found."
        update_cron_job(job_id, enabled=0)
        return f"Task #{job_id} disabled."

    if action == "run":
        job_id = args.get("job_id", 0)
        try:
            job_id = int(job_id)
        except (ValueError, TypeError):
            return f"Invalid job_id: {job_id}"
        job = get_cron_job(job_id)
        if not job:
            return f"Task #{job_id} not found."
        result = await execute_job(job)
        return f"[Manual run #{job_id}]\n{result}"

    return f"Unknown action: {action}. Available: create, list, delete, enable, disable, run"


register_tool(
    name="cron_manager",
    description="Manage scheduled tasks. Create, list, delete, enable/disable recurring tasks that run on a cron schedule.",
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "list", "delete", "enable", "disable", "run"],
                "description": "Action to perform",
            },
            "cron_expr": {
                "type": "string",
                "description": "Cron expression (e.g., '0 10 * * *' for daily at 10:00, '*/10 * * * *' for every 10 min)",
            },
            "task": {
                "type": "string",
                "description": "Task description — what the AI should do when this job runs",
            },
            "job_id": {
                "type": "integer",
                "description": "Job ID for delete/enable/disable/run actions",
            },
            "chat_id": {
                "type": "integer",
                "description": "Telegram chat ID to send results to",
            },
        },
        "required": ["action"],
    },
    execute=_cron_manager,
)
