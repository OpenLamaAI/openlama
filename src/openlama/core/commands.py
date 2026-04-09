"""Shared command registry — channel-independent commands for CLI, Telegram, and future channels."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Awaitable, Optional


@dataclass
class Command:
    name: str
    description: str
    category: str  # "chat", "model", "settings", "system", "admin"
    handler: Optional[Callable] = None  # async fn(uid, args) -> str


# Master command list — single source of truth for all channels
COMMANDS: list[dict] = [
    # Chat
    {"name": "help", "description": "Show available commands", "category": "chat"},
    {"name": "clear", "description": "Clear conversation context", "category": "chat"},
    {"name": "status", "description": "Show session and context info", "category": "chat"},
    {"name": "export", "description": "Export conversation history", "category": "chat"},
    {"name": "profile", "description": "Redo profile setup", "category": "chat"},

    {"name": "compress", "description": "Compress conversation context", "category": "chat"},
    {"name": "session", "description": "View or extend session", "category": "chat"},

    # Model
    {"name": "model", "description": "Show or change current model", "category": "model"},
    {"name": "models", "description": "List available models", "category": "model"},
    {"name": "pull", "description": "Download a new model", "category": "model"},
    {"name": "rm", "description": "Delete a model", "category": "model"},

    # Settings
    {"name": "settings", "description": "Interactive model settings", "category": "settings"},
    {"name": "set", "description": "Set a model parameter", "category": "settings"},
    {"name": "systemprompt", "description": "View or edit system prompt", "category": "settings"},
    {"name": "think", "description": "Toggle think/reasoning mode", "category": "settings"},

    # System
    {"name": "ollama", "description": "Ollama server management", "category": "system"},
    {"name": "skills", "description": "List installed skills", "category": "system"},
    {"name": "tools", "description": "List registered tools", "category": "system"},
    {"name": "mcp", "description": "MCP server status", "category": "system"},
    {"name": "cron", "description": "View and manage scheduled tasks", "category": "system"},

    # Session
    {"name": "login", "description": "Authenticate with password", "category": "admin"},
    {"name": "logout", "description": "Log out and clear session", "category": "admin"},
    {"name": "setpassword", "description": "Change admin password", "category": "admin"},
    {"name": "quit", "description": "Exit chat (CLI only)", "category": "chat"},
]


def get_commands_by_category() -> dict[str, list[dict]]:
    """Group commands by category."""
    groups: dict[str, list[dict]] = {}
    for cmd in COMMANDS:
        cat = cmd["category"]
        if cat not in groups:
            groups[cat] = []
        groups[cat].append(cmd)
    return groups


def get_all_command_names() -> list[str]:
    return [c["name"] for c in COMMANDS]


def find_command(name: str) -> Optional[dict]:
    for c in COMMANDS:
        if c["name"] == name:
            return c
    return None


def format_help_text(exclude: list[str] | None = None) -> str:
    """Format help text for display. exclude: command names to hide."""
    exclude = exclude or []
    groups = get_commands_by_category()

    category_labels = {
        "chat": "Chat",
        "model": "Model",
        "settings": "Settings",
        "system": "System",
        "admin": "Account",
    }

    lines = []
    for cat in ["chat", "model", "settings", "system", "admin"]:
        cmds = groups.get(cat, [])
        cmds = [c for c in cmds if c["name"] not in exclude]
        if not cmds:
            continue
        lines.append(f"\n  {category_labels.get(cat, cat)}:")
        for c in cmds:
            lines.append(f"    /{c['name']:16s} {c['description']}")

    return "\n".join(lines)
