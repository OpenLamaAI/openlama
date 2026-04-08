"""Long-term memory management — MEMORY.md file operations."""
from __future__ import annotations

from pathlib import Path
from datetime import datetime

from openlama.config import get_config, get_config_int
from openlama.logger import get_logger

logger = get_logger("memory")


def _memory_path() -> Path:
    return Path(get_config("prompts_dir")) / "MEMORY.md"


def load_memory() -> str:
    p = _memory_path()
    if p.exists():
        return p.read_text(encoding="utf-8")
    return ""


def save_memory_entry(content: str, category: str = "other") -> str:
    p = _memory_path()
    p.parent.mkdir(parents=True, exist_ok=True)

    date = datetime.now().strftime("%Y-%m-%d")
    entry = f"- [{date}] {content}"

    existing = p.read_text(encoding="utf-8") if p.exists() else "# \uc7a5\uae30 \uba54\ubaa8\ub9ac\n"

    section = f"## {category}"
    if section in existing:
        lines = existing.split("\n")
        for i, line in enumerate(lines):
            if line.strip() == section:
                lines.insert(i + 1, entry)
                break
        existing = "\n".join(lines)
    else:
        existing += f"\n{section}\n{entry}\n"

    # Enforce max items
    max_items = get_config_int("memory_max_items", 50)
    item_lines = [l for l in existing.split("\n") if l.startswith("- [")]
    if len(item_lines) > max_items:
        for old_line in item_lines[:len(item_lines) - max_items]:
            existing = existing.replace(old_line + "\n", "")

    p.write_text(existing, encoding="utf-8")
    logger.info("memory saved: %s", content[:80])
    return entry
