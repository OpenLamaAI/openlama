"""Tool: memory — Long-term + episodic daily memory management."""
from openlama.tools.registry import register_tool
from openlama.core.memory import (
    save_memory_entry,
    load_memory,
    save_daily_entry,
    list_daily_dates,
    read_daily_memory,
    search_daily_memories,
)


async def _execute(args: dict) -> str:
    action = args.get("action", "").strip()
    content = args.get("content", "").strip()
    category = args.get("category", "other").strip()
    query = args.get("query", "").strip()
    date = args.get("date", "").strip()
    date_from = args.get("date_from", "").strip() or None
    date_to = args.get("date_to", "").strip() or None

    # ── Long-term memory (MEMORY.md) ──

    if action == "save":
        if not content:
            return "Please specify the content."
        entry = save_memory_entry(content, category)
        return f"Memory saved: {entry}"

    if action == "list":
        text = load_memory()
        return text if text else "No saved memories."

    if action == "search":
        if not query:
            return "Please specify a query."
        text = load_memory()
        if not text:
            return "No saved memories."
        matches = [l for l in text.split("\n") if query.lower() in l.lower()]
        return "\n".join(matches) if matches else f"No memories found for '{query}'."

    if action == "delete":
        if not content:
            return "Please specify the content to delete."
        from pathlib import Path
        from openlama.config import get_config
        memory_path = Path(get_config("prompts_dir")) / "MEMORY.md"
        if not memory_path.exists():
            return "No saved memories."
        text = memory_path.read_text(encoding="utf-8")
        lines = text.split("\n")
        new_lines = [l for l in lines if content.lower() not in l.lower()]
        memory_path.write_text("\n".join(new_lines), encoding="utf-8")
        removed = len(lines) - len(new_lines)
        return f"{removed} memory item(s) deleted."

    # ── Episodic daily memory (memories/YYYY-MM-DD.md) ──

    if action == "list_dates":
        dates = list_daily_dates()
        if not dates:
            return "No daily memories found."
        lines = ["Available daily memories:"]
        for d in dates:
            lines.append(f"  {d['date']}  ({d['sections']} entries, {d['size']:,} bytes)")
        return "\n".join(lines)

    if action == "read_daily":
        if not date:
            return "Please specify a date (YYYY-MM-DD)."
        return read_daily_memory(date, query=query or None)

    if action == "search_daily":
        if not query:
            return "Please specify a query."
        results = search_daily_memories(query, date_from=date_from, date_to=date_to)
        if not results:
            scope = ""
            if date_from or date_to:
                scope = f" ({date_from or '...'} ~ {date_to or '...'})"
            return f"No daily memories found for '{query}'{scope}."
        lines = [f"Found {len(results)} match(es):"]
        for r in results:
            lines.append(f"  [{r['date']} {r['time']}] ({r['source']}) {r['snippet']}")
        return "\n".join(lines)

    if action == "save_daily":
        if not content:
            return "Please specify the content."
        source = category or "manual"
        path = save_daily_entry(content, source=source)
        return f"Daily memory saved: {path}"

    actions = "save, list, search, delete, list_dates, read_daily, search_daily, save_daily"
    return f"Unknown action: {action}. Available: {actions}"


register_tool(
    name="memory",
    description=(
        "Memory management tool. "
        "Long-term: save/list/search/delete (MEMORY.md). "
        "Daily episodic: list_dates/read_daily/search_daily/save_daily (memories/YYYY-MM-DD.md). "
        "Use search_daily to find past conversations by keyword and date range."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": (
                    "Action: save, list, search, delete (long-term MEMORY.md) | "
                    "list_dates, read_daily, search_daily, save_daily (daily episodic)"
                ),
            },
            "content": {"type": "string", "description": "Content to save or delete"},
            "category": {"type": "string", "description": "Category: preference, project, fact, other (for save) or source tag (for save_daily)"},
            "query": {"type": "string", "description": "Search keyword (for search, search_daily, read_daily)"},
            "date": {"type": "string", "description": "Date YYYY-MM-DD (for read_daily)"},
            "date_from": {"type": "string", "description": "Start date YYYY-MM-DD (for search_daily, optional)"},
            "date_to": {"type": "string", "description": "End date YYYY-MM-DD (for search_daily, optional)"},
        },
        "required": ["action"],
    },
    execute=_execute,
    admin_only=False,
)
