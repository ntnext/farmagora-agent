"""Build the LLM client for a task from config/app.yaml. The only place that knows provider names."""

from __future__ import annotations

from typing import Any

from ...ports.llm import LLMClient, LLMError


def build_client(provider: str, model: str, providers_cfg: dict[str, Any]) -> LLMClient:
    cfg = dict(providers_cfg.get(provider, {}))
    if cfg.pop("kind", None) == "openai_compatible":  # named endpoint, e.g. `groq:` in app.yaml
        from .openai_llm import OpenAICompatibleLLM
        client = OpenAICompatibleLLM(model, **cfg)
        client.provider = provider  # logs and manifest show "groq", not the generic kind
        return client
    if provider == "anthropic":
        from .anthropic_llm import AnthropicLLM
        return AnthropicLLM(model, **cfg)
    if provider == "openai":
        from .openai_llm import OpenAILLM
        return OpenAILLM(model, **cfg)
    if provider == "openai_compatible":
        from .openai_llm import OpenAICompatibleLLM
        return OpenAICompatibleLLM(model, **cfg)
    if provider == "gemini":
        from .gemini_llm import GeminiLLM
        return GeminiLLM(model, **cfg)
    if provider == "offline":
        from .offline_llm import OfflineLLM
        return OfflineLLM(model or "rules-v1", **cfg)
    raise LLMError(f"unknown provider '{provider}'")
