"""Gemini provider via SDC LLM Gateway."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from agent.core.types import LLMResponse, Message, Role, ToolCall
from agent.llm.base import LLMProvider
from agent.tools.schema import ToolSchema

log = logging.getLogger(__name__)


class GeminiProvider(LLMProvider):
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
        return "gemini"

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        system: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        payload = self._build_payload(messages, tools, system, temperature, max_tokens)
        log.debug("Gemini request: model=%s", self._model)

        resp = await self._client.post(
            f"{self._base_url}/v1/gemini/generateContent",
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
        payload: dict[str, Any] = {
            "model": self._model,
            "contents": self._format_contents(messages),
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        if tools:
            payload["tools"] = [{"functionDeclarations": [self._format_tool(t) for t in tools]}]
        return payload

    def _format_contents(self, messages: list[Message]) -> list[dict[str, Any]]:
        contents: list[dict[str, Any]] = []
        for msg in messages:
            if msg.role == Role.SYSTEM:
                continue  # Handled via systemInstruction
            elif msg.role == Role.ASSISTANT and msg.tool_calls:
                parts: list[dict[str, Any]] = []
                if msg.content:
                    parts.append({"text": msg.content})
                for tc in msg.tool_calls:
                    parts.append({
                        "functionCall": {
                            "name": tc.name,
                            "args": tc.arguments,
                        }
                    })
                contents.append({"role": "model", "parts": parts})
            elif msg.role == Role.TOOL:
                parts = []
                for tr in msg.tool_results:
                    parts.append({
                        "functionResponse": {
                            "name": tr.name,
                            "response": {"result": tr.content},
                        }
                    })
                contents.append({"role": "user", "parts": parts})
            elif msg.role == Role.USER:
                contents.append({"role": "user", "parts": [{"text": msg.content}]})
            elif msg.role == Role.ASSISTANT:
                contents.append({"role": "model", "parts": [{"text": msg.content}]})
        return contents

    def _format_tool(self, schema: ToolSchema) -> dict[str, Any]:
        return {
            "name": schema.name,
            "description": schema.description,
            "parameters": schema.to_json_schema(),
        }

    def _parse_response(self, data: dict[str, Any]) -> LLMResponse:
        candidates = data.get("candidates", [{}])
        candidate = candidates[0] if candidates else {}
        content = candidate.get("content", {})
        parts = content.get("parts", [])

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for part in parts:
            if "text" in part:
                text_parts.append(part["text"])
            elif "functionCall" in part:
                fc = part["functionCall"]
                tool_calls.append(ToolCall(
                    name=fc["name"],
                    arguments=fc.get("args", {}),
                ))

        finish_reason = candidate.get("finishReason", "STOP")
        usage = data.get("usageMetadata", {})

        message = Message(
            role=Role.ASSISTANT,
            content="\n".join(text_parts),
            tool_calls=tool_calls,
        )

        return LLMResponse(
            message=message,
            stop_reason="tool_use" if tool_calls else "end_turn",
            usage={
                "input_tokens": usage.get("promptTokenCount", 0),
                "output_tokens": usage.get("candidatesTokenCount", 0),
            },
        )
