"""Memory management — long-term (MEMORY.md) + episodic daily memories."""
from __future__ import annotations

import re
from pathlib import Path
from datetime import datetime

from openlama.config import get_config, get_config_int
from openlama.logger import get_logger

logger = get_logger("memory")


# ── Paths ────────────────────────────────────────────────

def _memory_path() -> Path:
    return Path(get_config("prompts_dir")) / "MEMORY.md"


def _daily_dir() -> Path:
    d = Path(get_config("prompts_dir")) / "memories"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Long-term memory (MEMORY.md) ────────────────────────

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

    existing = p.read_text(encoding="utf-8") if p.exists() else "# Long-term Memory\n"

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


# ── Episodic daily memory (memories/YYYY-MM-DD.md) ──────

def save_daily_entry(content: str, source: str = "compression") -> str:
    """Append an entry to today's daily memory file.

    Args:
        content: Summary text to save.
        source: Origin tag — context_compression, context_clear, daily_flush.
    Returns:
        The file path written to.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    path = _daily_dir() / f"{today}.md"
    time_str = datetime.now().strftime("%H:%M")

    entry = f"\n## [{time_str}] {source}\n{content}\n"

    if path.exists():
        existing = path.read_text(encoding="utf-8")
    else:
        existing = f"# {today}\n"

    existing += entry
    path.write_text(existing, encoding="utf-8")
    logger.info("daily memory saved: %s [%s] %d chars", today, source, len(content))
    return str(path)


def list_daily_dates() -> list[dict]:
    """List available daily memory dates with file sizes.

    Returns:
        [{"date": "2026-04-08", "size": 1234, "sections": 3}, ...]
    """
    d = _daily_dir()
    results = []
    for f in sorted(d.glob("*.md"), reverse=True):
        name = f.stem  # "2026-04-08"
        text = f.read_text(encoding="utf-8")
        section_count = text.count("\n## [")
        results.append({
            "date": name,
            "size": f.stat().st_size,
            "sections": section_count,
        })
    return results


def read_daily_memory(date: str, query: str | None = None) -> str:
    """Read a specific date's memory, optionally filtered by keyword.

    Args:
        date: Date string like "2026-04-08".
        query: Optional keyword filter — returns only matching sections.
    Returns:
        Matching content or full file content.
    """
    path = _daily_dir() / f"{date}.md"
    if not path.exists():
        return f"No memory found for {date}."

    text = path.read_text(encoding="utf-8")

    if not query:
        return text

    # Section-level filtering: return sections containing the query
    sections = _split_sections(text)
    matched = []
    q_lower = query.lower()
    for section in sections:
        if q_lower in section.lower():
            matched.append(section.strip())

    if not matched:
        return f"No matches for '{query}' on {date}."
    return "\n\n".join(matched)


def _split_sections(text: str) -> list[str]:
    """Split daily memory text into sections by ## [...] headers."""
    return re.split(r"(?=^## \[)", text, flags=re.MULTILINE)


def search_daily_memories(
    query: str,
    date_from: str | None = None,
    date_to: str | None = None,
    max_results: int = 20,
) -> list[dict]:
    """Search across daily memory files by keyword and date range.

    Returns:
        [{"date": "2026-04-08", "time": "14:30", "source": "...", "snippet": "..."}, ...]
    """
    d = _daily_dir()
    q_lower = query.lower()
    results = []

    for f in sorted(d.glob("*.md"), reverse=True):
        date_str = f.stem
        if date_from and date_str < date_from:
            continue
        if date_to and date_str > date_to:
            continue

        text = f.read_text(encoding="utf-8")
        sections = _split_sections(text)

        for section in sections:
            if q_lower not in section.lower():
                continue

            # Parse header: ## [14:30] source
            header_match = re.match(r".*## \[(\d{2}:\d{2})\]\s*(\S+)", section)
            time_str = header_match.group(1) if header_match else ""
            source = header_match.group(2) if header_match else ""

            # Extract snippet (first meaningful line after header)
            lines = [l.strip() for l in section.split("\n") if l.strip() and not l.startswith("#")]
            snippet = lines[0][:200] if lines else ""

            results.append({
                "date": date_str,
                "time": time_str,
                "source": source,
                "snippet": snippet,
            })

            if len(results) >= max_results:
                return results

    return results


def extract_topics(ctx_items: list[dict]) -> str:
    """Extract brief topic listing from context items without LLM call.

    Used for context_clear and daily_flush — lightweight, no model needed.
    """
    if not ctx_items:
        return ""

    topics = []
    for item in ctx_items:
        user_msg = item.get("u", "").strip()
        if not user_msg:
            continue
        # Take first line, truncate
        first_line = user_msg.split("\n")[0][:150]
        topics.append(f"- {first_line}")

    if not topics:
        return ""

    return f"Conversation topics ({len(topics)} turns):\n" + "\n".join(topics)
