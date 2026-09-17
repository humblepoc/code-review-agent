"""Tool base class and registry."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from agent.tools.schema import ToolSchema

log = logging.getLogger(__name__)


class Tool(ABC):
    """Abstract base class for all tools."""

    @abstractmethod
    def schema(self) -> ToolSchema:
        """Return the tool's schema."""
        ...

    @abstractmethod
    async def execute(self, **kwargs: Any) -> str:
        """Execute the tool and return a string result."""
        ...

    @property
    def name(self) -> str:
        return self.schema().name


class ToolRegistry:
    """Registry for available tools."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool
        log.debug("Registered tool: %s", tool.name)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list(self) -> list[Tool]:
        return list(self._tools.values())

    def schemas(self) -> list[ToolSchema]:
        return [t.schema() for t in self._tools.values()]
