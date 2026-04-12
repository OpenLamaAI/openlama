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
class ToolResult:
    """Structured tool execution result with success/error tracking."""
    success: bool
    data: str
    error: str = ""
    metadata: dict = field(default_factory=dict)

    def to_message(self) -> str:
        """Convert to message string for LLM context."""
        if self.success:
            return self.data
        return f"[ERROR] {self.error}\n{self.data}" if self.data else f"[ERROR] {self.error}"

    def __str__(self) -> str:
        """String compatibility — existing code using str(result) still works."""
        return self.to_message()


@dataclass
class ChatResponse:
    content: str = ""
    thinking: str = ""
    images: list[str] = field(default_factory=list)
    tool_calls_log: list[dict] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=TokenUsage)
    context_bar: str = ""
