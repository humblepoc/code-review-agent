"""Provider factory and registry."""

from __future__ import annotations

from agent.config import AgentConfig
from agent.llm.anthropic_provider import AnthropicProvider
from agent.llm.base import LLMProvider


def get_provider(name: str, cfg: AgentConfig) -> LLMProvider:
    """Create an LLM provider by name."""
    factories = {
        "custom": _make_custom,
        "anthropic": _make_anthropic,
        "openai": _make_openai,
        "gemini": _make_gemini,
        "copilot": _make_copilot,
    }

    factory = factories.get(name)
    if factory is None:
        raise ValueError(f"Unknown provider: {name}. Available: {', '.join(factories)}")

    return factory(cfg)


def _make_anthropic(cfg: AgentConfig) -> LLMProvider:
    return AnthropicProvider(
        api_key=cfg.llm.api_key,
        model=cfg.llm.model,
        base_url=cfg.llm.base_url,
    )


def _make_openai(cfg: AgentConfig) -> LLMProvider:
    from agent.llm.openai_provider import OpenAIProvider
    return OpenAIProvider(
        api_key=cfg.llm.api_key,
        model=cfg.llm.model,
        base_url=cfg.llm.base_url,
    )


def _make_gemini(cfg: AgentConfig) -> LLMProvider:
    from agent.llm.gemini_provider import GeminiProvider
    return GeminiProvider(
        api_key=cfg.llm.api_key,
        model=cfg.llm.model,
        base_url=cfg.llm.base_url,
    )


def _make_copilot(cfg: AgentConfig) -> LLMProvider:
    from agent.llm.copilot_provider import CopilotProvider
    return CopilotProvider(
        model=cfg.llm.model,
        pat=cfg.llm.pat,
    )


def _make_custom(cfg: AgentConfig) -> LLMProvider:
    from agent.llm.custom_provider import CustomProvider
    return CustomProvider(
        api_key=cfg.llm.custom_api_key or cfg.llm.api_key,
        model=cfg.llm.model,
        base_url=cfg.llm.base_url,
    )
