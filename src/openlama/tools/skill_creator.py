"""Skill creator tool — create, list, view, update, delete skills via chat."""
from __future__ import annotations

from openlama.tools.registry import register_tool
from openlama.core.skills import (
    save_skill, delete_skill, list_skills, load_skill,
)


async def _skill_creator(args: dict) -> str:
    action = args.get("action", "list")

    if action == "list":
        skills = list_skills()
        if not skills:
            return "No skills registered. Use the 'create' action to create a new skill."
        lines = ["📋 Registered Skills:"]
        for s in skills:
            trigger = s.get("trigger", "")
            t_hint = f" | trigger: {trigger}" if trigger else ""
            lines.append(f"- **{s['name']}**: {s.get('description', '')}{t_hint}")
        return "\n".join(lines)

    if action == "create":
        name = args.get("name", "").strip()
        if not name:
            return "Skill name is required."
        description = args.get("description", "").strip()
        if not description:
            return "Skill description is required."
        trigger = args.get("trigger", "").strip()
        instructions = args.get("instructions", "").strip()
        if not instructions:
            return "Skill instructions are required."

        path = save_skill(name, description, trigger, instructions)
        return f"Skill '{name}' has been created.\nPath: {path}"

    if action == "view":
        name = args.get("name", "").strip()
        if not name:
            return "Skill name is required."
        skill = load_skill(name)
        if not skill:
            return f"Skill '{name}' not found."
        lines = [
            f"📄 Skill: {skill['name']}",
            f"Description: {skill.get('description', '')}",
            f"Trigger: {skill.get('trigger', '')}",
            f"---",
            skill.get("body", "(no content)"),
        ]
        return "\n".join(lines)

    if action == "update":
        name = args.get("name", "").strip()
        if not name:
            return "Skill name is required."
        existing = load_skill(name)
        if not existing:
            return f"Skill '{name}' not found."

        description = args.get("description", "").strip() or existing.get("description", "")
        trigger = args.get("trigger", "").strip() or existing.get("trigger", "")
        instructions = args.get("instructions", "").strip() or existing.get("body", "")

        path = save_skill(name, description, trigger, instructions)
        return f"Skill '{name}' has been updated."

    if action == "delete":
        name = args.get("name", "").strip()
        if not name:
            return "Skill name is required."
        if delete_skill(name):
            return f"Skill '{name}' has been deleted."
        return f"Skill '{name}' not found."

    if action == "install":
        file_path = args.get("file_path", "").strip()
        if not file_path:
            return "file_path is required (path to a SKILL.md file or a directory containing one)."

        from pathlib import Path
        import shutil
        from openlama.core.skills import _skills_dir, _invalidate_cache, _parse_frontmatter

        p = Path(file_path)
        if not p.exists():
            return f"Path not found: {file_path}"

        # If it's a file, check if it's a SKILL.md
        if p.is_file():
            if p.name != "SKILL.md":
                return "File must be named SKILL.md."
            skill_dir = p.parent
        else:
            # Directory — check for SKILL.md inside
            skill_md = p / "SKILL.md"
            if not skill_md.exists():
                return f"No SKILL.md found in {file_path}"
            skill_dir = p

        # Parse to get name
        content = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        meta = _parse_frontmatter(content)
        name = meta.get("name", skill_dir.name)

        # Copy to skills directory
        dest = _skills_dir() / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(skill_dir, dest)
        _invalidate_cache()

        return f"Skill '{name}' installed from {file_path}."

    return f"Unknown action: {action}. Available: create, list, view, update, delete, install"


register_tool(
    name="skill_creator",
    description="Create, view, update, and delete custom skills. Skills are instruction sets that activate automatically in specific situations.",
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "list", "view", "update", "delete", "install"],
                "description": "Action to perform",
            },
            "name": {
                "type": "string",
                "description": "Skill name (lowercase, hyphens allowed, e.g., web-researcher)",
            },
            "description": {
                "type": "string",
                "description": "Skill description -- when to use this skill",
            },
            "trigger": {
                "type": "string",
                "description": "Trigger keywords (comma-separated, e.g., research, investigate, look up)",
            },
            "instructions": {
                "type": "string",
                "description": "Skill instructions -- behavioral rules in markdown format",
            },
            "file_path": {
                "type": "string",
                "description": "Path to a SKILL.md file or directory (for install action)",
            },
        },
        "required": ["action"],
    },
    execute=_skill_creator,
)
