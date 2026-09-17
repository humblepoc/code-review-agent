"""Agent setup helpers — shared by the Lambda entry point and tests.

Headless-only: no console/terminal dependencies, so it runs cleanly in
Lambda. Wiring is fully generic — the selected flavor (``cfg.flavor``) is
loaded from its agent directory, contributing the system prompt and tools.

Built-in tools are OPT-IN. An agent gets a built-in only if it lists the name
in a ``builtins.txt`` in its directory. This keeps powerful built-ins (like the
shell ``bash`` tool) off webhook-triggered agents that ingest untrusted content
unless explicitly requested.
"""

from __future__ import annotations

import logging

from agent.config import AgentConfig
from agent.flavors.base import Flavor
from agent.flavors.loader import load_flavor
from agent.tools.base import Tool, ToolRegistry
from agent.tools.bash import BashTool

log = logging.getLogger(__name__)

# Map of built-in tool name -> factory. Nothing here is registered unless a
# flavor opts in via builtin_tool_names().
_BUILTIN_TOOLS: dict[str, type[Tool]] = {
    "bash": BashTool,
}


def get_flavor(cfg: AgentConfig) -> Flavor:
    """Load the flavor named by ``cfg.flavor``."""
    return load_flavor(cfg.flavor)


def build_registry(cfg: AgentConfig, flavor: Flavor | None = None) -> ToolRegistry:
    """Build the tool registry: the flavor's tools + any opted-in built-ins."""
    registry = ToolRegistry()
    flavor = flavor or get_flavor(cfg)

    # Opt-in built-ins first (so an agent tool of the same name would win).
    for name in flavor.builtin_tool_names(cfg):
        factory = _BUILTIN_TOOLS.get(name)
        if factory is None:
            log.warning("Agent '%s' requested unknown built-in tool '%s'", cfg.flavor, name)
            continue
        registry.register(factory())

    for tool in flavor.tools(cfg):
        registry.register(tool)

    return registry


def get_system_prompt(cfg: AgentConfig, flavor: Flavor | None = None) -> str:
    """Return the system prompt for the configured flavor."""
    flavor = flavor or get_flavor(cfg)
    prompt = flavor.system_prompt(cfg)
    if prompt:
        return prompt
    return "You are a helpful assistant with access to tools. Use them to help the user."
