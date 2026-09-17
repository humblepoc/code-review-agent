"""Declarative flavor loader.

Turns an agent directory into a :class:`Flavor` without any framework code
changes. To add a new agent, create::

    agent/agents/<name>/
        instructions.md      # the system prompt
        tools/
            __init__.py
            my_tool.py        # defines one or more Tool subclasses

``load_flavor("<name>")`` then:
  1. reads ``instructions.md`` as the system prompt, and
  2. imports every module under ``tools/`` and collects each concrete
     :class:`~agent.tools.base.Tool` subclass it finds, instantiating them.

Tool classes may declare ``__init__(self)`` or ``__init__(self, config)``.
If the constructor accepts a parameter, the loaded :class:`AgentConfig` is
passed so tools can read ``config.extra`` for their settings.
"""
from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from pathlib import Path
from typing import Any

from agent.config import AgentConfig
from agent.flavors.base import Flavor
from agent.tools.base import Tool

log = logging.getLogger(__name__)

# Package that holds the agent definitions (each a subpackage).
AGENTS_PACKAGE = "agent.agents"


def _agents_root() -> Path:
    return Path(__file__).resolve().parent.parent / "agents"


class MarkdownFlavor(Flavor):
    """A flavor loaded from an agent directory (instructions.md + tools/)."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._dir = _agents_root() / name
        if not self._dir.is_dir():
            raise FileNotFoundError(
                f"Agent '{name}' not found. Expected directory: {self._dir}"
            )

    def system_prompt(self, config: AgentConfig) -> str:
        md = self._dir / "instructions.md"
        if not md.exists():
            log.warning("No instructions.md for agent '%s'; using empty prompt", self.name)
            return ""
        return md.read_text(encoding="utf-8").strip()

    def tools(self, config: AgentConfig) -> list[Tool]:
        return _discover_tools(self.name, config)

    def builtin_tool_names(self, config: AgentConfig) -> list[str]:
        """Built-in tools this agent opts into.

        Built-ins (e.g. ``bash``) are OFF by default — a webhook-triggered
        agent that ingests untrusted content should not get a shell unless it
        explicitly asks for one. To opt in, add a ``builtins.txt`` in the agent
        directory listing one built-in tool name per line.
        """
        f = self._dir / "builtins.txt"
        if not f.exists():
            return []
        names = []
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                names.append(line)
        return names


def _discover_tools(agent_name: str, config: AgentConfig) -> list[Tool]:
    """Import every module under ``agents/<name>/tools`` and instantiate
    each concrete Tool subclass found."""
    pkg_name = f"{AGENTS_PACKAGE}.{agent_name}.tools"
    try:
        pkg = importlib.import_module(pkg_name)
    except ModuleNotFoundError:
        log.info("Agent '%s' has no tools package (%s)", agent_name, pkg_name)
        return []

    tools: list[Tool] = []
    seen: set[type] = set()

    pkg_path = getattr(pkg, "__path__", [])
    for mod_info in pkgutil.iter_modules(pkg_path):
        if mod_info.name.startswith("_"):
            continue
        mod = importlib.import_module(f"{pkg_name}.{mod_info.name}")
        for _, obj in inspect.getmembers(mod, inspect.isclass):
            if not issubclass(obj, Tool) or obj is Tool:
                continue
            if inspect.isabstract(obj):
                continue
            # Only pick up classes defined in this module (not imports).
            if obj.__module__ != mod.__name__:
                continue
            if obj in seen:
                continue
            seen.add(obj)
            instance = _instantiate(obj, config)
            if instance is not None:
                tools.append(instance)

    log.info("Agent '%s': discovered %d tool(s)", agent_name, len(tools))
    return tools


def _instantiate(tool_cls: type, config: AgentConfig) -> Tool | None:
    """Instantiate a Tool subclass, passing config if its __init__ accepts it."""
    try:
        sig = inspect.signature(tool_cls.__init__)
        # params minus 'self'
        params = [p for name, p in sig.parameters.items() if name != "self"]
        takes_arg = any(
            p.kind in (p.POSITIONAL_OR_KEYWORD, p.POSITIONAL_ONLY, p.KEYWORD_ONLY)
            for p in params
        )
        if takes_arg:
            return tool_cls(config)  # type: ignore[call-arg]
        return tool_cls()  # type: ignore[call-arg]
    except Exception:
        log.exception("Failed to instantiate tool %s", getattr(tool_cls, "__name__", tool_cls))
        return None


def load_flavor(name: str) -> Flavor:
    """Load a flavor by agent name."""
    return MarkdownFlavor(name)


def list_agents() -> list[str]:
    """List available agent names (subdirectories under agents/)."""
    root = _agents_root()
    if not root.is_dir():
        return []
    return sorted(
        p.name for p in root.iterdir()
        if p.is_dir() and not p.name.startswith("_") and not p.name.startswith(".")
    )
