"""Google Contacts tool — manage contacts via People API."""

from __future__ import annotations

import asyncio

from openlama.tools.registry import register_tool
from openlama.tools.google_auth import build_service


def _svc():
    return build_service("people", "v1")


_PERSON_FIELDS = "names,emailAddresses,phoneNumbers,addresses,organizations,birthdays,biographies,relations"


def _format_contact(p: dict) -> str:
    name = ""
    names = p.get("names", [])
    if names:
        name = names[0].get("displayName", "")
    emails = [e.get("value", "") for e in p.get("emailAddresses", [])]
    phones = [ph.get("value", "") for ph in p.get("phoneNumbers", [])]
    orgs = [o.get("name", "") for o in p.get("organizations", [])]
    resource = p.get("resourceName", "")
    lines = [f"Resource: {resource}", f"Name: {name}"]
    if emails:
        lines.append(f"Email: {', '.join(emails)}")
    if phones:
        lines.append(f"Phone: {', '.join(phones)}")
    if orgs:
        lines.append(f"Org: {', '.join(orgs)}")
    return "\n".join(lines)


async def _list(args: dict) -> str:
    max_results = int(args.get("max_results", 20))

    def _run():
        result = _svc().people().connections().list(
            resourceName="people/me",
            pageSize=max_results,
            personFields=_PERSON_FIELDS,
        ).execute()
        contacts = result.get("connections", [])
        if not contacts:
            return "No contacts found."
        return f"Contacts ({len(contacts)}):\n\n" + "\n---\n".join(_format_contact(c) for c in contacts)
    return await asyncio.to_thread(_run)


async def _search(args: dict) -> str:
    query = args.get("query", "")
    max_results = int(args.get("max_results", 10))

    def _run():
        result = _svc().people().searchContacts(
            query=query,
            pageSize=max_results,
            readMask=_PERSON_FIELDS,
        ).execute()
        contacts = [r.get("person", {}) for r in result.get("results", [])]
        if not contacts:
            return f"No contacts matching '{query}'."
        return f"Search results ({len(contacts)}):\n\n" + "\n---\n".join(_format_contact(c) for c in contacts)
    return await asyncio.to_thread(_run)


async def _get(args: dict) -> str:
    resource_name = args.get("resource_name", "")

    def _run():
        p = _svc().people().get(resourceName=resource_name, personFields=_PERSON_FIELDS).execute()
        return _format_contact(p)
    return await asyncio.to_thread(_run)


async def _create(args: dict) -> str:
    given_name = args.get("given_name", "")
    family_name = args.get("family_name", "")
    email = args.get("email", "")
    phone = args.get("phone", "")

    def _run():
        body = {"names": [{"givenName": given_name, "familyName": family_name}]}
        if email:
            body["emailAddresses"] = [{"value": email}]
        if phone:
            body["phoneNumbers"] = [{"value": phone}]
        p = _svc().people().createContact(body=body).execute()
        return f"Contact created: {given_name} {family_name}\nResource: {p.get('resourceName', '')}"
    return await asyncio.to_thread(_run)


async def _update(args: dict) -> str:
    resource_name = args.get("resource_name", "")
    given_name = args.get("given_name", "")
    family_name = args.get("family_name", "")
    email = args.get("email", "")
    phone = args.get("phone", "")

    def _run():
        svc = _svc()
        p = svc.people().get(resourceName=resource_name, personFields=_PERSON_FIELDS).execute()
        etag = p.get("etag", "")
        update_fields = []
        if given_name or family_name:
            p["names"] = [{"givenName": given_name or p.get("names", [{}])[0].get("givenName", ""),
                           "familyName": family_name or p.get("names", [{}])[0].get("familyName", "")}]
            update_fields.append("names")
        if email:
            p["emailAddresses"] = [{"value": email}]
            update_fields.append("emailAddresses")
        if phone:
            p["phoneNumbers"] = [{"value": phone}]
            update_fields.append("phoneNumbers")
        if not update_fields:
            return "No fields to update."
        p["etag"] = etag
        updated = svc.people().updateContact(
            resourceName=resource_name,
            body=p,
            updatePersonFields=",".join(update_fields),
        ).execute()
        return f"Contact updated: {resource_name}"
    return await asyncio.to_thread(_run)


async def _delete(args: dict) -> str:
    resource_name = args.get("resource_name", "")

    def _run():
        _svc().people().deleteContact(resourceName=resource_name).execute()
        return f"Contact deleted: {resource_name}"
    return await asyncio.to_thread(_run)


_ACTIONS = {
    "list": _list,
    "search": _search,
    "get": _get,
    "create": _create,
    "update": _update,
    "delete": _delete,
}


async def _execute(args: dict) -> str:
    action = args.get("action", "")
    fn = _ACTIONS.get(action)
    if not fn:
        return f"Unknown action: {action}. Available: {', '.join(sorted(_ACTIONS))}"
    return await fn(args)


register_tool(
    name="google_contacts",
    description=(
        "Manage Google Contacts: list, search, view, create, update, delete contacts. "
        "Requires Google authentication."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(_ACTIONS.keys()), "description": "Contacts action"},
            "resource_name": {"type": "string", "description": "Contact resource name (e.g. people/c123)"},
            "query": {"type": "string", "description": "Search query"},
            "given_name": {"type": "string", "description": "First name"},
            "family_name": {"type": "string", "description": "Last name"},
            "email": {"type": "string", "description": "Email address"},
            "phone": {"type": "string", "description": "Phone number"},
            "max_results": {"type": "integer", "description": "Max results"},
        },
        "required": ["action"],
    },
    execute=_execute,
)
