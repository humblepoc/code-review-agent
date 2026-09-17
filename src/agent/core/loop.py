"""ReAct agent loop: Think -> Act -> Observe -> Evaluate."""

from __future__ import annotations

import logging
import time
from typing import Any

from agent.core.context import ConversationContext
from agent.core.types import LLMResponse, Message, Role, ToolResult
from agent.llm.base import LLMProvider
from agent.tools.base import ToolRegistry

log = logging.getLogger(__name__)

DEFAULT_MAX_ITERATIONS = 25

# Cap tool-error text fed back into the model context so a large upstream
# error body (e.g. an HTML 500 page) can't blow the context budget.
MAX_TOOL_ERROR_CHARS = 600


def _cap(text: str, limit: int = MAX_TOOL_ERROR_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [error truncated, {len(text) - limit} chars]"


async def run_agent(
    provider: LLMProvider,
    registry: ToolRegistry,
    context: ConversationContext,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
) -> Message:
    """Run the agent loop until the LLM produces a final answer or hits max iterations.

    Returns the final assistant message.
    """
    schemas = registry.schemas()

    total_llm_seconds = 0.0

    for iteration in range(1, max_iterations + 1):
        log.info("--- Iteration %d/%d ---", iteration, max_iterations)

        # Think: send context to LLM (timed — open-source models can be slow)
        _t0 = time.monotonic()
        response: LLMResponse = await provider.chat(
            messages=context.messages,
            tools=schemas if schemas else None,
            system=context.system_prompt or None,
        )
        _elapsed = time.monotonic() - _t0
        total_llm_seconds += _elapsed
        _usage = response.usage or {}
        log.info(
            "LLM response in %.1fs (in=%s out=%s tokens) | cumulative LLM time %.1fs",
            _elapsed,
            _usage.get("input_tokens", "?"),
            _usage.get("output_tokens", "?"),
            total_llm_seconds,
        )
        assistant_msg = response.message
        context.add(assistant_msg)

        if assistant_msg.content:
            log.info("Assistant: %s", assistant_msg.content[:200])

        # If no tool calls, we're done
        if not assistant_msg.tool_calls:
            log.info(
                "Agent finished (stop_reason=%s) | total LLM time %.1fs over %d iteration(s)",
                response.stop_reason, total_llm_seconds, iteration,
            )
            return assistant_msg

        # Act: execute each tool call
        results: list[ToolResult] = []
        for tc in assistant_msg.tool_calls:
            log.info("Tool call: %s(%s)", tc.name, _summarize_args(tc.arguments))
            result = await _execute_tool(registry, tc.name, tc.arguments, tc.id)
            results.append(result)
            log.info("Tool result: %s", result.content[:200] if result.content else "(empty)")

        # Observe: add results to context
        tool_msg = Message(role=Role.TOOL, tool_results=results)
        context.add(tool_msg)

    # Max iterations reached
    log.warning(
        "Max iterations (%d) reached | total LLM time %.1fs", max_iterations, total_llm_seconds
    )
    return Message(
        role=Role.ASSISTANT,
        content="I've reached the maximum number of iterations. Here's what I found so far based on my investigation.",
    )


async def _execute_tool(
    registry: ToolRegistry,
    name: str,
    arguments: dict[str, Any],
    tool_call_id: str,
) -> ToolResult:
    """Execute a single tool call and return the result."""
    tool = registry.get(name)
    if tool is None:
        return ToolResult(
            tool_call_id=tool_call_id,
            name=name,
            content=f"Unknown tool: {name}",
            is_error=True,
        )

    # Enforce the tool's own schema before dispatch: fill optional defaults,
    # coerce simple types, and reject calls missing required args with a clear,
    # corrective message (instead of letting the tool raise KeyError/ValueError).
    coerced, errors = tool.schema().validate_and_coerce(arguments)
    if errors:
        return ToolResult(
            tool_call_id=tool_call_id,
            name=name,
            content=(
                f"Invalid call to {name}: " + "; ".join(errors) + ". "
                "Fix the arguments and call the tool again."
            ),
            is_error=True,
        )

    try:
        output = await tool.execute(**coerced)
        return ToolResult(
            tool_call_id=tool_call_id,
            name=name,
            content=output,
        )
    except Exception as e:
        log.exception("Tool %s failed", name)
        return ToolResult(
            tool_call_id=tool_call_id,
            name=name,
            content=_cap(f"Error executing {name}: {type(e).__name__}: {e}"),
            is_error=True,
        )


def _summarize_args(args: dict[str, Any]) -> str:
    """Short summary of tool arguments for logging."""
    parts = []
    for k, v in args.items():
        s = str(v)
        if len(s) > 80:
            s = s[:77] + "..."
        parts.append(f"{k}={s}")
    return ", ".join(parts)
