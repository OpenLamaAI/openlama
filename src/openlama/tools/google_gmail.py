"""Google Gmail tool — search, read, send, manage emails."""

from __future__ import annotations

import base64
import asyncio
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from openlama.tools.registry import register_tool
from openlama.tools.google_auth import build_service


def _svc():
    return build_service("gmail", "v1")


def _headers_dict(msg: dict) -> dict:
    """Extract headers from a Gmail message payload."""
    return {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}


def _extract_body(payload: dict) -> str:
    """Extract plain text body from message payload."""
    if payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode(errors="replace")
    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode(errors="replace")
    for part in payload.get("parts", []):
        body = _extract_body(part)
        if body:
            return body
    return ""


def _format_message(msg: dict, include_body: bool = False) -> str:
    """Format a Gmail message for display."""
    h = _headers_dict(msg)
    lines = [
        f"ID: {msg['id']}",
        f"Thread: {msg.get('threadId', '')}",
        f"From: {h.get('From', '')}",
        f"To: {h.get('To', '')}",
        f"Subject: {h.get('Subject', '')}",
        f"Date: {h.get('Date', '')}",
        f"Labels: {', '.join(msg.get('labelIds', []))}",
    ]
    if include_body:
        body = _extract_body(msg.get("payload", {}))
        lines.append(f"\n{body[:3000]}")
    return "\n".join(lines)


# ── Actions ──────────────────────────────────────────

async def _search(args: dict) -> str:
    query = args.get("query", "")
    max_results = int(args.get("max_results", 10))
    include_body = args.get("include_body", False)

    def _run():
        svc = _svc()
        resp = svc.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
        msgs = resp.get("messages", [])
        if not msgs:
            return "No messages found."
        results = []
        for m in msgs:
            msg = svc.users().messages().get(userId="me", id=m["id"], format="full").execute()
            results.append(_format_message(msg, include_body))
        return f"Found {len(results)} message(s):\n\n" + "\n---\n".join(results)

    return await asyncio.to_thread(_run)


async def _get(args: dict) -> str:
    message_id = args.get("message_id", "")

    def _run():
        msg = _svc().users().messages().get(userId="me", id=message_id, format="full").execute()
        return _format_message(msg, include_body=True)

    return await asyncio.to_thread(_run)


async def _get_thread(args: dict) -> str:
    thread_id = args.get("thread_id", "")

    def _run():
        thread = _svc().users().threads().get(userId="me", id=thread_id, format="full").execute()
        msgs = thread.get("messages", [])
        results = [_format_message(m, include_body=True) for m in msgs]
        return f"Thread ({len(msgs)} messages):\n\n" + "\n---\n".join(results)

    return await asyncio.to_thread(_run)


async def _send(args: dict) -> str:
    to = args.get("to", "")
    subject = args.get("subject", "")
    body = args.get("body", "")
    cc = args.get("cc", "")
    bcc = args.get("bcc", "")
    html = args.get("html", False)
    reply_to = args.get("reply_to_message_id", "")

    def _run():
        if html:
            msg = MIMEMultipart("alternative")
            msg.attach(MIMEText(body, "html"))
        else:
            msg = MIMEText(body)
        msg["to"] = to
        msg["subject"] = subject
        if cc:
            msg["cc"] = cc
        if bcc:
            msg["bcc"] = bcc

        send_body = {"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()}
        if reply_to:
            send_body["threadId"] = _svc().users().messages().get(
                userId="me", id=reply_to, format="minimal"
            ).execute().get("threadId", "")

        result = _svc().users().messages().send(userId="me", body=send_body).execute()
        return f"Email sent. Message ID: {result['id']}"

    return await asyncio.to_thread(_run)


async def _reply(args: dict) -> str:
    message_id = args.get("message_id", "")
    body = args.get("body", "")
    quote = args.get("quote", True)

    def _run():
        svc = _svc()
        orig = svc.users().messages().get(userId="me", id=message_id, format="full").execute()
        h = _headers_dict(orig)
        to = h.get("Reply-To", h.get("From", ""))
        subject = h.get("Subject", "")
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"
        thread_id = orig.get("threadId", "")

        text = body
        if quote:
            orig_body = _extract_body(orig.get("payload", {}))
            if orig_body:
                quoted = "\n".join(f"> {line}" for line in orig_body[:1000].split("\n"))
                text = f"{body}\n\n{quoted}"

        msg = MIMEText(text)
        msg["to"] = to
        msg["subject"] = subject
        msg["In-Reply-To"] = message_id
        msg["References"] = message_id

        send_body = {
            "raw": base64.urlsafe_b64encode(msg.as_bytes()).decode(),
            "threadId": thread_id,
        }
        result = svc.users().messages().send(userId="me", body=send_body).execute()
        return f"Reply sent. Message ID: {result['id']}"

    return await asyncio.to_thread(_run)


async def _archive(args: dict) -> str:
    message_ids = args.get("message_ids", [])
    query = args.get("query", "")

    def _run():
        svc = _svc()
        ids = list(message_ids) if message_ids else []
        if query:
            resp = svc.users().messages().list(userId="me", q=query, maxResults=int(args.get("max_results", 50))).execute()
            ids.extend(m["id"] for m in resp.get("messages", []))
        count = 0
        for mid in ids:
            svc.users().messages().modify(userId="me", id=mid, body={"removeLabelIds": ["INBOX"]}).execute()
            count += 1
        return f"Archived {count} message(s)."

    return await asyncio.to_thread(_run)


async def _mark_read(args: dict) -> str:
    message_ids = args.get("message_ids", [])

    def _run():
        svc = _svc()
        for mid in message_ids:
            svc.users().messages().modify(userId="me", id=mid, body={"removeLabelIds": ["UNREAD"]}).execute()
        return f"Marked {len(message_ids)} message(s) as read."

    return await asyncio.to_thread(_run)


async def _mark_unread(args: dict) -> str:
    message_ids = args.get("message_ids", [])

    def _run():
        svc = _svc()
        for mid in message_ids:
            svc.users().messages().modify(userId="me", id=mid, body={"addLabelIds": ["UNREAD"]}).execute()
        return f"Marked {len(message_ids)} message(s) as unread."

    return await asyncio.to_thread(_run)


async def _trash(args: dict) -> str:
    message_ids = args.get("message_ids", [])

    def _run():
        svc = _svc()
        for mid in message_ids:
            svc.users().messages().trash(userId="me", id=mid).execute()
        return f"Trashed {len(message_ids)} message(s)."

    return await asyncio.to_thread(_run)


async def _labels_list(args: dict) -> str:
    def _run():
        labels = _svc().users().labels().list(userId="me").execute().get("labels", [])
        lines = [f"  {l['id']:30s} {l['name']}" for l in sorted(labels, key=lambda x: x["name"])]
        return f"Labels ({len(labels)}):\n" + "\n".join(lines)
    return await asyncio.to_thread(_run)


async def _labels_create(args: dict) -> str:
    name = args.get("name", "")

    def _run():
        label = _svc().users().labels().create(userId="me", body={"name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"}).execute()
        return f"Label created: {label['name']} (ID: {label['id']})"
    return await asyncio.to_thread(_run)


async def _labels_modify(args: dict) -> str:
    message_ids = args.get("message_ids", [])
    add = args.get("add_labels", [])
    remove = args.get("remove_labels", [])

    def _run():
        svc = _svc()
        body = {}
        if add:
            body["addLabelIds"] = add
        if remove:
            body["removeLabelIds"] = remove
        for mid in message_ids:
            svc.users().messages().modify(userId="me", id=mid, body=body).execute()
        return f"Modified labels on {len(message_ids)} message(s)."
    return await asyncio.to_thread(_run)


async def _labels_delete(args: dict) -> str:
    label_id = args.get("label_id", "")

    def _run():
        _svc().users().labels().delete(userId="me", id=label_id).execute()
        return f"Label deleted: {label_id}"
    return await asyncio.to_thread(_run)


async def _drafts_list(args: dict) -> str:
    def _run():
        drafts = _svc().users().drafts().list(userId="me").execute().get("drafts", [])
        if not drafts:
            return "No drafts."
        lines = []
        svc = _svc()
        for d in drafts[:20]:
            msg = svc.users().drafts().get(userId="me", id=d["id"], format="metadata").execute()
            h = _headers_dict(msg.get("message", {}))
            lines.append(f"  {d['id']}  To: {h.get('To', '?')}  Subject: {h.get('Subject', '?')}")
        return f"Drafts ({len(drafts)}):\n" + "\n".join(lines)
    return await asyncio.to_thread(_run)


async def _drafts_create(args: dict) -> str:
    to = args.get("to", "")
    subject = args.get("subject", "")
    body = args.get("body", "")

    def _run():
        msg = MIMEText(body)
        msg["to"] = to
        msg["subject"] = subject
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        draft = _svc().users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
        return f"Draft created. ID: {draft['id']}"
    return await asyncio.to_thread(_run)


async def _drafts_send(args: dict) -> str:
    draft_id = args.get("draft_id", "")

    def _run():
        result = _svc().users().drafts().send(userId="me", body={"id": draft_id}).execute()
        return f"Draft sent. Message ID: {result['id']}"
    return await asyncio.to_thread(_run)


async def _filters_list(args: dict) -> str:
    def _run():
        filters = _svc().users().settings().filters().list(userId="me").execute().get("filter", [])
        if not filters:
            return "No filters."
        lines = []
        for f in filters:
            criteria = f.get("criteria", {})
            action = f.get("action", {})
            lines.append(f"  {f['id']}  From: {criteria.get('from', '*')}  → Labels: {action.get('addLabelIds', [])}")
        return f"Filters ({len(filters)}):\n" + "\n".join(lines)
    return await asyncio.to_thread(_run)


async def _filters_create(args: dict) -> str:
    from_addr = args.get("from", "")
    add_label = args.get("add_label", "")

    def _run():
        body = {"criteria": {}, "action": {}}
        if from_addr:
            body["criteria"]["from"] = from_addr
        if add_label:
            body["action"]["addLabelIds"] = [add_label]
        f = _svc().users().settings().filters().create(userId="me", body=body).execute()
        return f"Filter created. ID: {f['id']}"
    return await asyncio.to_thread(_run)


async def _filters_delete(args: dict) -> str:
    filter_id = args.get("filter_id", "")

    def _run():
        _svc().users().settings().filters().delete(userId="me", id=filter_id).execute()
        return f"Filter deleted: {filter_id}"
    return await asyncio.to_thread(_run)


async def _vacation_get(args: dict) -> str:
    def _run():
        v = _svc().users().settings().getVacation(userId="me").execute()
        status = "enabled" if v.get("enableAutoReply") else "disabled"
        subject = v.get("responseSubject", "")
        return f"Vacation auto-reply: {status}\nSubject: {subject}"
    return await asyncio.to_thread(_run)


async def _vacation_enable(args: dict) -> str:
    subject = args.get("subject", "Out of Office")
    message = args.get("message", "")

    def _run():
        body = {"enableAutoReply": True, "responseSubject": subject, "responseBodyHtml": message}
        _svc().users().settings().updateVacation(userId="me", body=body).execute()
        return f"Vacation auto-reply enabled. Subject: {subject}"
    return await asyncio.to_thread(_run)


async def _vacation_disable(args: dict) -> str:
    def _run():
        _svc().users().settings().updateVacation(userId="me", body={"enableAutoReply": False}).execute()
        return "Vacation auto-reply disabled."
    return await asyncio.to_thread(_run)


async def _forwarding_list(args: dict) -> str:
    def _run():
        fwd = _svc().users().settings().forwardingAddresses().list(userId="me").execute()
        addrs = fwd.get("forwardingAddresses", [])
        if not addrs:
            return "No forwarding addresses."
        lines = [f"  {a['forwardingEmail']} ({a.get('verificationStatus', '?')})" for a in addrs]
        return "Forwarding addresses:\n" + "\n".join(lines)
    return await asyncio.to_thread(_run)


async def _sendas_list(args: dict) -> str:
    def _run():
        aliases = _svc().users().settings().sendAs().list(userId="me").execute().get("sendAs", [])
        lines = [f"  {a.get('sendAsEmail', '?')} — {a.get('displayName', '')} {'(default)' if a.get('isDefault') else ''}" for a in aliases]
        return "Send-as addresses:\n" + "\n".join(lines)
    return await asyncio.to_thread(_run)


async def _delegates_list(args: dict) -> str:
    def _run():
        delegates = _svc().users().settings().delegates().list(userId="me").execute().get("delegates", [])
        if not delegates:
            return "No delegates."
        lines = [f"  {d.get('delegateEmail', '?')} ({d.get('verificationStatus', '?')})" for d in delegates]
        return "Delegates:\n" + "\n".join(lines)
    return await asyncio.to_thread(_run)


async def _attachment(args: dict) -> str:
    message_id = args.get("message_id", "")
    attachment_id = args.get("attachment_id", "")
    filename = args.get("filename", "attachment")

    def _run():
        att = _svc().users().messages().attachments().get(userId="me", messageId=message_id, id=attachment_id).execute()
        data = base64.urlsafe_b64decode(att["data"])
        from openlama.config import DATA_DIR
        from pathlib import Path
        out_dir = DATA_DIR / "tmp_uploads"
        out_dir.mkdir(parents=True, exist_ok=True)
        # Sanitize filename — strip path components
        safe_name = Path(filename).name.replace("..", "_").replace("/", "_").replace("\\", "_") or "attachment"
        out_path = out_dir / safe_name
        out_path.write_bytes(data)
        return f"Attachment saved: {out_path} ({len(data)} bytes)"
    return await asyncio.to_thread(_run)


async def _labels_get(args: dict) -> str:
    label_id = args.get("label_id", "")

    def _run():
        label = _svc().users().labels().get(userId="me", id=label_id).execute()
        return (
            f"ID: {label['id']}\n"
            f"Name: {label.get('name', '')}\n"
            f"Type: {label.get('type', '')}\n"
            f"Messages total: {label.get('messagesTotal', 0)}\n"
            f"Messages unread: {label.get('messagesUnread', 0)}\n"
            f"Threads total: {label.get('threadsTotal', 0)}"
        )
    return await asyncio.to_thread(_run)


async def _labels_rename(args: dict) -> str:
    label_id = args.get("label_id", "")
    name = args.get("name", "")

    def _run():
        label = _svc().users().labels().update(userId="me", id=label_id, body={"name": name}).execute()
        return f"Label renamed to: {label['name']}"
    return await asyncio.to_thread(_run)


async def _batch_delete(args: dict) -> str:
    message_ids = args.get("message_ids", [])

    def _run():
        _svc().users().messages().batchDelete(userId="me", body={"ids": message_ids}).execute()
        return f"Permanently deleted {len(message_ids)} message(s)."
    return await asyncio.to_thread(_run)


async def _autoforward_get(args: dict) -> str:
    def _run():
        fwd = _svc().users().settings().getAutoForwarding(userId="me").execute()
        enabled = fwd.get("enabled", False)
        email = fwd.get("emailAddress", "")
        disposition = fwd.get("disposition", "")
        return f"Auto-forwarding: {'enabled' if enabled else 'disabled'}\nTo: {email}\nDisposition: {disposition}"
    return await asyncio.to_thread(_run)


async def _autoforward_enable(args: dict) -> str:
    email = args.get("email", "")
    disposition = args.get("disposition", "leaveInInbox")

    def _run():
        _svc().users().settings().updateAutoForwarding(userId="me", body={
            "enabled": True, "emailAddress": email, "disposition": disposition,
        }).execute()
        return f"Auto-forwarding enabled to {email}"
    return await asyncio.to_thread(_run)


async def _autoforward_disable(args: dict) -> str:
    def _run():
        _svc().users().settings().updateAutoForwarding(userId="me", body={"enabled": False}).execute()
        return "Auto-forwarding disabled."
    return await asyncio.to_thread(_run)


async def _sendas_create(args: dict) -> str:
    email = args.get("email", "")
    display_name = args.get("display_name", "")

    def _run():
        body = {"sendAsEmail": email}
        if display_name:
            body["displayName"] = display_name
        alias = _svc().users().settings().sendAs().create(userId="me", body=body).execute()
        return f"Send-as created: {alias.get('sendAsEmail', '')} ({alias.get('verificationStatus', '?')})"
    return await asyncio.to_thread(_run)


async def _delegates_add(args: dict) -> str:
    email = args.get("email", "")

    def _run():
        _svc().users().settings().delegates().create(userId="me", body={"delegateEmail": email}).execute()
        return f"Delegate added: {email}"
    return await asyncio.to_thread(_run)


async def _delegates_remove(args: dict) -> str:
    email = args.get("email", "")

    def _run():
        _svc().users().settings().delegates().delete(userId="me", delegateEmail=email).execute()
        return f"Delegate removed: {email}"
    return await asyncio.to_thread(_run)


async def _url(args: dict) -> str:
    thread_id = args.get("thread_id", "")

    def _run():
        return f"https://mail.google.com/mail/u/0/#inbox/{thread_id}"
    return await asyncio.to_thread(_run)


async def _batch_modify(args: dict) -> str:
    message_ids = args.get("message_ids", [])
    add = args.get("add_labels", [])
    remove = args.get("remove_labels", [])

    def _run():
        body = {"ids": message_ids}
        if add:
            body["addLabelIds"] = add
        if remove:
            body["removeLabelIds"] = remove
        _svc().users().messages().batchModify(userId="me", body=body).execute()
        return f"Batch modified {len(message_ids)} message(s)."
    return await asyncio.to_thread(_run)


# ── Dispatcher ───────────────────────────────────────

_ACTIONS = {
    "search": _search,
    "get": _get,
    "get_thread": _get_thread,
    "send": _send,
    "reply": _reply,
    "archive": _archive,
    "mark_read": _mark_read,
    "mark_unread": _mark_unread,
    "trash": _trash,
    "labels_list": _labels_list,
    "labels_get": _labels_get,
    "labels_create": _labels_create,
    "labels_rename": _labels_rename,
    "labels_modify": _labels_modify,
    "labels_delete": _labels_delete,
    "drafts_list": _drafts_list,
    "drafts_create": _drafts_create,
    "drafts_send": _drafts_send,
    "filters_list": _filters_list,
    "filters_create": _filters_create,
    "filters_delete": _filters_delete,
    "vacation_get": _vacation_get,
    "vacation_enable": _vacation_enable,
    "vacation_disable": _vacation_disable,
    "forwarding_list": _forwarding_list,
    "sendas_list": _sendas_list,
    "delegates_list": _delegates_list,
    "attachment": _attachment,
    "batch_modify": _batch_modify,
    "batch_delete": _batch_delete,
    "autoforward_get": _autoforward_get,
    "autoforward_enable": _autoforward_enable,
    "autoforward_disable": _autoforward_disable,
    "sendas_create": _sendas_create,
    "delegates_add": _delegates_add,
    "delegates_remove": _delegates_remove,
    "url": _url,
}


async def _execute(args: dict) -> str:
    action = args.get("action", "")
    fn = _ACTIONS.get(action)
    if not fn:
        return f"Unknown action: {action}. Available: {', '.join(sorted(_ACTIONS))}"
    return await fn(args)


register_tool(
    name="google_gmail",
    description=(
        "Manage Gmail: search emails, read messages/threads, send/reply, "
        "archive, mark read/unread, trash, manage labels/drafts/filters, "
        "vacation auto-reply, forwarding, send-as aliases, delegates, attachments. "
        "Requires Google authentication (google_auth tool)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": list(_ACTIONS.keys()),
                "description": "Gmail action to perform",
            },
            "query": {"type": "string", "description": "Gmail search query (for search/archive)"},
            "message_id": {"type": "string", "description": "Message ID"},
            "thread_id": {"type": "string", "description": "Thread ID"},
            "message_ids": {"type": "array", "items": {"type": "string"}, "description": "List of message IDs"},
            "to": {"type": "string", "description": "Recipient email"},
            "cc": {"type": "string", "description": "CC recipients"},
            "bcc": {"type": "string", "description": "BCC recipients"},
            "subject": {"type": "string", "description": "Email subject"},
            "body": {"type": "string", "description": "Email body text"},
            "html": {"type": "boolean", "description": "Send as HTML"},
            "reply_to_message_id": {"type": "string", "description": "Message ID to reply to"},
            "quote": {"type": "boolean", "description": "Include original message in reply"},
            "max_results": {"type": "integer", "description": "Max results to return"},
            "include_body": {"type": "boolean", "description": "Include message body in search results"},
            "name": {"type": "string", "description": "Label name"},
            "label_id": {"type": "string", "description": "Label ID"},
            "add_labels": {"type": "array", "items": {"type": "string"}, "description": "Label IDs to add"},
            "remove_labels": {"type": "array", "items": {"type": "string"}, "description": "Label IDs to remove"},
            "draft_id": {"type": "string", "description": "Draft ID"},
            "filter_id": {"type": "string", "description": "Filter ID"},
            "from": {"type": "string", "description": "From address (for filter)"},
            "add_label": {"type": "string", "description": "Label to add (for filter)"},
            "message": {"type": "string", "description": "Vacation message body"},
            "attachment_id": {"type": "string", "description": "Attachment ID"},
            "filename": {"type": "string", "description": "Filename for attachment download"},
        },
        "required": ["action"],
    },
    execute=_execute,
)
