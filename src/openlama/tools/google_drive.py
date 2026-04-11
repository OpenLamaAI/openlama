"""Google Drive tool — file management, search, upload, download, sharing."""

from __future__ import annotations

import asyncio
import io
from pathlib import Path

from openlama.tools.registry import register_tool
from openlama.tools.google_auth import build_service
from openlama.config import DATA_DIR


def _svc():
    return build_service("drive", "v3")


def _format_file(f: dict) -> str:
    size = f.get("size", "")
    size_str = f" ({int(size):,} bytes)" if size else ""
    return (
        f"ID: {f['id']}  Name: {f.get('name', '?')}  "
        f"Type: {f.get('mimeType', '?')}{size_str}  "
        f"Modified: {f.get('modifiedTime', '?')}"
    )


async def _list(args: dict) -> str:
    parent = args.get("parent", "")
    max_results = int(args.get("max_results", 20))

    def _run():
        q = f"'{parent}' in parents" if parent else None
        kwargs = {"pageSize": max_results, "fields": "files(id,name,mimeType,size,modifiedTime)", "supportsAllDrives": True, "includeItemsFromAllDrives": True}
        if q:
            kwargs["q"] = q
        files = _svc().files().list(**kwargs).execute().get("files", [])
        if not files:
            return "No files found."
        return f"Files ({len(files)}):\n" + "\n".join(f"  {_format_file(f)}" for f in files)
    return await asyncio.to_thread(_run)


async def _search(args: dict) -> str:
    query = args.get("query", "")
    max_results = int(args.get("max_results", 10))

    def _run():
        q = f"name contains '{query}' or fullText contains '{query}'"
        files = _svc().files().list(
            q=q, pageSize=max_results,
            fields="files(id,name,mimeType,size,modifiedTime)",
            supportsAllDrives=True, includeItemsFromAllDrives=True,
        ).execute().get("files", [])
        if not files:
            return f"No files matching '{query}'."
        return f"Search results ({len(files)}):\n" + "\n".join(f"  {_format_file(f)}" for f in files)
    return await asyncio.to_thread(_run)


async def _get(args: dict) -> str:
    file_id = args.get("file_id", "")

    def _run():
        f = _svc().files().get(fileId=file_id, fields="*", supportsAllDrives=True).execute()
        lines = [
            f"Name: {f.get('name', '')}",
            f"ID: {f['id']}",
            f"Type: {f.get('mimeType', '')}",
            f"Size: {f.get('size', 'N/A')}",
            f"Created: {f.get('createdTime', '')}",
            f"Modified: {f.get('modifiedTime', '')}",
            f"Owners: {', '.join(o.get('emailAddress', '') for o in f.get('owners', []))}",
            f"Web link: {f.get('webViewLink', '')}",
        ]
        return "\n".join(lines)
    return await asyncio.to_thread(_run)


async def _download(args: dict) -> str:
    file_id = args.get("file_id", "")
    export_format = args.get("format", "")

    def _run():
        svc = _svc()
        meta = svc.files().get(fileId=file_id, fields="name,mimeType", supportsAllDrives=True).execute()
        name = meta.get("name", "download")
        mime = meta.get("mimeType", "")

        out_dir = DATA_DIR / "tmp_uploads"
        out_dir.mkdir(parents=True, exist_ok=True)

        export_mimes = {
            "pdf": "application/pdf",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "txt": "text/plain",
            "csv": "text/csv",
            "html": "text/html",
        }

        if mime.startswith("application/vnd.google-apps.") or export_format:
            fmt = export_format or "pdf"
            export_mime = export_mimes.get(fmt, f"application/{fmt}")
            import httpx as _httpx
            from openlama.tools.google_auth import get_google_creds
            creds = get_google_creds()
            url = f"https://www.googleapis.com/drive/v3/files/{file_id}/export?mimeType={export_mime}"
            resp = _httpx.get(url, headers={"Authorization": f"Bearer {creds.token}"}, timeout=120)
            resp.raise_for_status()
            data = resp.content
            ext = fmt
        else:
            from googleapiclient.http import MediaIoBaseDownload
            request = svc.files().get_media(fileId=file_id, supportsAllDrives=True)
            buf = io.BytesIO()
            downloader = MediaIoBaseDownload(buf, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            data = buf.getvalue()
            ext = Path(name).suffix or ""

        out_path = out_dir / f"{Path(name).stem}.{ext}" if ext else out_dir / name
        if isinstance(data, bytes):
            out_path.write_bytes(data)
        else:
            out_path.write_bytes(data)
        return f"Downloaded: {out_path} ({out_path.stat().st_size:,} bytes)"
    return await asyncio.to_thread(_run)


async def _upload(args: dict) -> str:
    file_path = args.get("file_path", "")
    parent = args.get("parent", "")
    name = args.get("name", "")

    def _run():
        from googleapiclient.http import MediaFileUpload
        p = Path(file_path)
        if not p.exists():
            return f"File not found: {file_path}"
        fname = name or p.name
        body = {"name": fname}
        if parent:
            body["parents"] = [parent]
        media = MediaFileUpload(str(p))
        f = _svc().files().create(body=body, media_body=media, fields="id,name,webViewLink", supportsAllDrives=True).execute()
        return f"Uploaded: {f.get('name', '')} (ID: {f['id']})\nLink: {f.get('webViewLink', '')}"
    return await asyncio.to_thread(_run)


async def _mkdir(args: dict) -> str:
    name = args.get("name", "")
    parent = args.get("parent", "")

    def _run():
        body = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
        if parent:
            body["parents"] = [parent]
        f = _svc().files().create(body=body, fields="id,name", supportsAllDrives=True).execute()
        return f"Folder created: {f['name']} (ID: {f['id']})"
    return await asyncio.to_thread(_run)


async def _copy(args: dict) -> str:
    file_id = args.get("file_id", "")
    name = args.get("name", "")

    def _run():
        body = {"name": name} if name else {}
        f = _svc().files().copy(fileId=file_id, body=body, fields="id,name", supportsAllDrives=True).execute()
        return f"Copied: {f['name']} (ID: {f['id']})"
    return await asyncio.to_thread(_run)


async def _rename(args: dict) -> str:
    file_id = args.get("file_id", "")
    name = args.get("name", "")

    def _run():
        f = _svc().files().update(fileId=file_id, body={"name": name}, fields="id,name", supportsAllDrives=True).execute()
        return f"Renamed to: {f['name']}"
    return await asyncio.to_thread(_run)


async def _move(args: dict) -> str:
    file_id = args.get("file_id", "")
    parent = args.get("parent", "")

    def _run():
        svc = _svc()
        current = svc.files().get(fileId=file_id, fields="parents", supportsAllDrives=True).execute()
        old_parents = ",".join(current.get("parents", []))
        f = svc.files().update(fileId=file_id, addParents=parent, removeParents=old_parents, fields="id,name", supportsAllDrives=True).execute()
        return f"Moved: {f['name']} to folder {parent}"
    return await asyncio.to_thread(_run)


async def _delete(args: dict) -> str:
    file_id = args.get("file_id", "")
    permanent = args.get("permanent", False)

    def _run():
        if permanent:
            _svc().files().delete(fileId=file_id, supportsAllDrives=True).execute()
            return f"Permanently deleted: {file_id}"
        else:
            _svc().files().update(fileId=file_id, body={"trashed": True}, supportsAllDrives=True).execute()
            return f"Trashed: {file_id}"
    return await asyncio.to_thread(_run)


async def _share(args: dict) -> str:
    file_id = args.get("file_id", "")
    email = args.get("email", "")
    role = args.get("role", "reader")
    share_type = args.get("type", "user")

    def _run():
        body = {"type": share_type, "role": role}
        if email:
            body["emailAddress"] = email
        perm = _svc().permissions().create(fileId=file_id, body=body, sendNotificationEmail=True, supportsAllDrives=True).execute()
        return f"Shared with {email or share_type} as {role}. Permission ID: {perm['id']}"
    return await asyncio.to_thread(_run)


async def _unshare(args: dict) -> str:
    file_id = args.get("file_id", "")
    permission_id = args.get("permission_id", "")

    def _run():
        _svc().permissions().delete(fileId=file_id, permissionId=permission_id, supportsAllDrives=True).execute()
        return f"Permission removed: {permission_id}"
    return await asyncio.to_thread(_run)


async def _permissions(args: dict) -> str:
    file_id = args.get("file_id", "")

    def _run():
        perms = _svc().permissions().list(fileId=file_id, fields="permissions(id,type,role,emailAddress)", supportsAllDrives=True).execute().get("permissions", [])
        if not perms:
            return "No permissions."
        lines = [f"  {p['id']:20s} {p.get('type', ''):10s} {p.get('role', ''):10s} {p.get('emailAddress', '')}" for p in perms]
        return f"Permissions ({len(perms)}):\n" + "\n".join(lines)
    return await asyncio.to_thread(_run)


async def _comments_list(args: dict) -> str:
    file_id = args.get("file_id", "")

    def _run():
        comments = _svc().comments().list(fileId=file_id, fields="comments(id,author,content,createdTime,resolved)").execute().get("comments", [])
        if not comments:
            return "No comments."
        lines = [f"  {c['id']} [{c.get('author', {}).get('displayName', '?')}] {c.get('content', '')[:100]} ({'resolved' if c.get('resolved') else 'open'})" for c in comments]
        return f"Comments ({len(comments)}):\n" + "\n".join(lines)
    return await asyncio.to_thread(_run)


async def _comments_create(args: dict) -> str:
    file_id = args.get("file_id", "")
    content = args.get("content", "")

    def _run():
        c = _svc().comments().create(fileId=file_id, body={"content": content}, fields="id").execute()
        return f"Comment created. ID: {c['id']}"
    return await asyncio.to_thread(_run)


async def _comments_get(args: dict) -> str:
    file_id = args.get("file_id", "")
    comment_id = args.get("comment_id", "")

    def _run():
        c = _svc().comments().get(fileId=file_id, commentId=comment_id, fields="id,author,content,createdTime,resolved,replies").execute()
        lines = [
            f"ID: {c['id']}",
            f"Author: {c.get('author', {}).get('displayName', '?')}",
            f"Content: {c.get('content', '')}",
            f"Created: {c.get('createdTime', '')}",
            f"Resolved: {c.get('resolved', False)}",
        ]
        replies = c.get("replies", [])
        if replies:
            lines.append(f"Replies ({len(replies)}):")
            for r in replies:
                lines.append(f"  [{r.get('author', {}).get('displayName', '?')}] {r.get('content', '')}")
        return "\n".join(lines)
    return await asyncio.to_thread(_run)


async def _comments_update(args: dict) -> str:
    file_id = args.get("file_id", "")
    comment_id = args.get("comment_id", "")
    content = args.get("content", "")

    def _run():
        _svc().comments().update(fileId=file_id, commentId=comment_id, body={"content": content}, fields="id").execute()
        return f"Comment updated: {comment_id}"
    return await asyncio.to_thread(_run)


async def _comments_delete(args: dict) -> str:
    file_id = args.get("file_id", "")
    comment_id = args.get("comment_id", "")

    def _run():
        _svc().comments().delete(fileId=file_id, commentId=comment_id).execute()
        return f"Comment deleted: {comment_id}"
    return await asyncio.to_thread(_run)


async def _comments_reply(args: dict) -> str:
    file_id = args.get("file_id", "")
    comment_id = args.get("comment_id", "")
    content = args.get("content", "")

    def _run():
        r = _svc().replies().create(fileId=file_id, commentId=comment_id, body={"content": content}, fields="id").execute()
        return f"Reply added. ID: {r['id']}"
    return await asyncio.to_thread(_run)


async def _drives(args: dict) -> str:
    """List shared/team drives."""
    max_results = int(args.get("max_results", 20))

    def _run():
        result = _svc().drives().list(pageSize=max_results).execute()
        drives = result.get("drives", [])
        if not drives:
            return "No shared drives."
        lines = [f"  {d['id']}  {d.get('name', '?')}" for d in drives]
        return f"Shared drives ({len(drives)}):\n" + "\n".join(lines)
    return await asyncio.to_thread(_run)


# ── Dispatcher ───────────────────────────────────────

_ACTIONS = {
    "list": _list,
    "search": _search,
    "get": _get,
    "download": _download,
    "upload": _upload,
    "mkdir": _mkdir,
    "copy": _copy,
    "rename": _rename,
    "move": _move,
    "delete": _delete,
    "share": _share,
    "unshare": _unshare,
    "permissions": _permissions,
    "comments_list": _comments_list,
    "comments_create": _comments_create,
    "comments_get": _comments_get,
    "comments_update": _comments_update,
    "comments_delete": _comments_delete,
    "comments_reply": _comments_reply,
    "drives": _drives,
}


async def _execute(args: dict) -> str:
    action = args.get("action", "")
    fn = _ACTIONS.get(action)
    if not fn:
        return f"Unknown action: {action}. Available: {', '.join(sorted(_ACTIONS))}"
    return await fn(args)


register_tool(
    name="google_drive",
    description=(
        "Manage Google Drive: list/search files, download/upload, create folders, "
        "copy/rename/move/delete files, manage sharing permissions, file comments. "
        "Requires Google authentication."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": list(_ACTIONS.keys()),
                "description": "Drive action to perform",
            },
            "file_id": {"type": "string", "description": "File/folder ID"},
            "file_path": {"type": "string", "description": "Local file path (for upload)"},
            "parent": {"type": "string", "description": "Parent folder ID"},
            "name": {"type": "string", "description": "File/folder name"},
            "query": {"type": "string", "description": "Search query"},
            "format": {"type": "string", "description": "Export format (pdf, docx, xlsx, csv, txt, html)"},
            "max_results": {"type": "integer", "description": "Max results"},
            "email": {"type": "string", "description": "Email for sharing"},
            "role": {"type": "string", "enum": ["reader", "writer", "commenter"], "description": "Sharing role"},
            "type": {"type": "string", "enum": ["user", "group", "domain", "anyone"], "description": "Share type"},
            "permission_id": {"type": "string", "description": "Permission ID (for unshare)"},
            "permanent": {"type": "boolean", "description": "Permanently delete (skip trash)"},
            "content": {"type": "string", "description": "Comment content"},
        },
        "required": ["action"],
    },
    execute=_execute,
)
