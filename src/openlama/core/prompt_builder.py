"""Multi-prompt assembly — SYSTEM + SOUL + USERS + MEMORY."""
from __future__ import annotations

from pathlib import Path

from openlama.config import get_config, DEFAULT_SYSTEM_PROMPT
from openlama.tools.registry import get_all_tools
from openlama.core.skills import build_skills_section
from openlama.logger import get_logger

logger = get_logger("prompt")


def _prompts_dir() -> Path:
    return Path(get_config("prompts_dir"))


def _read_prompt(name: str) -> str:
    p = _prompts_dir() / name
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    return ""


def _has_real_content(path: Path) -> bool:
    """Check if file exists and has meaningful content (not just a header)."""
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8").strip()
    # Remove markdown header lines
    lines = [l.strip() for l in text.split("\n") if l.strip() and not l.strip().startswith("#")]
    # Need at least 10 chars of real content
    content = " ".join(lines)
    return len(content) >= 10


def is_profile_setup_done() -> bool:
    """Check if USERS.md and SOUL.md exist with meaningful content."""
    d = _prompts_dir()
    return _has_real_content(d / "USERS.md") and _has_real_content(d / "SOUL.md")


def save_prompt_file(name: str, content: str):
    d = _prompts_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(content, encoding="utf-8")
    logger.info("saved prompt: %s (%d chars)", name, len(content))


def _build_tool_section() -> str:
    """Build the tools section with all registered tools + MCP tools."""
    tools = get_all_tools()
    lines = []
    for t in tools:
        lines.append(f"- {t.name}: {t.description[:80]}")

    # MCP server tools
    try:
        from openlama.core.mcp_client import get_all_mcp_tools
        mcp_tools = get_all_mcp_tools()
        if mcp_tools:
            lines.append("")
            lines.append("### MCP Tools (external)")
            for t in mcp_tools:
                lines.append(f"- mcp_{t['server']}_{t['name']}: {t['description'][:60]}")
    except Exception:
        pass

    return "\n".join(lines)


def _build_cron_section() -> str:
    """Build cron jobs section showing active scheduled tasks."""
    try:
        from openlama.database import list_cron_jobs
        jobs = list_cron_jobs(enabled_only=True)
        if not jobs:
            return ""

        lines = ["## Active Scheduled Tasks"]
        for j in jobs:
            lines.append(f"- #{j['id']}: `{j['cron_expr']}` — {j['task'][:60]}")
        return "\n".join(lines)
    except Exception:
        return ""


def generate_system_prompt() -> str:
    """Build SYSTEM.md from templates + current tools, skills, MCP, cron."""
    tool_section = _build_tool_section()
    skills_section = build_skills_section()
    cron_section = _build_cron_section()

    system = f"""# System Prompt

## Reference Files
- Agent identity: SOUL.md
- User information: USERS.md
- Long-term memory: MEMORY.md

## Operating Rules
1. Always maintain the identity defined in SOUL.md.
2. Provide personalized responses based on user information in USERS.md.
3. Actively use tools to fulfill user requests.

## Available Tools
{tool_section}

## Tool Usage Rules
- You MUST use tools when the user's request matches a tool's capability. Never answer from memory alone for real-time, current, or factual questions.
- Use tools directly without unnecessary pre-checks.
- Use multiple tools sequentially to fulfill user requests.
- The user may speak any language. Always interpret the user's intent regardless of language and call the correct tool.
- Tool parameters must be in the format the tool expects (usually English for technical parameters).
- image_generate/image_edit: ComfyUI auto-starts/stops. Translate non-English prompts to detailed English.
- cron_manager: Convert natural language schedules to cron expressions before calling.
- skill_creator: Use when user asks to create, edit, or manage custom skills.
- mcp_manager: Use when user asks to install or manage external tool servers.

### Tool Trigger Examples (any language → tool call)
- "search for X" / "X 검색해줘" / "X를 찾아줘" → web_search
- "what time is it" / "지금 몇시야" → get_datetime
- "calculate X" / "X 계산해줘" → calculator
- "run this code" / "코드 실행해줘" → code_execute
- "check server status" / "서버 상태 확인해줘" → shell_command
- "remember this" / "이거 기억해" → memory
- "create a skill" / "스킬 만들어줘" → skill_creator
- "schedule X every day" / "매일 X 작업 등록해줘" → cron_manager
- "generate an image" / "그림 그려줘" → image_generate
- "read file X" / "X 파일 읽어줘" → file_read

## Scheduled Tasks (cron_manager)
When user asks to schedule a recurring task:
1. Convert the schedule to a cron expression:
   - "every day at 10:00" → `0 10 * * *`
   - "every 10 minutes" → `*/10 * * * *`
   - "weekdays at 9am" → `0 9 * * 1-5`
   - "every 2 hours" → `0 */2 * * *`
   - "every Monday at 8:30" → `30 8 * * 1`
2. Call cron_manager with action "create", the cron_expr, and a clear task description.
3. The task will run automatically and send results to the current chat.

## Long-term Memory (memory)
Save to memory when:
1. User says "remember this", "save to memory", etc.
2. Important user preference discovered.
3. Key project decision made.
Format: concise single line, date auto-included, max 50 items.

## Skill System (skill_creator)
- Skills are custom instruction sets that activate on trigger keywords.
- Use skill_creator to create/list/update/delete skills.
- When a skill triggers, its instructions are injected into this prompt.

## Context Management
- Context auto-compresses at 70% of max capacity.
- Save important info with memory tool before compression.
"""

    if skills_section:
        system += f"\n{skills_section}\n"

    if cron_section:
        system += f"\n{cron_section}\n"

    return system


def build_full_system_prompt() -> str:
    """Assemble all prompt files into one system prompt."""
    parts = []

    # Always regenerate SYSTEM.md to include latest tools and skills
    system = generate_system_prompt()
    parts.append(system)

    # SOUL.md
    soul = _read_prompt("SOUL.md")
    if soul:
        parts.append(f"\n{soul}")

    # USERS.md
    users = _read_prompt("USERS.md")
    if users:
        parts.append(f"\n{users}")

    # MEMORY.md
    memory = _read_prompt("MEMORY.md")
    if memory:
        parts.append(f"\n{memory}")

    if not parts:
        return DEFAULT_SYSTEM_PROMPT

    return "\n".join(parts)
