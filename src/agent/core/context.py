"""Conversation context management."""

from __future__ import annotations

import logging

from agent.core.types import Message, Role

log = logging.getLogger(__name__)

# Rough estimate: 1 token ~ 4 chars
CHARS_PER_TOKEN = 4


class ConversationContext:
    """Manages the conversation message list and system prompt."""

    def __init__(self, system_prompt: str = "", max_tokens: int = 180_000) -> None:
        self.system_prompt = system_prompt
        self.max_tokens = max_tokens
        self._messages: list[Message] = []

    @property
    def messages(self) -> list[Message]:
        return list(self._messages)

    def add(self, message: Message) -> None:
        self._messages.append(message)
        self._maybe_truncate()

    def clear(self) -> None:
        self._messages.clear()

    def estimate_tokens(self) -> int:
        total_chars = len(self.system_prompt)
        for msg in self._messages:
            total_chars += len(msg.content)
            for tc in msg.tool_calls:
                total_chars += len(str(tc.arguments)) + len(tc.name)
            for tr in msg.tool_results:
                total_chars += len(tr.content) + len(tr.name)
        return total_chars // CHARS_PER_TOKEN

    def _maybe_truncate(self) -> None:
        """Truncate old tool results when approaching context limit."""
        while self.estimate_tokens() > self.max_tokens and len(self._messages) > 2:
            # Find oldest tool message and truncate its content
            for i, msg in enumerate(self._messages):
                if msg.role == Role.TOOL and msg.tool_results:
                    for tr in msg.tool_results:
                        if len(tr.content) > 500:
                            tr.content = tr.content[:200] + "\n[...truncated...]"
                            log.debug("Truncated tool result at message %d", i)
                            return
            # If no tool results to truncate, remove oldest non-user message
            for i, msg in enumerate(self._messages):
                if msg.role not in (Role.USER, Role.SYSTEM):
                    self._messages.pop(i)
                    log.debug("Dropped message %d to fit context", i)
                    return
            break
