"""Skills system — discover, load, match, and inject user-defined skills."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from openlama.config import get_config, DATA_DIR
from openlama.logger import get_logger

logger = get_logger("skills")

# Cache: invalidated by save_skill/delete_skill
_skills_cache: list[dict] | None = None
_skills_cache_ts: float = 0
_CACHE_TTL = 30  # seconds


def _skills_dir() -> Path:
    """Get the skills directory path."""
    return DATA_DIR / "skills"


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from SKILL.md content.

    Returns (metadata_dict, body_text).
    """
    text = text.strip()
    if not text.startswith("---"):
        return {}, text

    end = text.find("---", 3)
    if end == -1:
        return {}, text

    frontmatter = text[3:end].strip()
    body = text[end + 3:].strip()

    meta: dict = {}
    for line in frontmatter.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            meta[key] = val

    return meta, body


def _invalidate_cache():
    global _skills_cache, _skills_cache_ts
    _skills_cache = None
    _skills_cache_ts = 0


def discover_skills() -> list[dict]:
    """Scan skills directory and return metadata for all skills. Cached for 30s."""
    global _skills_cache, _skills_cache_ts
    now = time.time()
    if _skills_cache is not None and (now - _skills_cache_ts) < _CACHE_TTL:
        return _skills_cache

    d = _skills_dir()
    if not d.exists():
        _skills_cache = []
        _skills_cache_ts = now
        return []

    skills = []
    for skill_dir in sorted(d.iterdir()):
        if not skill_dir.is_dir():
            continue
        try:
            skill_md = skill_dir / "SKILL.md"
            text = skill_md.read_text(encoding="utf-8")
            meta, body = _parse_frontmatter(text)
            name = meta.get("name", skill_dir.name)
            skills.append({
                "name": name,
                "description": meta.get("description", ""),
                "trigger": meta.get("trigger", ""),
                "body": body,
                "path": str(skill_dir),
            })
        except Exception as e:
            logger.warning("failed to parse skill %s: %s", skill_dir.name, e)

    _skills_cache = skills
    _skills_cache_ts = now
    return skills


def load_skill(name: str) -> Optional[dict]:
    """Load a skill by name. Uses cache from discover_skills() when available."""
    for s in discover_skills():
        if s["name"] == name:
            return s
    return None


def list_skills() -> list[dict]:
    """Return list of all skills with name, description, trigger."""
    return discover_skills()


def match_skill(user_text: str) -> Optional[dict]:
    """Match user text against skill triggers.

    Returns the best matching skill or None.
    Matching logic:
    1. Check trigger keywords (comma-separated) against user text
    2. Return the skill with the most keyword matches
    """
    if not user_text:
        return None

    text_lower = user_text.lower()
    skills = discover_skills()
    best_match = None
    best_score = 0

    for skill in skills:
        trigger = skill.get("trigger", "")
        if not trigger:
            continue

        keywords = [kw.strip().lower() for kw in trigger.split(",") if kw.strip()]
        score = sum(1 for kw in keywords if kw in text_lower)

        if score > best_score:
            best_score = score
            best_match = skill

    if best_match and best_score > 0:
        return best_match
    return None


def get_skill_prompt(name: str) -> str:
    """Get the skill body as a system prompt fragment."""
    skill = load_skill(name)
    if not skill:
        return ""
    return skill.get("body", "")


def build_skills_section() -> str:
    """Build the skills list section for the system prompt."""
    skills = discover_skills()
    if not skills:
        return ""

    lines = ["## Available Skills"]
    for s in skills:
        desc = s.get("description", "No description")
        trigger = s.get("trigger", "")
        trigger_hint = f" (trigger: {trigger})" if trigger else ""
        lines.append(f"- **{s['name']}**: {desc}{trigger_hint}")

    lines.append("")
    lines.append("When a skill is triggered, it operates according to that skill's instructions.")
    return "\n".join(lines)


def save_skill(name: str, description: str, trigger: str, instructions: str) -> str:
    """Create or update a skill. Returns the skill directory path."""
    d = _skills_dir() / name
    d.mkdir(parents=True, exist_ok=True)

    content = f"""---
name: {name}
description: "{description}"
trigger: "{trigger}"
---

{instructions}
"""
    (d / "SKILL.md").write_text(content, encoding="utf-8")
    _invalidate_cache()
    logger.info("saved skill: %s at %s", name, d)
    return str(d)


def delete_skill(name: str) -> bool:
    """Delete a skill directory. Returns True if deleted."""
    import shutil
    d = _skills_dir() / name
    if not d.exists():
        return False
    shutil.rmtree(d)
    _invalidate_cache()
    logger.info("deleted skill: %s", name)
    return True
