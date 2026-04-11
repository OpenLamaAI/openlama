"""Google Forms tool — create forms, add questions, view responses."""

from __future__ import annotations

import asyncio

from openlama.tools.registry import register_tool
from openlama.tools.google_auth import build_service


def _svc():
    return build_service("forms", "v1")


async def _get(args: dict) -> str:
    form_id = args.get("form_id", "")

    def _run():
        form = _svc().forms().get(formId=form_id).execute()
        items = form.get("items", [])
        lines = [
            f"Title: {form.get('info', {}).get('title', '')}",
            f"ID: {form.get('formId', '')}",
            f"Description: {form.get('info', {}).get('description', '')}",
            f"Questions: {len(items)}",
            f"Link: {form.get('responderUri', '')}",
        ]
        for i, item in enumerate(items):
            q = item.get("questionItem", {}).get("question", {})
            lines.append(f"  {i + 1}. {item.get('title', '?')} (required: {q.get('required', False)})")
        return "\n".join(lines)
    return await asyncio.to_thread(_run)


async def _create(args: dict) -> str:
    title = args.get("title", "Untitled Form")
    description = args.get("description", "")

    def _run():
        body = {"info": {"title": title}}
        if description:
            body["info"]["description"] = description
        form = _svc().forms().create(body=body).execute()
        return (
            f"Form created: {title}\n"
            f"ID: {form['formId']}\n"
            f"Edit: https://docs.google.com/forms/d/{form['formId']}/edit\n"
            f"Respond: {form.get('responderUri', '')}"
        )
    return await asyncio.to_thread(_run)


async def _add_question(args: dict) -> str:
    form_id = args.get("form_id", "")
    title = args.get("title", "")
    question_type = args.get("question_type", "TEXT")
    required = args.get("required", False)
    choices = args.get("choices", [])

    def _run():
        question = {"required": required}
        qtype = question_type.upper()
        if qtype in ("TEXT", "PARAGRAPH"):
            question["textQuestion"] = {"paragraph": qtype == "PARAGRAPH"}
        elif qtype in ("RADIO", "CHECKBOX", "DROP_DOWN"):
            question["choiceQuestion"] = {
                "type": qtype,
                "options": [{"value": c} for c in choices] if choices else [{"value": "Option 1"}],
            }
        elif qtype == "SCALE":
            question["scaleQuestion"] = {"low": 1, "high": 5}
        elif qtype == "DATE":
            question["dateQuestion"] = {}
        elif qtype == "TIME":
            question["timeQuestion"] = {}
        else:
            question["textQuestion"] = {"paragraph": False}

        request = {
            "requests": [{
                "createItem": {
                    "item": {
                        "title": title,
                        "questionItem": {"question": question},
                    },
                    "location": {"index": 0},
                }
            }]
        }
        _svc().forms().batchUpdate(formId=form_id, body=request).execute()
        return f"Question added: {title} (type: {question_type})"
    return await asyncio.to_thread(_run)


async def _update(args: dict) -> str:
    form_id = args.get("form_id", "")
    title = args.get("title", "")
    description = args.get("description", "")

    def _run():
        requests = []
        if title:
            requests.append({"updateFormInfo": {"info": {"title": title}, "updateMask": "title"}})
        if description:
            requests.append({"updateFormInfo": {"info": {"description": description}, "updateMask": "description"}})
        if not requests:
            return "No update fields specified."
        _svc().forms().batchUpdate(formId=form_id, body={"requests": requests}).execute()
        return f"Form updated: {title or '(unchanged)'}"
    return await asyncio.to_thread(_run)


async def _delete_question(args: dict) -> str:
    form_id = args.get("form_id", "")
    question_index = int(args.get("question_index", 0))

    def _run():
        form = _svc().forms().get(formId=form_id).execute()
        items = form.get("items", [])
        if question_index >= len(items):
            return f"Question index {question_index} out of range (total: {len(items)})"
        _svc().forms().batchUpdate(formId=form_id, body={
            "requests": [{"deleteItem": {"location": {"index": question_index}}}]
        }).execute()
        return f"Question at index {question_index} deleted."
    return await asyncio.to_thread(_run)


async def _move_question(args: dict) -> str:
    form_id = args.get("form_id", "")
    from_index = int(args.get("from_index", 0))
    to_index = int(args.get("to_index", 0))

    def _run():
        _svc().forms().batchUpdate(formId=form_id, body={
            "requests": [{"moveItem": {"originalLocation": {"index": from_index}, "newLocation": {"index": to_index}}}]
        }).execute()
        return f"Question moved from index {from_index} to {to_index}."
    return await asyncio.to_thread(_run)


async def _responses_get(args: dict) -> str:
    form_id = args.get("form_id", "")
    response_id = args.get("response_id", "")

    def _run():
        r = _svc().forms().responses().get(formId=form_id, responseId=response_id).execute()
        lines = [f"Response ID: {r.get('responseId', '')}", f"Created: {r.get('createTime', '')}"]
        for qid, a in r.get("answers", {}).items():
            texts = [t.get("value", "") for t in a.get("textAnswers", {}).get("answers", [])]
            lines.append(f"  {qid}: {', '.join(texts)}")
        return "\n".join(lines)
    return await asyncio.to_thread(_run)


async def _responses(args: dict) -> str:
    form_id = args.get("form_id", "")
    max_results = int(args.get("max_results", 20))

    def _run():
        result = _svc().forms().responses().list(formId=form_id, pageSize=max_results).execute()
        responses = result.get("responses", [])
        if not responses:
            return "No responses."
        lines = [f"Responses ({len(responses)}):"]
        for r in responses:
            ts = r.get("createTime", "?")
            answers = r.get("answers", {})
            answer_strs = []
            for qid, a in answers.items():
                texts = [t.get("value", "") for t in a.get("textAnswers", {}).get("answers", [])]
                answer_strs.append(f"{qid}: {', '.join(texts)}")
            lines.append(f"\n  [{ts}]")
            for a in answer_strs:
                lines.append(f"    {a}")
        return "\n".join(lines)
    return await asyncio.to_thread(_run)


_ACTIONS = {
    "get": _get,
    "create": _create,
    "update": _update,
    "add_question": _add_question,
    "delete_question": _delete_question,
    "move_question": _move_question,
    "responses": _responses,
    "responses_get": _responses_get,
}


async def _execute(args: dict) -> str:
    action = args.get("action", "")
    fn = _ACTIONS.get(action)
    if not fn:
        return f"Unknown action: {action}. Available: {', '.join(sorted(_ACTIONS))}"
    return await fn(args)


register_tool(
    name="google_forms",
    description=(
        "Manage Google Forms: view form details, create forms, add questions, "
        "view responses. Requires Google authentication."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(_ACTIONS.keys()), "description": "Forms action"},
            "form_id": {"type": "string", "description": "Form ID"},
            "title": {"type": "string", "description": "Form/question title"},
            "description": {"type": "string", "description": "Form description"},
            "question_type": {
                "type": "string",
                "enum": ["TEXT", "PARAGRAPH", "RADIO", "CHECKBOX", "DROP_DOWN", "SCALE", "DATE", "TIME"],
                "description": "Question type",
            },
            "required": {"type": "boolean", "description": "Required question"},
            "choices": {"type": "array", "items": {"type": "string"}, "description": "Answer choices (for RADIO/CHECKBOX/DROP_DOWN)"},
            "max_results": {"type": "integer", "description": "Max responses to return"},
        },
        "required": ["action"],
    },
    execute=_execute,
)
