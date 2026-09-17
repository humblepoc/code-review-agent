"""Flavor base class — bundles a system prompt + tool set.

A *flavor* is an agent definition. In this framework a flavor is expressed
declaratively as a directory under ``agent/agents/<name>/`` containing:

    instructions.md   -> becomes the system prompt
    tools/*.py        -> each module contributes one or more Tool subclasses

The :class:`MarkdownFlavor` loader (see ``flavors.loader``) reads that
directory, so creating a new agent needs no framework code changes — just
drop in the folder.

The abstract base is kept so advanced agents can still build a flavor in
pure Python if they want full control.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from agent.config import AgentConfig
from agent.tools.base import Tool


class Flavor(ABC):
    """A flavor specializes the agent for a particular domain."""

    @abstractmethod
    def system_prompt(self, config: AgentConfig) -> str:
        """Return the system prompt for this flavor."""
        ...

    @abstractmethod
    def tools(self, config: AgentConfig) -> list[Tool]:
        """Return the tools available in this flavor."""
        ...

    def builtin_tool_names(self, config: AgentConfig) -> list[str]:
        """Names of framework built-in tools this flavor opts into.

        Default is none: built-ins are opt-in, so no agent gets a shell (or
        other powerful built-in) unless it explicitly asks.
        """
        return []
