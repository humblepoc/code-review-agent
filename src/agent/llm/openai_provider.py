"""OpenAI-compatible provider (GPT, Nova via LLM gateway)."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from agent.core.types import LLMResponse, Message, Role, ToolCall
from agent.llm.base import LLMProvider
from agent.tools.schema import ToolSchema

log = logging.getLogger(__name__)


class OpenAIProvider(LLMProvider):
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
        return "openai"

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        system: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        payload = self._build_payload(messages, tools, system, temperature, max_tokens)
        log.debug("OpenAI request: model=%s, messages=%d", self._model, len(payload["messages"]))

        resp = await self._client.post(
            f"{self._base_url}/v1/chat/completions",
            headers={
                "x-api-key": self._api_key,
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
        formatted = self._format_messages(messages, system)
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": formatted,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = [self._format_tool(t) for t in tools]
        return payload

    def _format_messages(
        self, messages: list[Message], system: str | None
    ) -> list[dict[str, Any]]:
        formatted: list[dict[str, Any]] = []

        # System prompt goes as first message in OpenAI format
        if system:
            formatted.append({"role": "system", "content": system})

        for msg in messages:
            if msg.role == Role.SYSTEM:
                formatted.append({"role": "system", "content": msg.content})
            elif msg.role == Role.ASSISTANT and msg.tool_calls:
                m: dict[str, Any] = {"role": "assistant"}
                if msg.content:
                    m["content"] = msg.content
                else:
                    m["content"] = None
                m["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in msg.tool_calls
                ]
                formatted.append(m)
            elif msg.role == Role.TOOL:
                for tr in msg.tool_results:
                    formatted.append({
                        "role": "tool",
                        "tool_call_id": tr.tool_call_id,
                        "content": tr.content,
                    })
            else:
                formatted.append({
                    "role": msg.role.value,
                    "content": msg.content,
                })
        return formatted

    def _format_tool(self, schema: ToolSchema) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": schema.name,
                "description": schema.description,
                "parameters": schema.to_json_schema(),
            },
        }

    def _parse_response(self, data: dict[str, Any]) -> LLMResponse:
        choice = data["choices"][0]
        msg = choice["message"]

        tool_calls: list[ToolCall] = []
        if msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                func = tc["function"]
                try:
                    args = json.loads(func["arguments"])
                except (json.JSONDecodeError, TypeError):
                    args = {}
                tool_calls.append(ToolCall(
                    id=tc["id"],
                    name=func["name"],
                    arguments=args,
                ))

        finish_reason = choice.get("finish_reason", "stop")
        usage = data.get("usage", {})

        message = Message(
            role=Role.ASSISTANT,
            content=msg.get("content") or "",
            tool_calls=tool_calls,
        )

        stop_reason = "tool_use" if finish_reason == "tool_calls" else "end_turn"
        return LLMResponse(
            message=message,
            stop_reason=stop_reason,
            usage={
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
            },
        )
