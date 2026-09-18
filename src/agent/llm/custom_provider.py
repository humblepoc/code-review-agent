"""Custom LLM provider — OpenAI-compatible wire format, Bearer auth."""

from __future__ import annotations

import logging
from typing import Any

from agent.core.types import LLMResponse, Message
from agent.llm.openai_provider import OpenAIProvider
from agent.tools.schema import ToolSchema

log = logging.getLogger(__name__)


class CustomProvider(OpenAIProvider):
    """Custom gateway provider — same wire format as OpenAI, but Bearer auth.

    Inherits payload building and response parsing from OpenAIProvider.
    Only overrides the HTTP call to use ``Authorization: Bearer`` instead
    of the OpenAI-style ``x-api-key`` header.
    """

    @property
    def name(self) -> str:
        return "custom"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "accept": "application/json",
        }

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        system: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        payload = self._build_payload(messages, tools, system, temperature, max_tokens)
        log.debug("Custom request: model=%s, messages=%d", self._model, len(payload["messages"]))

        resp = await self._client.post(
            f"{self._base_url}/v1/chat/completions",
            headers=self._headers(),
            json=payload,
        )
        resp.raise_for_status()
        return self._parse_response(resp.json())

    async def list_models(self) -> list[dict[str, Any]]:
        """Fetch available models from the custom gateway."""
        resp = await self._client.get(
            f"{self._base_url}/v1/models",
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json().get("data", [])
