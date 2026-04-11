"""Google Slides tool — manage presentations."""

from __future__ import annotations

import asyncio

from openlama.tools.registry import register_tool
from openlama.tools.google_auth import build_service
from openlama.config import DATA_DIR


def _slides_svc():
    return build_service("slides", "v1")


def _drive_svc():
    return build_service("drive", "v3")


async def _info(args: dict) -> str:
    presentation_id = args.get("presentation_id", "")

    def _run():
        pres = _slides_svc().presentations().get(presentationId=presentation_id).execute()
        slides = pres.get("slides", [])
        return (
            f"Title: {pres.get('title', '')}\n"
            f"ID: {pres.get('presentationId', '')}\n"
            f"Slides: {len(slides)}\n"
            f"Size: {pres.get('pageSize', {}).get('width', {}).get('magnitude', '?')}x"
            f"{pres.get('pageSize', {}).get('height', {}).get('magnitude', '?')}"
        )
    return await asyncio.to_thread(_run)


async def _create(args: dict) -> str:
    title = args.get("title", "Untitled Presentation")

    def _run():
        pres = _slides_svc().presentations().create(body={"title": title}).execute()
        pid = pres["presentationId"]
        return f"Presentation created: {title}\nID: {pid}\nLink: https://docs.google.com/presentation/d/{pid}"
    return await asyncio.to_thread(_run)


async def _export(args: dict) -> str:
    presentation_id = args.get("presentation_id", "")
    fmt = args.get("format", "pdf")

    def _run():
        mime_map = {
            "pdf": "application/pdf",
            "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        }
        mime = mime_map.get(fmt, f"application/{fmt}")
        data = _drive_svc().files().export(fileId=presentation_id, mimeType=mime).execute()
        out_dir = DATA_DIR / "tmp_uploads"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"slides_export.{fmt}"
        out_path.write_bytes(data if isinstance(data, bytes) else data.encode())
        return f"Exported: {out_path} ({out_path.stat().st_size:,} bytes)"
    return await asyncio.to_thread(_run)


async def _list_slides(args: dict) -> str:
    presentation_id = args.get("presentation_id", "")

    def _run():
        pres = _slides_svc().presentations().get(presentationId=presentation_id).execute()
        slides = pres.get("slides", [])
        lines = []
        for i, s in enumerate(slides):
            elements = len(s.get("pageElements", []))
            notes = ""
            if s.get("slideProperties", {}).get("notesPage", {}).get("pageElements"):
                for pe in s["slideProperties"]["notesPage"]["pageElements"]:
                    shape = pe.get("shape", {})
                    for te in shape.get("text", {}).get("textElements", []):
                        tr = te.get("textRun", {})
                        if tr.get("content", "").strip():
                            notes = tr["content"].strip()[:60]
                            break
            notes_str = f" — notes: {notes}" if notes else ""
            lines.append(f"  {i + 1}. {s.get('objectId', '')} ({elements} elements){notes_str}")
        return f"Slides ({len(slides)}):\n" + "\n".join(lines)
    return await asyncio.to_thread(_run)


async def _read_slide(args: dict) -> str:
    presentation_id = args.get("presentation_id", "")
    slide_index = int(args.get("slide_index", 0))

    def _run():
        pres = _slides_svc().presentations().get(presentationId=presentation_id).execute()
        slides = pres.get("slides", [])
        if slide_index >= len(slides):
            return f"Slide index {slide_index} out of range (total: {len(slides)})"
        s = slides[slide_index]
        lines = [f"Slide {slide_index + 1} (ID: {s.get('objectId', '')})"]
        for pe in s.get("pageElements", []):
            shape = pe.get("shape", {})
            text_parts = []
            for te in shape.get("text", {}).get("textElements", []):
                tr = te.get("textRun", {})
                if tr.get("content"):
                    text_parts.append(tr["content"])
            if text_parts:
                lines.append(f"  Text: {''.join(text_parts).strip()}")
            if pe.get("image"):
                lines.append(f"  Image: {pe['image'].get('sourceUrl', '?')}")
        return "\n".join(lines)
    return await asyncio.to_thread(_run)


async def _copy(args: dict) -> str:
    presentation_id = args.get("presentation_id", "")
    name = args.get("name", "")

    def _run():
        body = {"name": name} if name else {}
        f = _drive_svc().files().copy(fileId=presentation_id, body=body, fields="id,name,webViewLink").execute()
        return f"Copied: {f['name']} (ID: {f['id']})\nLink: {f.get('webViewLink', '')}"
    return await asyncio.to_thread(_run)


async def _delete_slide(args: dict) -> str:
    presentation_id = args.get("presentation_id", "")
    slide_id = args.get("slide_id", "")

    def _run():
        _slides_svc().presentations().batchUpdate(presentationId=presentation_id, body={
            "requests": [{"deleteObject": {"objectId": slide_id}}]
        }).execute()
        return f"Slide deleted: {slide_id}"
    return await asyncio.to_thread(_run)


async def _update_notes(args: dict) -> str:
    presentation_id = args.get("presentation_id", "")
    slide_id = args.get("slide_id", "")
    notes = args.get("notes", "")

    def _run():
        pres = _slides_svc().presentations().get(presentationId=presentation_id).execute()
        notes_id = None
        for s in pres.get("slides", []):
            if s.get("objectId") == slide_id:
                notes_page = s.get("slideProperties", {}).get("notesPage", {})
                for pe in notes_page.get("pageElements", []):
                    shape = pe.get("shape", {})
                    if shape.get("shapeType") == "TEXT_BOX":
                        notes_id = pe.get("objectId")
                        break
                break
        if not notes_id:
            return f"Could not find notes text box for slide {slide_id}"
        _slides_svc().presentations().batchUpdate(presentationId=presentation_id, body={
            "requests": [
                {"deleteText": {"objectId": notes_id, "textRange": {"type": "ALL"}}},
                {"insertText": {"objectId": notes_id, "text": notes, "insertionIndex": 0}},
            ]
        }).execute()
        return f"Notes updated for slide {slide_id}"
    return await asyncio.to_thread(_run)


async def _add_slide(args: dict) -> str:
    presentation_id = args.get("presentation_id", "")
    layout = args.get("layout", "BLANK")

    def _run():
        result = _slides_svc().presentations().batchUpdate(presentationId=presentation_id, body={
            "requests": [{"createSlide": {"slideLayoutReference": {"predefinedLayout": layout}}}]
        }).execute()
        slide_id = result.get("replies", [{}])[0].get("createSlide", {}).get("objectId", "")
        return f"Slide added. ID: {slide_id}"
    return await asyncio.to_thread(_run)


_ACTIONS = {
    "info": _info,
    "create": _create,
    "copy": _copy,
    "export": _export,
    "list_slides": _list_slides,
    "read_slide": _read_slide,
    "add_slide": _add_slide,
    "delete_slide": _delete_slide,
    "update_notes": _update_notes,
}


async def _execute(args: dict) -> str:
    action = args.get("action", "")
    fn = _ACTIONS.get(action)
    if not fn:
        return f"Unknown action: {action}. Available: {', '.join(sorted(_ACTIONS))}"
    return await fn(args)


register_tool(
    name="google_slides",
    description=(
        "Manage Google Slides: view presentation info, create presentations, "
        "export (pdf/pptx), list/read slides, add new slides. "
        "Requires Google authentication."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(_ACTIONS.keys()), "description": "Slides action"},
            "presentation_id": {"type": "string", "description": "Presentation ID"},
            "title": {"type": "string", "description": "Presentation title"},
            "format": {"type": "string", "enum": ["pdf", "pptx"], "description": "Export format"},
            "slide_index": {"type": "integer", "description": "Slide index (0-based)"},
            "layout": {"type": "string", "description": "Slide layout (BLANK, TITLE, TITLE_AND_BODY, etc.)"},
        },
        "required": ["action"],
    },
    execute=_execute,
)
