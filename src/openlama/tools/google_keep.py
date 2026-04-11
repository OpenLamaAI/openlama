"""Google Keep tool — manage notes (Workspace only)."""

from __future__ import annotations

import asyncio

from openlama.tools.registry import register_tool
from openlama.tools.google_auth import build_service


def _svc():
    return build_service("keep", "v1")


async def _list(args: dict) -> str:
    max_results = int(args.get("max_results", 20))

    def _run():
        result = _svc().notes().list(pageSize=max_results).execute()
        notes = result.get("notes", [])
        if not notes:
            return "No notes found."
        lines = []
        for n in notes:
            title = n.get("title", "(untitled)")
            body_text = ""
            body = n.get("body", {})
            if body.get("text", {}).get("text"):
                body_text = body["text"]["text"][:80]
            elif body.get("list", {}).get("listItems"):
                items = [li.get("text", {}).get("text", "") for li in body["list"]["listItems"][:3]]
                body_text = "; ".join(items)
            lines.append(f"  {n.get('name', '')}  {title}  — {body_text}")
        return f"Notes ({len(notes)}):\n" + "\n".join(lines)
    return await asyncio.to_thread(_run)


async def _get(args: dict) -> str:
    note_id = args.get("note_id", "")

    def _run():
        n = _svc().notes().get(name=note_id).execute()
        title = n.get("title", "(untitled)")
        body = n.get("body", {})
        body_text = ""
        if body.get("text", {}).get("text"):
            body_text = body["text"]["text"]
        elif body.get("list", {}).get("listItems"):
            items = []
            for li in body["list"]["listItems"]:
                checked = "✓" if li.get("checked") else "○"
                items.append(f"  {checked} {li.get('text', {}).get('text', '')}")
            body_text = "\n".join(items)
        return f"Title: {title}\nID: {n.get('name', '')}\nCreated: {n.get('createTime', '')}\n\n{body_text}"
    return await asyncio.to_thread(_run)


async def _create(args: dict) -> str:
    title = args.get("title", "")
    text = args.get("text", "")
    items = args.get("items", [])

    def _run():
        body = {"title": title}
        if items:
            body["body"] = {"list": {"listItems": [{"text": {"text": i}} for i in items]}}
        else:
            body["body"] = {"text": {"text": text}}
        n = _svc().notes().create(body=body).execute()
        return f"Note created: {title}\nID: {n.get('name', '')}"
    return await asyncio.to_thread(_run)


async def _delete(args: dict) -> str:
    note_id = args.get("note_id", "")

    def _run():
        _svc().notes().delete(name=note_id).execute()
        return f"Note deleted: {note_id}"
    return await asyncio.to_thread(_run)


async def _search(args: dict) -> str:
    query = args.get("query", "")
    max_results = int(args.get("max_results", 10))

    def _run():
        # Keep API list doesn't support text search filters directly;
        # fetch all and filter client-side
        result = _svc().notes().list(pageSize=100).execute()
        notes = result.get("notes", [])
        q = query.lower()
        matched = []
        for n in notes:
            title = n.get("title", "").lower()
            body = n.get("body", {})
            body_text = body.get("text", {}).get("text", "").lower()
            if q in title or q in body_text:
                matched.append(n)
            if len(matched) >= max_results:
                break
        if not matched:
            return f"No notes matching '{query}'."
        lines = [f"  {n.get('name', '')}  {n.get('title', '?')}" for n in matched]
        return f"Search results ({len(matched)}):\n" + "\n".join(lines)
    return await asyncio.to_thread(_run)


async def _attachment(args: dict) -> str:
    note_id = args.get("note_id", "")
    attachment_name = args.get("attachment_name", "")

    def _run():
        att = _svc().media().download(name=attachment_name).execute()
        from openlama.config import DATA_DIR
        out_dir = DATA_DIR / "tmp_uploads"
        out_dir.mkdir(parents=True, exist_ok=True)
        filename = attachment_name.split("/")[-1] or "attachment"
        out_path = out_dir / filename
        out_path.write_bytes(att if isinstance(att, bytes) else att.encode())
        return f"Attachment saved: {out_path}"
    return await asyncio.to_thread(_run)


_ACTIONS = {
    "list": _list,
    "get": _get,
    "create": _create,
    "delete": _delete,
    "search": _search,
    "attachment": _attachment,
}


async def _execute(args: dict) -> str:
    action = args.get("action", "")
    fn = _ACTIONS.get(action)
    if not fn:
        return f"Unknown action: {action}. Available: {', '.join(sorted(_ACTIONS))}"
    return await fn(args)


register_tool(
    name="google_keep",
    description=(
        "Manage Google Keep notes: list, view, create (text or checklist), search, delete. "
        "Note: Keep API is only available for Google Workspace accounts. "
        "Requires Google authentication."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(_ACTIONS.keys()), "description": "Keep action"},
            "note_id": {"type": "string", "description": "Note ID (notes/xxx format)"},
            "title": {"type": "string", "description": "Note title"},
            "text": {"type": "string", "description": "Note text content"},
            "items": {"type": "array", "items": {"type": "string"}, "description": "Checklist items"},
            "query": {"type": "string", "description": "Search query"},
            "max_results": {"type": "integer", "description": "Max results"},
        },
        "required": ["action"],
    },
    execute=_execute,
)
