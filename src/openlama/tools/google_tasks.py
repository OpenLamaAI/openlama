"""Google Tasks tool — manage task lists and tasks."""

from __future__ import annotations

import asyncio

from openlama.tools.registry import register_tool
from openlama.tools.google_auth import build_service


def _svc():
    return build_service("tasks", "v1")


async def _lists(args: dict) -> str:
    def _run():
        result = _svc().tasklists().list(maxResults=100).execute()
        items = result.get("items", [])
        if not items:
            return "No task lists."
        lines = [f"  {t['id']}  {t.get('title', '?')}" for t in items]
        return f"Task lists ({len(items)}):\n" + "\n".join(lines)
    return await asyncio.to_thread(_run)


async def _list(args: dict) -> str:
    tasklist_id = args.get("tasklist_id", "@default")
    max_results = int(args.get("max_results", 20))

    def _run():
        result = _svc().tasks().list(tasklist=tasklist_id, maxResults=max_results, showCompleted=True).execute()
        items = result.get("items", [])
        if not items:
            return "No tasks."
        lines = []
        for t in items:
            status = "✓" if t.get("status") == "completed" else "○"
            due = f" (due: {t.get('due', '')[:10]})" if t.get("due") else ""
            lines.append(f"  {status} {t['id']}  {t.get('title', '?')}{due}")
        return f"Tasks ({len(items)}):\n" + "\n".join(lines)
    return await asyncio.to_thread(_run)


async def _add(args: dict) -> str:
    tasklist_id = args.get("tasklist_id", "@default")
    title = args.get("title", "")
    due = args.get("due", "")
    notes = args.get("notes", "")

    def _run():
        body = {"title": title}
        if due:
            body["due"] = due + "T00:00:00.000Z" if "T" not in due else due
        if notes:
            body["notes"] = notes
        t = _svc().tasks().insert(tasklist=tasklist_id, body=body).execute()
        return f"Task added: {t.get('title', '')} (ID: {t['id']})"
    return await asyncio.to_thread(_run)


async def _update(args: dict) -> str:
    tasklist_id = args.get("tasklist_id", "@default")
    task_id = args.get("task_id", "")
    title = args.get("title", "")
    notes = args.get("notes", "")
    due = args.get("due", "")

    def _run():
        svc = _svc()
        t = svc.tasks().get(tasklist=tasklist_id, task=task_id).execute()
        if title:
            t["title"] = title
        if notes:
            t["notes"] = notes
        if due:
            t["due"] = due + "T00:00:00.000Z" if "T" not in due else due
        updated = svc.tasks().update(tasklist=tasklist_id, task=task_id, body=t).execute()
        return f"Task updated: {updated.get('title', '')}"
    return await asyncio.to_thread(_run)


async def _done(args: dict) -> str:
    tasklist_id = args.get("tasklist_id", "@default")
    task_id = args.get("task_id", "")

    def _run():
        svc = _svc()
        t = svc.tasks().get(tasklist=tasklist_id, task=task_id).execute()
        t["status"] = "completed"
        svc.tasks().update(tasklist=tasklist_id, task=task_id, body=t).execute()
        return f"Task completed: {t.get('title', '')}"
    return await asyncio.to_thread(_run)


async def _undo(args: dict) -> str:
    tasklist_id = args.get("tasklist_id", "@default")
    task_id = args.get("task_id", "")

    def _run():
        svc = _svc()
        t = svc.tasks().get(tasklist=tasklist_id, task=task_id).execute()
        t["status"] = "needsAction"
        t.pop("completed", None)
        svc.tasks().update(tasklist=tasklist_id, task=task_id, body=t).execute()
        return f"Task reopened: {t.get('title', '')}"
    return await asyncio.to_thread(_run)


async def _delete(args: dict) -> str:
    tasklist_id = args.get("tasklist_id", "@default")
    task_id = args.get("task_id", "")

    def _run():
        _svc().tasks().delete(tasklist=tasklist_id, task=task_id).execute()
        return f"Task deleted: {task_id}"
    return await asyncio.to_thread(_run)


async def _clear(args: dict) -> str:
    tasklist_id = args.get("tasklist_id", "@default")

    def _run():
        _svc().tasks().clear(tasklist=tasklist_id).execute()
        return "Completed tasks cleared."
    return await asyncio.to_thread(_run)


async def _lists_create(args: dict) -> str:
    title = args.get("title", "")

    def _run():
        tl = _svc().tasklists().insert(body={"title": title}).execute()
        return f"Task list created: {tl.get('title', '')} (ID: {tl['id']})"
    return await asyncio.to_thread(_run)


_ACTIONS = {
    "lists": _lists,
    "list": _list,
    "add": _add,
    "update": _update,
    "done": _done,
    "undo": _undo,
    "delete": _delete,
    "clear": _clear,
    "lists_create": _lists_create,
}


async def _execute(args: dict) -> str:
    action = args.get("action", "")
    fn = _ACTIONS.get(action)
    if not fn:
        return f"Unknown action: {action}. Available: {', '.join(sorted(_ACTIONS))}"
    return await fn(args)


register_tool(
    name="google_tasks",
    description=(
        "Manage Google Tasks: list task lists, view/add/update/complete/delete tasks, "
        "clear completed tasks. Requires Google authentication."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(_ACTIONS.keys()), "description": "Tasks action"},
            "tasklist_id": {"type": "string", "description": "Task list ID (default: @default)"},
            "task_id": {"type": "string", "description": "Task ID"},
            "title": {"type": "string", "description": "Task/list title"},
            "notes": {"type": "string", "description": "Task notes"},
            "due": {"type": "string", "description": "Due date (YYYY-MM-DD)"},
            "max_results": {"type": "integer", "description": "Max results"},
        },
        "required": ["action"],
    },
    execute=_execute,
)
