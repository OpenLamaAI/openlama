"""Core types for openlama."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class ChatRequest:
    user_id: int
    text: str
    images: list[bytes] = field(default_factory=list)
    channel: str = "telegram"


@dataclass
class ChatResponse:
    content: str = ""
    thinking: str = ""
    images: list[str] = field(default_factory=list)
    tool_calls_log: list[dict] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=TokenUsage)
    context_bar: str = ""
