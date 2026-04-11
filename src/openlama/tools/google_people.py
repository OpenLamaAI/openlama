"""Google People tool — user profile and directory search."""

from __future__ import annotations

import asyncio

from openlama.tools.registry import register_tool
from openlama.tools.google_auth import build_service


def _svc():
    return build_service("people", "v1")


_PERSON_FIELDS = "names,emailAddresses,phoneNumbers,addresses,organizations,birthdays,biographies,relations,photos"


def _format_person(p: dict) -> str:
    names = p.get("names", [])
    name = names[0].get("displayName", "") if names else ""
    emails = [e.get("value", "") for e in p.get("emailAddresses", [])]
    phones = [ph.get("value", "") for ph in p.get("phoneNumbers", [])]
    orgs = [o.get("name", "") for o in p.get("organizations", [])]
    photos = [ph.get("url", "") for ph in p.get("photos", []) if ph.get("url")]
    lines = [f"Resource: {p.get('resourceName', '')}", f"Name: {name}"]
    if emails:
        lines.append(f"Email: {', '.join(emails)}")
    if phones:
        lines.append(f"Phone: {', '.join(phones)}")
    if orgs:
        lines.append(f"Organization: {', '.join(orgs)}")
    if photos:
        lines.append(f"Photo: {photos[0]}")
    return "\n".join(lines)


async def _me(args: dict) -> str:
    def _run():
        p = _svc().people().get(resourceName="people/me", personFields=_PERSON_FIELDS).execute()
        return f"Current user:\n{_format_person(p)}"
    return await asyncio.to_thread(_run)


async def _get(args: dict) -> str:
    resource_name = args.get("resource_name", "")

    def _run():
        p = _svc().people().get(resourceName=resource_name, personFields=_PERSON_FIELDS).execute()
        return _format_person(p)
    return await asyncio.to_thread(_run)


async def _search(args: dict) -> str:
    query = args.get("query", "")
    max_results = int(args.get("max_results", 10))

    def _run():
        result = _svc().people().searchDirectoryPeople(
            query=query,
            pageSize=max_results,
            readMask=_PERSON_FIELDS,
            sources=["DIRECTORY_SOURCE_TYPE_DOMAIN_PROFILE"],
        ).execute()
        people = result.get("people", [])
        if not people:
            return f"No people matching '{query}'."
        return f"Search results ({len(people)}):\n\n" + "\n---\n".join(_format_person(p) for p in people)
    return await asyncio.to_thread(_run)


async def _relations(args: dict) -> str:
    resource_name = args.get("resource_name", "people/me")

    def _run():
        p = _svc().people().get(resourceName=resource_name, personFields="relations").execute()
        rels = p.get("relations", [])
        if not rels:
            return "No relations found."
        lines = [f"  {r.get('type', '?')}: {r.get('person', '')}" for r in rels]
        return f"Relations ({len(rels)}):\n" + "\n".join(lines)
    return await asyncio.to_thread(_run)


_ACTIONS = {
    "me": _me,
    "get": _get,
    "search": _search,
    "relations": _relations,
}


async def _execute(args: dict) -> str:
    action = args.get("action", "")
    fn = _ACTIONS.get(action)
    if not fn:
        return f"Unknown action: {action}. Available: {', '.join(sorted(_ACTIONS))}"
    return await fn(args)


register_tool(
    name="google_people",
    description=(
        "Google People: view your profile (me), look up people, "
        "search directory, view relations. Requires Google authentication."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(_ACTIONS.keys()), "description": "People action"},
            "resource_name": {"type": "string", "description": "Person resource (e.g. people/me, people/c123)"},
            "query": {"type": "string", "description": "Search query"},
            "max_results": {"type": "integer", "description": "Max results"},
        },
        "required": ["action"],
    },
    execute=_execute,
)
