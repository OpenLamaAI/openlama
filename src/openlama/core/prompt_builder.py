"""Multi-prompt assembly — SYSTEM + SOUL + USERS."""
from __future__ import annotations

from pathlib import Path

from openlama.config import get_config, IS_ANDROID, DEFAULT_SYSTEM_PROMPT
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
    """Build system prompt dynamically from current tools, skills, MCP, cron."""
    tool_section = _build_tool_section()
    skills_section = build_skills_section()
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

## Tools
{tool_section}

## Tool Triggers (any language → tool call)
- "search X" / "X 검색해줘" → web_search
- "what time" / "몇시야" → get_datetime
- "calculate X" / "X 계산해줘" → calculator
- "run code" / "코드 실행" → code_execute
- "server status" / "서버 상태" → shell_command
- "fetch URL" / "URL 내용" → url_fetch
- "read file" / "파일 읽어" → file_read
- "write file" / "파일 저장" → file_write
- "remember this" / "기억해" → memory (save)
- "yesterday's talk" / "어제 얘기" → memory (search_daily)
- "create skill" / "스킬 만들어" → skill_creator
- "schedule X daily" / "매일 X 등록" → cron_manager (convert to cron expr)
- "generate image" / "그림 그려" → image_generate (translate prompt to English)
- "edit image" / "이미지 수정" → image_edit
- "tmux session" / "tmux 세션" → tmux
- "update bot" / "업데이트" → self_update (check first, then update)
- "transcribe audio" / "음성 변환" → whisper
- "git status" / "깃 상태" → git
- "check processes" / "프로세스 확인" → process_manager
- "list notes" / "노트 목록" → obsidian
- "install MCP" / "MCP 설치" → mcp_manager

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
        system += """
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

### Trigger Examples
- "배터리 얼마야" / "check battery" → termux_device(action="battery")
- "엄마한테 문자 보내" / "text mom" → confirm first, then termux_device(action="sms_send")
- "사진 찍어" / "take a photo" → termux_device(action="camera_photo")
- "지금 어디야" / "where am I" → termux_device(action="location")
- "플래시 켜" / "turn on flashlight" → termux_device(action="torch", torch_enabled=true)
- "볼륨 올려" / "volume up" → termux_device(action="volume_set")
"""

    return system


def build_full_system_prompt() -> str:
    """Assemble all prompt files into one system prompt."""
    parts = []

    # Always regenerate system prompt to include latest tools and skills
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

    # MEMORY.md is NOT loaded into prompt — accessed via memory tool only.

    if not parts:
        return DEFAULT_SYSTEM_PROMPT

    return "\n".join(parts)
