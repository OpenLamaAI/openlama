"""Google Sheets tool — read, write, format, manage spreadsheets."""

from __future__ import annotations

import asyncio
import re

from openlama.tools.registry import register_tool
from openlama.tools.google_auth import build_service
from openlama.config import DATA_DIR


def _sheets_svc():
    return build_service("sheets", "v4")


def _drive_svc():
    return build_service("drive", "v3")


def _col_to_index(col: str) -> int:
    """Convert column letter(s) to 0-based index. A=0, B=1, Z=25, AA=26."""
    result = 0
    for ch in col.upper():
        result = result * 26 + (ord(ch) - ord("A") + 1)
    return result - 1


def _parse_a1_range(spreadsheet_id: str, range_str: str) -> dict:
    """Parse A1 notation to a GridRange dict. Returns {sheetId, startRowIndex, endRowIndex, startColumnIndex, endColumnIndex}."""
    svc = _sheets_svc()
    ss = svc.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()

    sheet_name = ""
    cell_range = range_str
    if "!" in range_str:
        sheet_name, cell_range = range_str.rsplit("!", 1)
        sheet_name = sheet_name.strip("'")

    sheet_id = ss["sheets"][0]["properties"]["sheetId"]
    if sheet_name:
        for s in ss.get("sheets", []):
            if s["properties"]["title"] == sheet_name:
                sheet_id = s["properties"]["sheetId"]
                break

    grid = {"sheetId": sheet_id}
    m = re.match(r"([A-Za-z]+)(\d+)(?::([A-Za-z]+)(\d+))?", cell_range)
    if m:
        grid["startColumnIndex"] = _col_to_index(m.group(1))
        grid["startRowIndex"] = int(m.group(2)) - 1
        if m.group(3) and m.group(4):
            grid["endColumnIndex"] = _col_to_index(m.group(3)) + 1
            grid["endRowIndex"] = int(m.group(4))
        else:
            grid["endColumnIndex"] = grid["startColumnIndex"] + 1
            grid["endRowIndex"] = grid["startRowIndex"] + 1
    return grid


def _get_sheet_id(spreadsheet_id: str, sheet_name: str = "") -> int:
    """Get sheet ID by name, or first sheet if name is empty."""
    ss = _sheets_svc().spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    if sheet_name:
        for s in ss.get("sheets", []):
            if s["properties"]["title"] == sheet_name:
                return s["properties"]["sheetId"]
    return ss["sheets"][0]["properties"]["sheetId"]


async def _metadata(args: dict) -> str:
    spreadsheet_id = args.get("spreadsheet_id", "")

    def _run():
        ss = _sheets_svc().spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        sheets = ss.get("sheets", [])
        lines = [
            f"Title: {ss.get('properties', {}).get('title', '')}",
            f"ID: {ss.get('spreadsheetId', '')}",
            f"URL: {ss.get('spreadsheetUrl', '')}",
            f"Sheets ({len(sheets)}):",
        ]
        for s in sheets:
            props = s.get("properties", {})
            grid = props.get("gridProperties", {})
            lines.append(f"  {props.get('title', '?')} (ID: {props.get('sheetId', '')}, {grid.get('rowCount', '?')}x{grid.get('columnCount', '?')})")
        return "\n".join(lines)
    return await asyncio.to_thread(_run)


async def _get(args: dict) -> str:
    spreadsheet_id = args.get("spreadsheet_id", "")
    range_str = args.get("range", "Sheet1")

    def _run():
        result = _sheets_svc().spreadsheets().values().get(
            spreadsheetId=spreadsheet_id, range=range_str,
        ).execute()
        values = result.get("values", [])
        if not values:
            return f"No data in range '{range_str}'."
        lines = []
        for i, row in enumerate(values):
            lines.append(f"  {i + 1:4d} | {' | '.join(str(c) for c in row)}")
        return f"Range: {range_str} ({len(values)} rows)\n" + "\n".join(lines)
    return await asyncio.to_thread(_run)


async def _create(args: dict) -> str:
    title = args.get("title", "Untitled")
    sheet_names = args.get("sheet_names", [])

    def _run():
        body = {"properties": {"title": title}}
        if sheet_names:
            body["sheets"] = [{"properties": {"title": n}} for n in sheet_names]
        ss = _sheets_svc().spreadsheets().create(body=body).execute()
        return f"Spreadsheet created: {title}\nID: {ss['spreadsheetId']}\nLink: {ss.get('spreadsheetUrl', '')}"
    return await asyncio.to_thread(_run)


async def _copy(args: dict) -> str:
    spreadsheet_id = args.get("spreadsheet_id", "")
    name = args.get("name", "")

    def _run():
        body = {"name": name} if name else {}
        f = _drive_svc().files().copy(fileId=spreadsheet_id, body=body, fields="id,name,webViewLink").execute()
        return f"Copied: {f['name']} (ID: {f['id']})\nLink: {f.get('webViewLink', '')}"
    return await asyncio.to_thread(_run)


async def _export(args: dict) -> str:
    spreadsheet_id = args.get("spreadsheet_id", "")
    fmt = args.get("format", "xlsx")

    def _run():
        import httpx
        from openlama.tools.google_auth import get_google_creds
        creds = get_google_creds()
        mime_map = {
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "pdf": "application/pdf",
            "csv": "text/csv",
            "ods": "application/vnd.oasis.opendocument.spreadsheet",
        }
        mime = mime_map.get(fmt, f"application/{fmt}")
        url = f"https://www.googleapis.com/drive/v3/files/{spreadsheet_id}/export?mimeType={mime}"
        resp = httpx.get(url, headers={"Authorization": f"Bearer {creds.token}"}, timeout=60)
        resp.raise_for_status()
        out_dir = DATA_DIR / "tmp_uploads"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"sheet_export.{fmt}"
        out_path.write_bytes(resp.content)
        return f"Exported: {out_path} ({out_path.stat().st_size:,} bytes)"
    return await asyncio.to_thread(_run)


async def _update(args: dict) -> str:
    spreadsheet_id = args.get("spreadsheet_id", "")
    range_str = args.get("range", "")
    values = args.get("values", [])

    def _run():
        if not range_str:
            return "Error: 'range' parameter is required."
        body = {"values": values}
        result = _sheets_svc().spreadsheets().values().update(
            spreadsheetId=spreadsheet_id, range=range_str,
            valueInputOption="USER_ENTERED", body=body,
        ).execute()
        return f"Updated {result.get('updatedCells', 0)} cell(s) in {range_str}."
    return await asyncio.to_thread(_run)


async def _append(args: dict) -> str:
    spreadsheet_id = args.get("spreadsheet_id", "")
    range_str = args.get("range", "Sheet1")
    values = args.get("values", [])

    def _run():
        body = {"values": values}
        result = _sheets_svc().spreadsheets().values().append(
            spreadsheetId=spreadsheet_id, range=range_str,
            valueInputOption="USER_ENTERED", body=body,
        ).execute()
        updates = result.get("updates", {})
        return f"Appended {updates.get('updatedRows', 0)} row(s) to {range_str}."
    return await asyncio.to_thread(_run)


async def _clear(args: dict) -> str:
    spreadsheet_id = args.get("spreadsheet_id", "")
    range_str = args.get("range", "")

    def _run():
        if not range_str:
            return "Error: 'range' parameter is required."
        _sheets_svc().spreadsheets().values().clear(
            spreadsheetId=spreadsheet_id, range=range_str, body={},
        ).execute()
        return f"Cleared range: {range_str}"
    return await asyncio.to_thread(_run)


async def _find_replace(args: dict) -> str:
    spreadsheet_id = args.get("spreadsheet_id", "")
    find = args.get("find", "")
    replace = args.get("replace", "")
    sheet_name = args.get("sheet_name", "")

    def _run():
        request = {"findReplace": {"find": find, "replacement": replace, "allSheets": not bool(sheet_name)}}
        if sheet_name:
            sheet_id = _get_sheet_id(spreadsheet_id, sheet_name)
            request["findReplace"]["sheetId"] = sheet_id
        result = _sheets_svc().spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": [request]},
        ).execute()
        replies = result.get("replies", [{}])
        count = replies[0].get("findReplace", {}).get("occurrencesChanged", 0) if replies else 0
        return f"Replaced {count} occurrence(s) of '{find}' with '{replace}'."
    return await asyncio.to_thread(_run)


async def _add_tab(args: dict) -> str:
    spreadsheet_id = args.get("spreadsheet_id", "")
    tab_name = args.get("tab_name", "New Sheet")

    def _run():
        _sheets_svc().spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={
            "requests": [{"addSheet": {"properties": {"title": tab_name}}}]
        }).execute()
        return f"Tab added: {tab_name}"
    return await asyncio.to_thread(_run)


async def _rename_tab(args: dict) -> str:
    spreadsheet_id = args.get("spreadsheet_id", "")
    old_name = args.get("old_name", "")
    new_name = args.get("new_name", "")

    def _run():
        sheet_id = _get_sheet_id(spreadsheet_id, old_name)
        _sheets_svc().spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={
            "requests": [{"updateSheetProperties": {"properties": {"sheetId": sheet_id, "title": new_name}, "fields": "title"}}]
        }).execute()
        return f"Tab renamed: {old_name} → {new_name}"
    return await asyncio.to_thread(_run)


async def _delete_tab(args: dict) -> str:
    spreadsheet_id = args.get("spreadsheet_id", "")
    tab_name = args.get("tab_name", "")

    def _run():
        sheet_id = _get_sheet_id(spreadsheet_id, tab_name)
        _sheets_svc().spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={
            "requests": [{"deleteSheet": {"sheetId": sheet_id}}]
        }).execute()
        return f"Tab deleted: {tab_name}"
    return await asyncio.to_thread(_run)


async def _named_ranges(args: dict) -> str:
    spreadsheet_id = args.get("spreadsheet_id", "")

    def _run():
        ss = _sheets_svc().spreadsheets().get(spreadsheetId=spreadsheet_id, fields="namedRanges").execute()
        ranges = ss.get("namedRanges", [])
        if not ranges:
            return "No named ranges."
        lines = [f"  {r.get('name', '?')} (ID: {r.get('namedRangeId', '')})" for r in ranges]
        return f"Named ranges ({len(ranges)}):\n" + "\n".join(lines)
    return await asyncio.to_thread(_run)


async def _merge(args: dict) -> str:
    spreadsheet_id = args.get("spreadsheet_id", "")
    range_str = args.get("range", "")

    def _run():
        if not range_str:
            return "Error: 'range' parameter is required (e.g. Sheet1!A1:C3)."
        grid = _parse_a1_range(spreadsheet_id, range_str)
        _sheets_svc().spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={
            "requests": [{"mergeCells": {"range": grid, "mergeType": "MERGE_ALL"}}]
        }).execute()
        return f"Cells merged: {range_str}"
    return await asyncio.to_thread(_run)


async def _unmerge(args: dict) -> str:
    spreadsheet_id = args.get("spreadsheet_id", "")
    range_str = args.get("range", "")

    def _run():
        if not range_str:
            return "Error: 'range' parameter is required."
        grid = _parse_a1_range(spreadsheet_id, range_str)
        _sheets_svc().spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={
            "requests": [{"unmergeCells": {"range": grid}}]
        }).execute()
        return f"Cells unmerged: {range_str}"
    return await asyncio.to_thread(_run)


async def _format(args: dict) -> str:
    spreadsheet_id = args.get("spreadsheet_id", "")
    range_str = args.get("range", "")
    bold = args.get("bold", None)
    italic = args.get("italic", None)
    font_size = args.get("font_size", None)
    bg_color = args.get("bg_color", "")

    def _run():
        if not range_str:
            return "Error: 'range' parameter is required."
        grid = _parse_a1_range(spreadsheet_id, range_str)

        cell_format = {}
        fields_parts = []
        if bold is not None:
            cell_format.setdefault("textFormat", {})["bold"] = bold
            fields_parts.append("userEnteredFormat.textFormat.bold")
        if italic is not None:
            cell_format.setdefault("textFormat", {})["italic"] = italic
            fields_parts.append("userEnteredFormat.textFormat.italic")
        if font_size is not None:
            cell_format.setdefault("textFormat", {})["fontSize"] = font_size
            fields_parts.append("userEnteredFormat.textFormat.fontSize")
        if bg_color:
            # Parse hex color #RRGGBB
            bg_color = bg_color.lstrip("#")
            if len(bg_color) == 6:
                r, g, b = int(bg_color[:2], 16) / 255, int(bg_color[2:4], 16) / 255, int(bg_color[4:6], 16) / 255
                cell_format["backgroundColor"] = {"red": r, "green": g, "blue": b}
                fields_parts.append("userEnteredFormat.backgroundColor")

        if not fields_parts:
            return "No formatting options specified. Use bold, italic, font_size, or bg_color."

        _sheets_svc().spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={
            "requests": [{"repeatCell": {
                "range": grid,
                "cell": {"userEnteredFormat": cell_format},
                "fields": ",".join(fields_parts),
            }}]
        }).execute()
        return f"Formatting applied to {range_str}."
    return await asyncio.to_thread(_run)


async def _number_format(args: dict) -> str:
    spreadsheet_id = args.get("spreadsheet_id", "")
    range_str = args.get("range", "")
    format_type = args.get("number_type", "NUMBER")
    pattern = args.get("pattern", "")

    def _run():
        if not range_str:
            return "Error: 'range' parameter is required."
        grid = _parse_a1_range(spreadsheet_id, range_str)
        nf = {"type": format_type}
        if pattern:
            nf["pattern"] = pattern
        _sheets_svc().spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={
            "requests": [{"repeatCell": {
                "range": grid,
                "cell": {"userEnteredFormat": {"numberFormat": nf}},
                "fields": "userEnteredFormat.numberFormat",
            }}]
        }).execute()
        return f"Number format applied to {range_str}: type={format_type}, pattern={pattern or 'default'}"
    return await asyncio.to_thread(_run)


async def _freeze(args: dict) -> str:
    spreadsheet_id = args.get("spreadsheet_id", "")
    sheet_name = args.get("sheet_name", "")
    rows = int(args.get("freeze_rows", 0))
    cols = int(args.get("freeze_cols", 0))

    def _run():
        sheet_id = _get_sheet_id(spreadsheet_id, sheet_name)
        props = {"sheetId": sheet_id, "gridProperties": {}}
        fields_parts = []
        if rows:
            props["gridProperties"]["frozenRowCount"] = rows
            fields_parts.append("gridProperties.frozenRowCount")
        if cols:
            props["gridProperties"]["frozenColumnCount"] = cols
            fields_parts.append("gridProperties.frozenColumnCount")
        if not fields_parts:
            return "Specify freeze_rows and/or freeze_cols."
        _sheets_svc().spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={
            "requests": [{"updateSheetProperties": {"properties": props, "fields": ",".join(fields_parts)}}]
        }).execute()
        return f"Frozen: {rows} row(s), {cols} column(s)"
    return await asyncio.to_thread(_run)


async def _insert(args: dict) -> str:
    spreadsheet_id = args.get("spreadsheet_id", "")
    sheet_name = args.get("sheet_name", "")
    dimension = args.get("dimension", "ROWS")
    start_index = int(args.get("start_index", 0))
    count = int(args.get("count", 1))

    def _run():
        sheet_id = _get_sheet_id(spreadsheet_id, sheet_name)
        _sheets_svc().spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={
            "requests": [{"insertDimension": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": dimension,
                    "startIndex": start_index,
                    "endIndex": start_index + count,
                },
                "inheritFromBefore": start_index > 0,
            }}]
        }).execute()
        return f"Inserted {count} {dimension.lower()} at index {start_index}."
    return await asyncio.to_thread(_run)


async def _notes(args: dict) -> str:
    spreadsheet_id = args.get("spreadsheet_id", "")
    range_str = args.get("range", "Sheet1")

    def _run():
        result = _sheets_svc().spreadsheets().get(
            spreadsheetId=spreadsheet_id,
            ranges=[range_str],
            fields="sheets.data.rowData.values.note",
        ).execute()
        lines = []
        for sheet in result.get("sheets", []):
            for rd_idx, rd in enumerate(sheet.get("data", [{}])[0].get("rowData", [])):
                for c_idx, cell in enumerate(rd.get("values", [])):
                    note = cell.get("note", "")
                    if note:
                        lines.append(f"  Row {rd_idx + 1}, Col {c_idx + 1}: {note}")
        if not lines:
            return f"No notes in {range_str}."
        return f"Notes ({len(lines)}):\n" + "\n".join(lines)
    return await asyncio.to_thread(_run)


async def _update_note(args: dict) -> str:
    spreadsheet_id = args.get("spreadsheet_id", "")
    cell = args.get("cell", "")
    note = args.get("note", "")

    def _run():
        if not cell:
            return "Error: 'cell' parameter is required (e.g. A1 or Sheet1!B2)."
        grid = _parse_a1_range(spreadsheet_id, cell)
        _sheets_svc().spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={
            "requests": [{"updateCells": {
                "rows": [{"values": [{"note": note}]}],
                "fields": "note",
                "range": grid,
            }}]
        }).execute()
        return f"Note {'set' if note else 'cleared'} on {cell}."
    return await asyncio.to_thread(_run)


async def _resize_columns(args: dict) -> str:
    spreadsheet_id = args.get("spreadsheet_id", "")
    sheet_name = args.get("sheet_name", "")
    start_col = int(args.get("start_col", 0))
    end_col = int(args.get("end_col", 1))
    auto = args.get("auto", True)

    def _run():
        sheet_id = _get_sheet_id(spreadsheet_id, sheet_name)
        _sheets_svc().spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={
            "requests": [{"autoResizeDimensions": {
                "dimensions": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": start_col,
                    "endIndex": end_col,
                },
            }}]
        }).execute()
        return f"Columns {start_col}-{end_col} auto-resized."
    return await asyncio.to_thread(_run)


# ── Dispatcher ───────────────────────────────────────

_ACTIONS = {
    "metadata": _metadata,
    "get": _get,
    "create": _create,
    "copy": _copy,
    "export": _export,
    "update": _update,
    "append": _append,
    "clear": _clear,
    "find_replace": _find_replace,
    "add_tab": _add_tab,
    "rename_tab": _rename_tab,
    "delete_tab": _delete_tab,
    "named_ranges": _named_ranges,
    "merge": _merge,
    "unmerge": _unmerge,
    "format": _format,
    "number_format": _number_format,
    "freeze": _freeze,
    "insert": _insert,
    "notes": _notes,
    "update_note": _update_note,
    "resize_columns": _resize_columns,
}


async def _execute(args: dict) -> str:
    action = args.get("action", "")
    fn = _ACTIONS.get(action)
    if not fn:
        return f"Unknown action: {action}. Available: {', '.join(sorted(_ACTIONS))}"
    return await fn(args)


register_tool(
    name="google_sheets",
    description=(
        "Manage Google Sheets: read/write cell ranges, create/copy spreadsheets, export (xlsx/pdf/csv), "
        "append rows, clear data, find & replace, manage tabs/named ranges, "
        "format/number-format cells, merge/unmerge, freeze rows/cols, insert rows/cols, "
        "cell notes, auto-resize columns. Requires Google authentication."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(_ACTIONS.keys()), "description": "Sheets action"},
            "spreadsheet_id": {"type": "string", "description": "Spreadsheet ID"},
            "range": {"type": "string", "description": "Cell range in A1 notation (e.g. Sheet1!A1:C10)"},
            "values": {"type": "array", "items": {"type": "array"}, "description": "2D array of values [[row1], [row2]]"},
            "title": {"type": "string", "description": "Spreadsheet title"},
            "name": {"type": "string", "description": "Copy name"},
            "sheet_names": {"type": "array", "items": {"type": "string"}, "description": "Sheet names to create"},
            "tab_name": {"type": "string", "description": "Tab name"},
            "old_name": {"type": "string", "description": "Old tab name (rename)"},
            "new_name": {"type": "string", "description": "New tab name (rename)"},
            "sheet_name": {"type": "string", "description": "Target sheet name"},
            "find": {"type": "string", "description": "Text to find"},
            "replace": {"type": "string", "description": "Replacement text"},
            "format": {"type": "string", "enum": ["xlsx", "pdf", "csv", "ods"], "description": "Export format"},
            "bold": {"type": "boolean", "description": "Bold formatting"},
            "italic": {"type": "boolean", "description": "Italic formatting"},
            "font_size": {"type": "integer", "description": "Font size"},
            "bg_color": {"type": "string", "description": "Background color (#RRGGBB hex)"},
            "number_type": {"type": "string", "enum": ["NUMBER", "CURRENCY", "PERCENT", "DATE", "TIME", "TEXT"], "description": "Number format type"},
            "pattern": {"type": "string", "description": "Number format pattern (e.g. #,##0.00)"},
            "freeze_rows": {"type": "integer", "description": "Number of rows to freeze"},
            "freeze_cols": {"type": "integer", "description": "Number of columns to freeze"},
            "dimension": {"type": "string", "enum": ["ROWS", "COLUMNS"], "description": "Insert dimension"},
            "start_index": {"type": "integer", "description": "Start index for insert"},
            "count": {"type": "integer", "description": "Number of rows/columns to insert"},
            "cell": {"type": "string", "description": "Cell reference for notes (e.g. A1)"},
            "note": {"type": "string", "description": "Note text"},
            "start_col": {"type": "integer", "description": "Start column index (0-based)"},
            "end_col": {"type": "integer", "description": "End column index"},
            "auto": {"type": "boolean", "description": "Auto-resize"},
        },
        "required": ["action"],
    },
    execute=_execute,
)
