"""Google Docs tool — read, create, edit, export documents."""

from __future__ import annotations

import asyncio

from openlama.tools.registry import register_tool
from openlama.tools.google_auth import build_service
from openlama.config import DATA_DIR


def _docs_svc():
    return build_service("docs", "v1")


def _drive_svc():
    return build_service("drive", "v3")


def _extract_text(body: dict) -> str:
    """Extract plain text from Docs document body."""
    text_parts = []
    for elem in body.get("content", []):
        para = elem.get("paragraph", {})
        for pe in para.get("elements", []):
            tr = pe.get("textRun", {})
            if tr.get("content"):
                text_parts.append(tr["content"])
    return "".join(text_parts)


async def _info(args: dict) -> str:
    doc_id = args.get("doc_id", "")

    def _run():
        doc = _docs_svc().documents().get(documentId=doc_id).execute()
        return (
            f"Title: {doc.get('title', '')}\n"
            f"ID: {doc.get('documentId', '')}\n"
            f"Revision: {doc.get('revisionId', '')}\n"
            f"Tabs: {len(doc.get('tabs', []))}"
        )
    return await asyncio.to_thread(_run)


async def _read(args: dict) -> str:
    doc_id = args.get("doc_id", "")
    max_chars = int(args.get("max_chars", 5000))

    def _run():
        doc = _docs_svc().documents().get(documentId=doc_id).execute()
        title = doc.get("title", "")
        body = doc.get("body", {})
        text = _extract_text(body)
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n... (truncated, {len(text)} total chars)"
        return f"Title: {title}\n\n{text}"
    return await asyncio.to_thread(_run)


async def _create(args: dict) -> str:
    title = args.get("title", "Untitled")
    content = args.get("content", "")

    def _run():
        doc = _docs_svc().documents().create(body={"title": title}).execute()
        doc_id = doc["documentId"]
        if content:
            _docs_svc().documents().batchUpdate(documentId=doc_id, body={
                "requests": [{"insertText": {"location": {"index": 1}, "text": content}}]
            }).execute()
        return f"Document created: {title}\nID: {doc_id}\nLink: https://docs.google.com/document/d/{doc_id}"
    return await asyncio.to_thread(_run)


async def _copy(args: dict) -> str:
    doc_id = args.get("doc_id", "")
    name = args.get("name", "")

    def _run():
        body = {"name": name} if name else {}
        f = _drive_svc().files().copy(fileId=doc_id, body=body, fields="id,name").execute()
        return f"Copied: {f['name']} (ID: {f['id']})"
    return await asyncio.to_thread(_run)


async def _export(args: dict) -> str:
    doc_id = args.get("doc_id", "")
    fmt = args.get("format", "pdf")

    def _run():
        import httpx
        from openlama.tools.google_auth import get_google_creds
        creds = get_google_creds()
        mime_map = {
            "pdf": "application/pdf",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "txt": "text/plain",
            "html": "text/html",
            "md": "text/markdown",
        }
        mime = mime_map.get(fmt, f"application/{fmt}")
        url = f"https://www.googleapis.com/drive/v3/files/{doc_id}/export?mimeType={mime}"
        resp = httpx.get(url, headers={"Authorization": f"Bearer {creds.token}"}, timeout=60)
        resp.raise_for_status()
        out_dir = DATA_DIR / "tmp_uploads"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"doc_export.{fmt}"
        out_path.write_bytes(resp.content)
        return f"Exported: {out_path} ({out_path.stat().st_size:,} bytes)"
    return await asyncio.to_thread(_run)


async def _write(args: dict) -> str:
    """Overwrite document body with new text."""
    doc_id = args.get("doc_id", "")
    text = args.get("text", "")

    def _run():
        svc = _docs_svc()
        doc = svc.documents().get(documentId=doc_id).execute()
        content = doc.get("body", {}).get("content", [])
        requests = []
        if len(content) > 1:
            end_index = content[-1].get("endIndex", 1)
            if end_index > 2:
                requests.append({"deleteContentRange": {"range": {"startIndex": 1, "endIndex": end_index - 1}}})
        requests.append({"insertText": {"location": {"index": 1}, "text": text}})
        svc.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()
        return f"Document overwritten with {len(text)} characters."
    return await asyncio.to_thread(_run)


async def _list_tabs(args: dict) -> str:
    doc_id = args.get("doc_id", "")

    def _run():
        doc = _docs_svc().documents().get(documentId=doc_id).execute()
        tabs = doc.get("tabs", [])
        if not tabs:
            return "No tabs (single-tab document)."
        lines = [f"  {i + 1}. {t.get('tabProperties', {}).get('title', '?')} (ID: {t.get('tabProperties', {}).get('tabId', '')})" for i, t in enumerate(tabs)]
        return f"Tabs ({len(tabs)}):\n" + "\n".join(lines)
    return await asyncio.to_thread(_run)


async def _update(args: dict) -> str:
    doc_id = args.get("doc_id", "")
    text = args.get("text", "")
    index = int(args.get("index", 1))

    def _run():
        _docs_svc().documents().batchUpdate(documentId=doc_id, body={
            "requests": [{"insertText": {"location": {"index": index}, "text": text}}]
        }).execute()
        return f"Inserted {len(text)} characters at index {index}."
    return await asyncio.to_thread(_run)


async def _find_replace(args: dict) -> str:
    doc_id = args.get("doc_id", "")
    find = args.get("find", "")
    replace = args.get("replace", "")

    def _run():
        result = _docs_svc().documents().batchUpdate(documentId=doc_id, body={
            "requests": [{"replaceAllText": {"containsText": {"text": find, "matchCase": True}, "replaceText": replace}}]
        }).execute()
        count = sum(r.get("replaceAllText", {}).get("occurrencesChanged", 0) for r in result.get("replies", []))
        return f"Replaced {count} occurrence(s) of '{find}' with '{replace}'."
    return await asyncio.to_thread(_run)


async def _clear(args: dict) -> str:
    doc_id = args.get("doc_id", "")

    def _run():
        doc = _docs_svc().documents().get(documentId=doc_id).execute()
        body = doc.get("body", {})
        content = body.get("content", [])
        if len(content) <= 1:
            return "Document is already empty."
        end_index = content[-1].get("endIndex", 1)
        if end_index <= 2:
            return "Document is already empty."
        _docs_svc().documents().batchUpdate(documentId=doc_id, body={
            "requests": [{"deleteContentRange": {"range": {"startIndex": 1, "endIndex": end_index - 1}}}]
        }).execute()
        return "Document cleared."
    return await asyncio.to_thread(_run)


async def _structure(args: dict) -> str:
    doc_id = args.get("doc_id", "")

    def _run():
        doc = _docs_svc().documents().get(documentId=doc_id).execute()
        lines = []
        for i, elem in enumerate(doc.get("body", {}).get("content", [])):
            para = elem.get("paragraph", {})
            style = para.get("paragraphStyle", {}).get("namedStyleType", "")
            text = "".join(pe.get("textRun", {}).get("content", "") for pe in para.get("elements", []))
            text = text.strip()
            if text:
                prefix = f"[{style}]" if style and style != "NORMAL_TEXT" else ""
                lines.append(f"  {i:3d}. {prefix} {text[:80]}")
        return f"Structure ({len(lines)} paragraphs):\n" + "\n".join(lines)
    return await asyncio.to_thread(_run)


async def _comments_list(args: dict) -> str:
    doc_id = args.get("doc_id", "")

    def _run():
        comments = _drive_svc().comments().list(
            fileId=doc_id,
            fields="comments(id,author,content,createdTime,resolved)",
        ).execute().get("comments", [])
        if not comments:
            return "No comments."
        lines = [f"  {c['id']} [{c.get('author', {}).get('displayName', '?')}] {c.get('content', '')[:100]}" for c in comments]
        return f"Comments ({len(comments)}):\n" + "\n".join(lines)
    return await asyncio.to_thread(_run)


async def _comments_add(args: dict) -> str:
    doc_id = args.get("doc_id", "")
    content = args.get("content", "")

    def _run():
        c = _drive_svc().comments().create(fileId=doc_id, body={"content": content}, fields="id").execute()
        return f"Comment added. ID: {c['id']}"
    return await asyncio.to_thread(_run)


async def _comments_resolve(args: dict) -> str:
    doc_id = args.get("doc_id", "")
    comment_id = args.get("comment_id", "")

    def _run():
        _drive_svc().comments().update(fileId=doc_id, commentId=comment_id, body={"resolved": True}, fields="id").execute()
        return f"Comment resolved: {comment_id}"
    return await asyncio.to_thread(_run)


async def _comments_reply(args: dict) -> str:
    doc_id = args.get("doc_id", "")
    comment_id = args.get("comment_id", "")
    content = args.get("content", "")

    def _run():
        r = _drive_svc().replies().create(fileId=doc_id, commentId=comment_id, body={"content": content}, fields="id").execute()
        return f"Reply added. ID: {r['id']}"
    return await asyncio.to_thread(_run)


async def _comments_delete(args: dict) -> str:
    doc_id = args.get("doc_id", "")
    comment_id = args.get("comment_id", "")

    def _run():
        _drive_svc().comments().delete(fileId=doc_id, commentId=comment_id).execute()
        return f"Comment deleted: {comment_id}"
    return await asyncio.to_thread(_run)


# ── Dispatcher ───────────────────────────────────────

_ACTIONS = {
    "info": _info,
    "read": _read,
    "create": _create,
    "copy": _copy,
    "export": _export,
    "write": _write,
    "list_tabs": _list_tabs,
    "update": _update,
    "find_replace": _find_replace,
    "clear": _clear,
    "structure": _structure,
    "comments_list": _comments_list,
    "comments_add": _comments_add,
    "comments_resolve": _comments_resolve,
    "comments_reply": _comments_reply,
    "comments_delete": _comments_delete,
}


async def _execute(args: dict) -> str:
    action = args.get("action", "")
    fn = _ACTIONS.get(action)
    if not fn:
        return f"Unknown action: {action}. Available: {', '.join(sorted(_ACTIONS))}"
    return await fn(args)


register_tool(
    name="google_docs",
    description=(
        "Manage Google Docs: read content, create/copy documents, export (pdf/docx/txt/html), "
        "insert text, find & replace, view structure, manage comments. "
        "Requires Google authentication."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(_ACTIONS.keys()), "description": "Docs action"},
            "doc_id": {"type": "string", "description": "Document ID"},
            "title": {"type": "string", "description": "Document title"},
            "content": {"type": "string", "description": "Text content or comment content"},
            "name": {"type": "string", "description": "Copy name"},
            "text": {"type": "string", "description": "Text to insert"},
            "index": {"type": "integer", "description": "Insert position index"},
            "find": {"type": "string", "description": "Text to find"},
            "replace": {"type": "string", "description": "Replacement text"},
            "format": {"type": "string", "enum": ["pdf", "docx", "txt", "html", "md"], "description": "Export format"},
            "max_chars": {"type": "integer", "description": "Max chars to read"},
            "comment_id": {"type": "string", "description": "Comment ID"},
        },
        "required": ["action"],
    },
    execute=_execute,
)
