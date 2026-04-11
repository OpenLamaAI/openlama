"""Google Chat tool — manage spaces, messages, DMs (Workspace only)."""

from __future__ import annotations

import asyncio

from openlama.tools.registry import register_tool
from openlama.tools.google_auth import build_service


def _svc():
    return build_service("chat", "v1")


async def _spaces_list(args: dict) -> str:
    def _run():
        result = _svc().spaces().list(pageSize=50).execute()
        spaces = result.get("spaces", [])
        if not spaces:
            return "No spaces."
        lines = [f"  {s.get('name', '')}  {s.get('displayName', '?')}  type={s.get('spaceType', '?')}" for s in spaces]
        return f"Spaces ({len(spaces)}):\n" + "\n".join(lines)
    return await asyncio.to_thread(_run)


async def _spaces_find(args: dict) -> str:
    query = args.get("query", "")

    def _run():
        result = _svc().spaces().search(query=query, pageSize=20).execute()
        spaces = result.get("spaces", [])
        if not spaces:
            return f"No spaces matching '{query}'."
        lines = [f"  {s.get('name', '')}  {s.get('displayName', '?')}" for s in spaces]
        return f"Search results ({len(spaces)}):\n" + "\n".join(lines)
    return await asyncio.to_thread(_run)


async def _spaces_create(args: dict) -> str:
    display_name = args.get("display_name", "")
    members = args.get("members", [])

    def _run():
        body = {"displayName": display_name, "spaceType": "SPACE"}
        if members:
            body["membership"] = [{"member": {"name": f"users/{m}", "type": "HUMAN"}} for m in members]
        space = _svc().spaces().create(body=body).execute()
        return f"Space created: {space.get('displayName', '')} ({space.get('name', '')})"
    return await asyncio.to_thread(_run)


async def _messages_list(args: dict) -> str:
    space_name = args.get("space_name", "")
    max_results = int(args.get("max_results", 20))

    def _run():
        result = _svc().spaces().messages().list(parent=space_name, pageSize=max_results).execute()
        msgs = result.get("messages", [])
        if not msgs:
            return "No messages."
        lines = []
        for m in msgs:
            sender = m.get("sender", {}).get("displayName", "?")
            text = m.get("text", "")[:100]
            lines.append(f"  [{m.get('createTime', '?')}] {sender}: {text}")
        return f"Messages ({len(msgs)}):\n" + "\n".join(lines)
    return await asyncio.to_thread(_run)


async def _messages_send(args: dict) -> str:
    space_name = args.get("space_name", "")
    text = args.get("text", "")
    thread_key = args.get("thread_key", "")

    def _run():
        body = {"text": text}
        if thread_key:
            body["thread"] = {"threadKey": thread_key}
        msg = _svc().spaces().messages().create(parent=space_name, body=body).execute()
        return f"Message sent. ID: {msg.get('name', '')}"
    return await asyncio.to_thread(_run)


async def _dm_send(args: dict) -> str:
    email = args.get("email", "")
    text = args.get("text", "")

    def _run():
        # Find or create DM space
        dm = _svc().spaces().findDirectMessage(name=f"users/{email}").execute()
        space_name = dm.get("name", "")
        if not space_name:
            dm = _svc().spaces().setup(body={
                "spaceType": "DIRECT_MESSAGE",
                "memberships": [{"member": {"name": f"users/{email}", "type": "HUMAN"}}],
            }).execute()
            space_name = dm.get("name", "")
        msg = _svc().spaces().messages().create(parent=space_name, body={"text": text}).execute()
        return f"DM sent to {email}. ID: {msg.get('name', '')}"
    return await asyncio.to_thread(_run)


async def _reactions_list(args: dict) -> str:
    message_name = args.get("message_name", "")

    def _run():
        result = _svc().spaces().messages().reactions().list(parent=message_name).execute()
        reactions = result.get("reactions", [])
        if not reactions:
            return "No reactions."
        lines = [f"  {r.get('emoji', {}).get('unicode', '?')} by {r.get('user', {}).get('displayName', '?')}" for r in reactions]
        return f"Reactions ({len(reactions)}):\n" + "\n".join(lines)
    return await asyncio.to_thread(_run)


async def _react(args: dict) -> str:
    message_name = args.get("message_name", "")
    emoji = args.get("emoji", "")

    def _run():
        _svc().spaces().messages().reactions().create(
            parent=message_name, body={"emoji": {"unicode": emoji}},
        ).execute()
        return f"Reaction '{emoji}' added."
    return await asyncio.to_thread(_run)


_ACTIONS = {
    "spaces_list": _spaces_list,
    "spaces_find": _spaces_find,
    "spaces_create": _spaces_create,
    "messages_list": _messages_list,
    "messages_send": _messages_send,
    "dm_send": _dm_send,
    "reactions_list": _reactions_list,
    "react": _react,
}


async def _execute(args: dict) -> str:
    action = args.get("action", "")
    fn = _ACTIONS.get(action)
    if not fn:
        return f"Unknown action: {action}. Available: {', '.join(sorted(_ACTIONS))}"
    return await fn(args)


register_tool(
    name="google_chat",
    description=(
        "Google Chat (Workspace): list/search/create spaces, send/list messages, "
        "send DMs, manage reactions. Requires Google Workspace account."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(_ACTIONS.keys()), "description": "Chat action"},
            "space_name": {"type": "string", "description": "Space name (e.g. spaces/xxx)"},
            "display_name": {"type": "string", "description": "Space display name"},
            "members": {"type": "array", "items": {"type": "string"}, "description": "Member emails"},
            "text": {"type": "string", "description": "Message text"},
            "thread_key": {"type": "string", "description": "Thread key for threaded replies"},
            "email": {"type": "string", "description": "Email for DM"},
            "message_name": {"type": "string", "description": "Message name for reactions"},
            "emoji": {"type": "string", "description": "Emoji unicode (e.g. 👍)"},
            "query": {"type": "string", "description": "Search query"},
            "max_results": {"type": "integer", "description": "Max results"},
        },
        "required": ["action"],
    },
    execute=_execute,
)
