"""Claude provider via LLM gateway (/v1/messages)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from agent.core.types import LLMResponse, Message, Role, ToolCall
from agent.llm.base import LLMProvider
from agent.tools.schema import ToolSchema

log = logging.getLogger(__name__)


class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str, model: str, base_url: str) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        # No read/write timeout: open-source models on the gateway can be very
        # slow. Only the Lambda's own 900s timeout bounds a call. Keep a short
        # connect timeout so an unreachable gateway still fails fast.
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(None, connect=30.0))

    @property
    def name(self) -> str:
        return "anthropic"

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        system: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        payload = self._build_payload(messages, tools, system, temperature, max_tokens)
        log.debug("Anthropic request: model=%s, messages=%d", self._model, len(messages))

        resp = await self._client.post(
            f"{self._base_url}/v1/messages",
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        return self._parse_response(data)

    def _build_payload(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None,
        system: str | None,
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": self._format_messages(messages),
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = [self._format_tool(t) for t in tools]
        return payload

    def _format_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        formatted: list[dict[str, Any]] = []
        for msg in messages:
            if msg.role == Role.SYSTEM:
                continue  # System is top-level for Anthropic
            if msg.role == Role.ASSISTANT and msg.tool_calls:
                content: list[dict[str, Any]] = []
                if msg.content:
                    content.append({"type": "text", "text": msg.content})
                for tc in msg.tool_calls:
                    content.append({
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.name,
                        "input": tc.arguments,
                    })
                formatted.append({"role": "assistant", "content": content})
            elif msg.role == Role.TOOL:
                # Tool results go in a user message with tool_result blocks
                content = []
                for tr in msg.tool_results:
                    content.append({
                        "type": "tool_result",
                        "tool_use_id": tr.tool_call_id,
                        "content": tr.content,
                        **({"is_error": True} if tr.is_error else {}),
                    })
                formatted.append({"role": "user", "content": content})
            else:
                formatted.append({
                    "role": msg.role.value,
                    "content": msg.content,
                })
        return formatted

    def _format_tool(self, schema: ToolSchema) -> dict[str, Any]:
        return {
            "name": schema.name,
            "description": schema.description,
            "input_schema": schema.to_json_schema(),
        }

    def _parse_response(self, data: dict[str, Any]) -> LLMResponse:
        content_blocks = data.get("content", [])
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for block in content_blocks:
            if block["type"] == "text":
                text_parts.append(block["text"])
            elif block["type"] == "tool_use":
                tool_calls.append(ToolCall(
                    id=block["id"],
                    name=block["name"],
                    arguments=block.get("input", {}),
                ))

        stop_reason = data.get("stop_reason", "end_turn")
        usage = data.get("usage", {})

        message = Message(
            role=Role.ASSISTANT,
            content="\n".join(text_parts),
            tool_calls=tool_calls,
        )

        return LLMResponse(
            message=message,
            stop_reason="tool_use" if stop_reason == "tool_use" else stop_reason,
            usage={
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
            },
        )
