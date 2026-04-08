"""Tool: memory — Long-term memory management."""
from pathlib import Path
from openlama.config import get_config
from openlama.tools.registry import register_tool
import json
from datetime import datetime

async def _execute(args: dict) -> str:
    action = args.get("action", "").strip()
    content = args.get("content", "").strip()
    category = args.get("category", "other").strip()
    query = args.get("query", "").strip()

    memory_path = Path(get_config("prompts_dir")) / "MEMORY.md"
    memory_path.parent.mkdir(parents=True, exist_ok=True)

    if action == "save":
        if not content:
            return "Please specify the content."
        date = datetime.now().strftime("%Y-%m-%d")
        entry = f"- [{date}] {content}"

        # Read existing
        existing = memory_path.read_text() if memory_path.exists() else "# Long-term Memory\n"

        # Find or create category section
        section = f"## {category}"
        if section in existing:
            # Add under existing section
            lines = existing.split("\n")
            idx = lines.index(section)
            lines.insert(idx + 1, entry)
            existing = "\n".join(lines)
        else:
            existing += f"\n{section}\n{entry}\n"

        # Check max items
        max_items = int(get_config("memory_max_items", "50"))
        item_lines = [l for l in existing.split("\n") if l.startswith("- [")]
        if len(item_lines) > max_items:
            # Remove oldest
            for old_line in item_lines[:len(item_lines) - max_items]:
                existing = existing.replace(old_line + "\n", "")

        memory_path.write_text(existing)
        return f"Memory saved: {content[:100]}"

    elif action == "list":
        if not memory_path.exists():
            return "No saved memories."
        return memory_path.read_text()

    elif action == "search":
        if not query:
            return "Please specify a query."
        if not memory_path.exists():
            return "No saved memories."
        text = memory_path.read_text()
        matches = [l for l in text.split("\n") if query.lower() in l.lower()]
        return "\n".join(matches) if matches else f"No memories found for '{query}'."

    elif action == "delete":
        if not content:
            return "Please specify the content to delete."
        if not memory_path.exists():
            return "No saved memories."
        text = memory_path.read_text()
        lines = text.split("\n")
        new_lines = [l for l in lines if content.lower() not in l.lower()]
        memory_path.write_text("\n".join(new_lines))
        removed = len(lines) - len(new_lines)
        return f"{removed} memory item(s) deleted."

    return f"Unknown action: {action}. Available: save, list, search, delete"

register_tool(
    name="memory",
    description="Long-term memory save/list/search/delete tool. Use to store information when the user asks to remember something.",
    parameters={
        "type": "object",
        "properties": {
            "action": {"type": "string", "description": "Action to perform: save, list (all entries), search, delete"},
            "content": {"type": "string", "description": "Content to save or delete (for save, delete actions)"},
            "category": {"type": "string", "description": "Category: preference, project, fact, other"},
            "query": {"type": "string", "description": "Search query (for search action)"},
        },
        "required": ["action"],
    },
    execute=_execute,
    admin_only=False,
)
