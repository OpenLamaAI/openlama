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

    return f"Unknown action: {action}. Available: create, list, view, update, delete"


register_tool(
    name="skill_creator",
    description="Create, view, update, and delete custom skills. Skills are instruction sets that activate automatically in specific situations.",
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "list", "view", "update", "delete"],
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
        },
        "required": ["action"],
    },
    execute=_skill_creator,
)
