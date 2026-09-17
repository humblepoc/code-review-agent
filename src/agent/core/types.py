"""Universal message types for the agent framework.

All LLM providers translate to/from these types. The agent loop
only works with these — never provider-specific formats.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Role(Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class ToolCall:
    """A tool invocation requested by the LLM."""

    name: str
    arguments: dict[str, Any]
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


@dataclass
class ToolResult:
    """The result of executing a tool."""

    tool_call_id: str
    name: str
    content: str
    is_error: bool = False


@dataclass
class Message:
    """A single message in the conversation."""

    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)


@dataclass
class LLMResponse:
    """Response from an LLM provider."""

    message: Message
    stop_reason: str = "end_turn"  # "end_turn" | "tool_use" | "max_tokens"
    usage: dict[str, int] = field(default_factory=dict)
