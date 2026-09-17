"""Abstract LLM provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from agent.core.types import LLMResponse, Message
from agent.tools.schema import ToolSchema


class LLMProvider(ABC):
    """Base class for all LLM providers.

    Each provider translates between the universal Message format
    and the provider's specific API format.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier (e.g. 'anthropic', 'openai')."""
        ...

    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        system: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Send messages to the LLM and get a response."""
        ...
