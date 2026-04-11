"""Google Calendar tool — manage calendars, events, scheduling."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta

from openlama.tools.registry import register_tool
from openlama.tools.google_auth import build_service


def _svc():
    return build_service("calendar", "v3")


def _format_event(e: dict) -> str:
    start = e.get("start", {}).get("dateTime", e.get("start", {}).get("date", ""))
    end = e.get("end", {}).get("dateTime", e.get("end", {}).get("date", ""))
    attendees = ", ".join(a.get("email", "") for a in e.get("attendees", [])[:5])
    status = e.get("status", "")
    lines = [
        f"ID: {e.get('id', '')}",
        f"Summary: {e.get('summary', '(no title)')}",
        f"Start: {start}",
        f"End: {end}",
        f"Location: {e.get('location', '')}",
        f"Status: {status}",
    ]
    if attendees:
        lines.append(f"Attendees: {attendees}")
    if e.get("description"):
        lines.append(f"Description: {e['description'][:500]}")
    if e.get("htmlLink"):
        lines.append(f"Link: {e['htmlLink']}")
    return "\n".join(lines)


async def _calendars(args: dict) -> str:
    def _run():
        cals = _svc().calendarList().list().execute().get("items", [])
        lines = [f"  {c['id']:40s} {c.get('summary', '?')} {'(primary)' if c.get('primary') else ''}" for c in cals]
        return f"Calendars ({len(cals)}):\n" + "\n".join(lines)
    return await asyncio.to_thread(_run)


async def _events(args: dict) -> str:
    calendar_id = args.get("calendar_id", "primary")
    days = int(args.get("days", 7))
    max_results = int(args.get("max_results", 20))

    def _run():
        now = datetime.now(timezone.utc)
        time_min = now.isoformat()
        time_max = (now + timedelta(days=days)).isoformat()
        events = _svc().events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        ).execute().get("items", [])
        if not events:
            return f"No events in the next {days} day(s)."
        return f"Events ({len(events)}):\n\n" + "\n---\n".join(_format_event(e) for e in events)
    return await asyncio.to_thread(_run)


async def _event_get(args: dict) -> str:
    calendar_id = args.get("calendar_id", "primary")
    event_id = args.get("event_id", "")

    def _run():
        e = _svc().events().get(calendarId=calendar_id, eventId=event_id).execute()
        return _format_event(e)
    return await asyncio.to_thread(_run)


async def _search(args: dict) -> str:
    query = args.get("query", "")
    calendar_id = args.get("calendar_id", "primary")
    max_results = int(args.get("max_results", 10))

    def _run():
        events = _svc().events().list(
            calendarId=calendar_id,
            q=query,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
            timeMin=datetime.now(timezone.utc).isoformat(),
        ).execute().get("items", [])
        if not events:
            return f"No events matching '{query}'."
        return f"Search results ({len(events)}):\n\n" + "\n---\n".join(_format_event(e) for e in events)
    return await asyncio.to_thread(_run)


async def _create(args: dict) -> str:
    calendar_id = args.get("calendar_id", "primary")
    summary = args.get("summary", "")
    start = args.get("start", "")
    end = args.get("end", "")
    location = args.get("location", "")
    description = args.get("description", "")
    attendees = args.get("attendees", [])
    all_day = args.get("all_day", False)
    timezone_str = args.get("timezone", "")

    def _run():
        body = {"summary": summary}
        if all_day:
            body["start"] = {"date": start}
            body["end"] = {"date": end or start}
        else:
            start_obj = {"dateTime": start}
            end_obj = {"dateTime": end}
            if timezone_str:
                start_obj["timeZone"] = timezone_str
                end_obj["timeZone"] = timezone_str
            body["start"] = start_obj
            body["end"] = end_obj
        if location:
            body["location"] = location
        if description:
            body["description"] = description
        if attendees:
            body["attendees"] = [{"email": a} for a in attendees]

        e = _svc().events().insert(calendarId=calendar_id, body=body, sendUpdates="all").execute()
        return f"Event created:\n{_format_event(e)}"
    return await asyncio.to_thread(_run)


async def _update(args: dict) -> str:
    calendar_id = args.get("calendar_id", "primary")
    event_id = args.get("event_id", "")
    updates = {}
    for key in ("summary", "location", "description", "start", "end"):
        if args.get(key):
            if key in ("start", "end"):
                updates[key] = {"dateTime": args[key]}
            else:
                updates[key] = args[key]
    if args.get("add_attendees"):
        updates["attendees"] = [{"email": a} for a in args["add_attendees"]]

    def _run():
        svc = _svc()
        event = svc.events().get(calendarId=calendar_id, eventId=event_id).execute()
        event.update(updates)
        if "add_attendees" in updates:
            existing = event.get("attendees", [])
            existing.extend(updates["attendees"])
            event["attendees"] = existing
        e = svc.events().update(calendarId=calendar_id, eventId=event_id, body=event, sendUpdates="all").execute()
        return f"Event updated:\n{_format_event(e)}"
    return await asyncio.to_thread(_run)


async def _delete(args: dict) -> str:
    calendar_id = args.get("calendar_id", "primary")
    event_id = args.get("event_id", "")

    def _run():
        _svc().events().delete(calendarId=calendar_id, eventId=event_id, sendUpdates="all").execute()
        return f"Event deleted: {event_id}"
    return await asyncio.to_thread(_run)


async def _respond(args: dict) -> str:
    calendar_id = args.get("calendar_id", "primary")
    event_id = args.get("event_id", "")
    response = args.get("response", "accepted")

    def _run():
        svc = _svc()
        event = svc.events().get(calendarId=calendar_id, eventId=event_id).execute()
        # Find self in attendees
        for att in event.get("attendees", []):
            if att.get("self"):
                att["responseStatus"] = response
                break
        e = svc.events().update(calendarId=calendar_id, eventId=event_id, body=event, sendUpdates="all").execute()
        return f"Responded '{response}' to: {e.get('summary', '')}"
    return await asyncio.to_thread(_run)


async def _freebusy(args: dict) -> str:
    calendar_ids = args.get("calendar_ids", ["primary"])
    days = int(args.get("days", 1))

    def _run():
        now = datetime.now(timezone.utc)
        body = {
            "timeMin": now.isoformat(),
            "timeMax": (now + timedelta(days=days)).isoformat(),
            "items": [{"id": c} for c in calendar_ids],
        }
        result = _svc().freebusy().query(body=body).execute()
        lines = []
        for cal_id, data in result.get("calendars", {}).items():
            busy = data.get("busy", [])
            lines.append(f"{cal_id}: {len(busy)} busy slot(s)")
            for b in busy:
                lines.append(f"  {b['start']} → {b['end']}")
        return "Free/Busy:\n" + "\n".join(lines) if lines else "No busy slots."
    return await asyncio.to_thread(_run)


async def _conflicts(args: dict) -> str:
    calendar_id = args.get("calendar_id", "primary")
    days = int(args.get("days", 7))

    def _run():
        now = datetime.now(timezone.utc)
        events = _svc().events().list(
            calendarId=calendar_id,
            timeMin=now.isoformat(),
            timeMax=(now + timedelta(days=days)).isoformat(),
            singleEvents=True,
            orderBy="startTime",
        ).execute().get("items", [])

        conflicts = []
        for i, e1 in enumerate(events):
            for e2 in events[i + 1:]:
                s1 = e1.get("start", {}).get("dateTime", "")
                e1_end = e1.get("end", {}).get("dateTime", "")
                s2 = e2.get("start", {}).get("dateTime", "")
                if s1 and e1_end and s2 and s2 < e1_end:
                    conflicts.append(f"  '{e1.get('summary', '?')}' overlaps '{e2.get('summary', '?')}'")
        if not conflicts:
            return f"No scheduling conflicts in the next {days} day(s)."
        return f"Conflicts ({len(conflicts)}):\n" + "\n".join(conflicts)
    return await asyncio.to_thread(_run)


async def _colors(args: dict) -> str:
    def _run():
        colors = _svc().colors().get().execute()
        lines = ["Event colors:"]
        for cid, c in colors.get("event", {}).items():
            lines.append(f"  {cid}: bg={c.get('background', '')} fg={c.get('foreground', '')}")
        return "\n".join(lines)
    return await asyncio.to_thread(_run)


async def _focus_time(args: dict) -> str:
    calendar_id = args.get("calendar_id", "primary")
    start = args.get("start", "")
    end = args.get("end", "")

    def _run():
        body = {
            "summary": "Focus Time",
            "eventType": "focusTime",
            "start": {"dateTime": start},
            "end": {"dateTime": end},
            "transparency": "opaque",
        }
        e = _svc().events().insert(calendarId=calendar_id, body=body).execute()
        return f"Focus time created:\n{_format_event(e)}"
    return await asyncio.to_thread(_run)


async def _out_of_office(args: dict) -> str:
    calendar_id = args.get("calendar_id", "primary")
    start = args.get("start", "")
    end = args.get("end", "")
    all_day = args.get("all_day", False)

    def _run():
        body = {
            "summary": "Out of office",
            "eventType": "outOfOffice",
            "transparency": "opaque",
        }
        if all_day:
            body["start"] = {"date": start}
            body["end"] = {"date": end or start}
        else:
            body["start"] = {"dateTime": start}
            body["end"] = {"dateTime": end}
        e = _svc().events().insert(calendarId=calendar_id, body=body).execute()
        return f"Out of office created:\n{_format_event(e)}"
    return await asyncio.to_thread(_run)


async def _working_location(args: dict) -> str:
    calendar_id = args.get("calendar_id", "primary")
    start = args.get("start", "")
    end = args.get("end", "")
    location_type = args.get("location_type", "officeLocation")
    office_label = args.get("office_label", "")

    def _run():
        body = {
            "summary": office_label or "Working Location",
            "eventType": "workingLocation",
            "start": {"date": start},
            "end": {"date": end or start},
            "workingLocationProperties": {"type": location_type},
        }
        if location_type == "officeLocation" and office_label:
            body["workingLocationProperties"]["officeLocation"] = {"label": office_label}
        e = _svc().events().insert(calendarId=calendar_id, body=body).execute()
        return f"Working location set:\n{_format_event(e)}"
    return await asyncio.to_thread(_run)


async def _acl(args: dict) -> str:
    calendar_id = args.get("calendar_id", "primary")

    def _run():
        rules = _svc().acl().list(calendarId=calendar_id).execute().get("items", [])
        if not rules:
            return "No ACL rules."
        lines = [f"  {r.get('id', '?'):40s} role={r.get('role', '?')} scope={r.get('scope', {}).get('type', '?')}:{r.get('scope', {}).get('value', '')}" for r in rules]
        return f"ACL rules ({len(rules)}):\n" + "\n".join(lines)
    return await asyncio.to_thread(_run)


# ── Dispatcher ───────────────────────────────────────

_ACTIONS = {
    "calendars": _calendars,
    "events": _events,
    "event_get": _event_get,
    "search": _search,
    "create": _create,
    "update": _update,
    "delete": _delete,
    "respond": _respond,
    "freebusy": _freebusy,
    "conflicts": _conflicts,
    "colors": _colors,
    "focus_time": _focus_time,
    "out_of_office": _out_of_office,
    "working_location": _working_location,
    "acl": _acl,
}


async def _execute(args: dict) -> str:
    action = args.get("action", "")
    fn = _ACTIONS.get(action)
    if not fn:
        return f"Unknown action: {action}. Available: {', '.join(sorted(_ACTIONS))}"
    return await fn(args)


register_tool(
    name="google_calendar",
    description=(
        "Manage Google Calendar: list calendars, view/search events, "
        "create/update/delete events, respond to invitations, check free/busy times, "
        "detect conflicts. Requires Google authentication."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": list(_ACTIONS.keys()),
                "description": "Calendar action to perform",
            },
            "calendar_id": {"type": "string", "description": "Calendar ID (default: primary)"},
            "calendar_ids": {"type": "array", "items": {"type": "string"}, "description": "Calendar IDs for freebusy"},
            "event_id": {"type": "string", "description": "Event ID"},
            "query": {"type": "string", "description": "Search query"},
            "summary": {"type": "string", "description": "Event title"},
            "start": {"type": "string", "description": "Start time (ISO 8601 or YYYY-MM-DD)"},
            "end": {"type": "string", "description": "End time (ISO 8601 or YYYY-MM-DD)"},
            "location": {"type": "string", "description": "Event location"},
            "description": {"type": "string", "description": "Event description"},
            "attendees": {"type": "array", "items": {"type": "string"}, "description": "Attendee emails"},
            "add_attendees": {"type": "array", "items": {"type": "string"}, "description": "Attendees to add"},
            "all_day": {"type": "boolean", "description": "All-day event"},
            "timezone": {"type": "string", "description": "Timezone (e.g. Asia/Seoul)"},
            "days": {"type": "integer", "description": "Number of days to look ahead"},
            "max_results": {"type": "integer", "description": "Max results"},
            "response": {"type": "string", "enum": ["accepted", "declined", "tentative"], "description": "RSVP response"},
        },
        "required": ["action"],
    },
    execute=_execute,
)
