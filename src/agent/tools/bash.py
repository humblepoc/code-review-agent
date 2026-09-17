"""Shell execution tool — a generic built-in available to every agent."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from agent.tools.base import Tool
from agent.tools.schema import ToolParameter, ToolSchema

log = logging.getLogger(__name__)

MAX_OUTPUT_CHARS = 10_000
DEFAULT_TIMEOUT = 120


class BashTool(Tool):
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="bash",
            description=(
                "Execute a shell command and return its output (stdout + stderr). "
                "Use for running scripts, checking system state, or any shell operation."
            ),
            parameters=[
                ToolParameter(
                    name="command",
                    type="string",
                    description="The shell command to execute.",
                ),
                ToolParameter(
                    name="timeout",
                    type="integer",
                    description="Timeout in seconds (default 120).",
                    required=False,
                    default=DEFAULT_TIMEOUT,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> str:
        command: str = kwargs["command"]
        timeout: int = kwargs.get("timeout", DEFAULT_TIMEOUT)

        log.info("Executing: %s", command)

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            output = stdout.decode("utf-8", errors="replace")

            if len(output) > MAX_OUTPUT_CHARS:
                half = MAX_OUTPUT_CHARS // 2
                output = (
                    output[:half]
                    + f"\n\n... [{len(output) - MAX_OUTPUT_CHARS} chars truncated] ...\n\n"
                    + output[-half:]
                )

            exit_info = f"[exit code: {proc.returncode}]"
            return f"{output}\n{exit_info}" if output.strip() else exit_info

        except asyncio.TimeoutError:
            proc.kill()  # type: ignore[union-attr]
            return f"[ERROR] Command timed out after {timeout}s"
        except Exception as e:
            return f"[ERROR] {type(e).__name__}: {e}"
