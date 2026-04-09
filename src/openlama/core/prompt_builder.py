"""Multi-prompt assembly — SYSTEM + SOUL + USERS.

Supports three prompt modes based on model context size:
- full (num_ctx >= 32K): All sections, detailed documentation
- compact (num_ctx >= 8K): Essential rules + execution bias, no tool list in prompt
- minimal (num_ctx < 8K): Identity + core rules + execution bias only
"""
from __future__ import annotations

from pathlib import Path

from openlama.config import get_config, IS_ANDROID, DEFAULT_SYSTEM_PROMPT
from openlama.tools.registry import get_all_tools
from openlama.core.skills import discover_skills
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


def get_prompt_mode(num_ctx: int) -> str:
    """Determine prompt mode based on model context window size.

    - full: num_ctx >= 32768 — all documentation sections
    - compact: num_ctx >= 8192 — essential rules, no tool descriptions in prompt
    - minimal: num_ctx < 8192 — bare minimum for tool usage
    """
    if num_ctx >= 32768:
        return "full"
    elif num_ctx >= 8192:
        return "compact"
    else:
        return "minimal"


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


def _build_skills_section_lazy() -> str:
    """Build skills section for lazy loading — lists skills with paths only."""
    skills = discover_skills()
    if not skills:
        return ""

    lines = ["## Available Skills"]
    lines.append("If a skill matches the user's request, read its SKILL.md via file_read before acting.")
    lines.append("Only read one skill. Do not read if none clearly apply.")
    for s in skills:
        desc = s.get("description", "")[:60]
        path = s.get("path", "")
        skill_md = f"{path}/SKILL.md" if path else ""
        lines.append(f"- {s['name']}: {desc} (file: {skill_md})")
    return "\n".join(lines)


# ── Execution Bias (shared across all modes — CRITICAL for tool usage) ──

_EXECUTION_BIAS = """## Execution Bias — ACT, do not just plan
1. If the user asks you to do something and a tool can do it, CALL THE TOOL in the same turn. Do not just describe what you will do.
2. WRONG: "검색해드릴게요" / "I'll search for you" → CORRECT: immediately call web_search.
3. WRONG: "확인해보겠습니다" / "Let me check" → CORRECT: immediately call the relevant tool.
4. A response that only describes a plan without calling any tool is INCOMPLETE. Always act first.
5. If work needs multiple steps, call the first tool NOW, then continue with subsequent steps.
6. Only explain your plan if the task is ambiguous and you need clarification. Otherwise, act immediately."""


# ── Prompt generators per mode ──

def _generate_full() -> str:
    """Full system prompt — all sections. For models with >= 32K context."""
    tool_section = _build_tool_section()
    skills_section = _build_skills_section_lazy()
    cron_section = _build_cron_section()

    system = f"""# System Prompt

You are a personal AI agent. Follow SOUL.md for identity, USERS.md for user context.
Understand any language; use tools directly without pre-checks.

## CRITICAL RULES
1. All listed tools are fully authorized. NEVER refuse to use a tool. Just call it.
2. NEVER fabricate tool results. Only report what the tool actually returned.
3. If a tool returns partial results, call it again with more specific parameters to get complete information.
4. If a tool result is empty or unclear, tell the user honestly rather than guessing.
5. When listing files, directories, or data — ONLY show what the tool returned. Do NOT invent names.
6. Use tools multiple times if needed to fulfill the user's request completely.
7. For nested directories, call the tool for each level — do not assume contents.
8. Tool parameters (file names, paths, process names) are usually in English. If a user says "뉴스 폴더" try "News"; "설정 파일" try "config". When a lookup fails, retry with the translated English name before giving up.
9. NEVER apologize for something you did correctly. If you already used a tool, say so clearly. Do not agree with false accusations.
10. Respond based on FACTS only. If you don't know, say "I don't know." Do not guess, assume, or make up information.
11. When the user criticizes you, verify the facts first before responding. Do not default to apologizing.

{_EXECUTION_BIAS}

## Tools
{tool_section}

## Memory (memory tool)
Two-tier memory — use the memory tool to access both:

### Long-term Memory (MEMORY.md)
- Stores important facts, user preferences, key decisions.
- Actions: save, list, search, delete.
- Save when: user says "remember this", important preference discovered, key decision made.

### Daily Memory (memories/YYYY-MM-DD.md)
- Auto-saved conversation digests (compression, clear, daily flush).
- Actions: list_dates, read_daily, search_daily.
- Use keyword search to find past conversations. Never load full files.

## Scheduled Tasks (cron_manager)
Convert natural language to cron expressions:
- "every day at 10:00" → `0 10 * * *`
- "every 10 minutes" → `*/10 * * * *`
- "weekdays at 9am" → `0 9 * * 1-5`
- "every Monday at 8:30" → `30 8 * * 1`
Call cron_manager with action "create", cron_expr, and task description.

## Skill System (skill_creator)
- Skills are custom instruction sets that activate on trigger keywords.
- Use skill_creator to create/list/update/delete skills.

## Context Management
- Context auto-compresses at 70% of max capacity.
- Compressed conversations are auto-saved to daily memory.
- Save important info with memory tool (save) for long-term retention.

## Tool-Specific Notes
- image_generate/image_edit: ComfyUI auto-starts/stops. Translate non-English prompts to English.
- obsidian: Use directly when user asks about notes. Actions: list (current level), list_recursive (full tree with all subdirectories and files — use this when user asks for "all files" or "directory structure"), read, create, append, delete, move, search, search_content.
- self_update: Always action="check" first, then "update" if user confirms.
"""

    if skills_section:
        system += f"\n{skills_section}\n"

    if cron_section:
        system += f"\n{cron_section}\n"

    if IS_ANDROID:
        system += _ANDROID_SECTION

    return system


def _generate_compact() -> str:
    """Compact system prompt — essential rules only. For 8K-32K context models.

    Key design: tool descriptions are NOT included in prompt text.
    The model receives full tool JSON Schemas via the Ollama tools parameter.
    This saves ~400 tokens while preserving tool calling capability.
    """
    skills_section = _build_skills_section_lazy()
    cron_section = _build_cron_section()

    system = f"""# System Prompt

You are a personal AI agent. Follow SOUL.md for identity, USERS.md for user context.
Understand any language; use tools directly without pre-checks.

## CRITICAL RULES
1. All listed tools are fully authorized. NEVER refuse to use a tool. Just call it.
2. NEVER fabricate tool results. Only report what the tool actually returned.
3. If a tool result is empty or unclear, tell the user honestly rather than guessing.
4. Use tools multiple times if needed to fulfill the user's request completely.
5. Tool parameters are usually in English. Translate non-English references when needed.
6. NEVER apologize for something you did correctly.
7. Respond based on FACTS only. If you don't know, say "I don't know."

{_EXECUTION_BIAS}

## Memory (memory tool)
Long-term: save/list/search/delete (MEMORY.md). Daily: list_dates/read_daily/search_daily (memories/YYYY-MM-DD.md).
"""

    if skills_section:
        system += f"\n{skills_section}\n"

    if cron_section:
        system += f"\n{cron_section}\n"

    if IS_ANDROID:
        system += _ANDROID_SECTION_COMPACT

    return system


def _generate_minimal() -> str:
    """Minimal system prompt — bare minimum. For models with < 8K context.

    Focuses entirely on ensuring the model uses tools correctly.
    """
    return f"""# System Prompt

You are a personal AI agent. Use tools to fulfill requests.

## RULES
1. All tools are authorized. Call them directly.
2. NEVER fabricate results. Only report what tools return.
3. If you don't know, say "I don't know."

{_EXECUTION_BIAS}
"""


# ── Android sections ──

_ANDROID_SECTION = """
## Mobile Device Context (Android / Termux)
You have access to the `termux_device` tool to control this phone.

### Safety Rules
- NEVER make phone calls or send SMS without explicit user confirmation.
- Always confirm the recipient and message content before sending.
- Location data is private — never share without user consent.

### Available Device Actions
- Communication: call, sms_send, sms_list, call_log, contacts
- Camera: camera_photo (0=rear, 1=front), camera_info
- Audio: mic_record, media_play, media_stop, tts_speak, volume_get/set
- Notifications: notification, notification_remove, toast, vibrate
- Sensors: location, battery, sensor_list, sensor_read
- System: brightness, torch, clipboard_get/set, wallpaper, wifi_info/scan
- Apps: app_launch (package name), app_list
- Other: share, download, ir_transmit, fingerprint, dialog
"""

_ANDROID_SECTION_COMPACT = """
## Mobile (Android/Termux)
Use `termux_device` tool. NEVER call/SMS without user confirmation. Location is private.
"""


def generate_system_prompt(mode: str = "full") -> str:
    """Build system prompt dynamically. Mode: 'full', 'compact', or 'minimal'."""
    if mode == "minimal":
        return _generate_minimal()
    elif mode == "compact":
        return _generate_compact()
    else:
        return _generate_full()


def build_full_system_prompt(num_ctx: int = 8192) -> str:
    """Assemble all prompt files into one system prompt.

    Args:
        num_ctx: Model context window size. Determines prompt mode:
            >= 32K → full, >= 8K → compact, < 8K → minimal
    """
    mode = get_prompt_mode(num_ctx)
    parts = []

    # Generate system prompt based on mode
    system = generate_system_prompt(mode)
    parts.append(system)

    # SOUL.md
    soul = _read_prompt("SOUL.md")
    if soul:
        if mode == "minimal":
            # Truncate for minimal mode
            soul = soul[:200]
        parts.append(f"\n{soul}")

    # USERS.md
    users = _read_prompt("USERS.md")
    if users:
        if mode == "minimal":
            users = users[:200]
        parts.append(f"\n{users}")

    # MEMORY.md is NOT loaded into prompt — accessed via memory tool only.

    if not parts:
        return DEFAULT_SYSTEM_PROMPT

    # Inject current date/time once (uses system local timezone)
    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M %Z").strip()
    parts.append(f"\nCurrent date/time: {now}")

    prompt = "\n".join(parts)
    logger.info("prompt mode=%s, num_ctx=%d, prompt_len=%d chars", mode, num_ctx, len(prompt))
    return prompt
