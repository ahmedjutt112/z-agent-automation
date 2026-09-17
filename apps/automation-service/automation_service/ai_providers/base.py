"""AIProvider abstract base + registry — master prompt §6."""

from __future__ import annotations

import abc
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from ..models import Plan, RiskLevel


@dataclass
class AIProviderConfig:
    name: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: str = ""
    temperature: float = 0.2
    max_tokens: int = 2000
    vision: bool = False
    reasoning: bool = False


class AIProvider(abc.ABC):
    """Abstract AI provider — cloud or local."""

    name: str = "base"

    def __init__(self, config: AIProviderConfig) -> None:
        self.config = config

    @abc.abstractmethod
    async def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        """Run a chat completion. Returns the assistant message content."""
        raise NotImplementedError

    async def complete_with_vision(
        self, messages: list[dict[str, str]], image_paths: list[str], **kwargs: Any
    ) -> str:
        """Vision-aware completion. Default: not supported."""
        raise NotImplementedError(f"{self.name} does not support vision")

    @staticmethod
    def _risk_from_text(text: str) -> RiskLevel:
        t = text.lower()
        if any(k in t for k in ("delete", "rm -rf", "format", "format disk", "drop table")):
            return RiskLevel.CRITICAL
        if any(k in t for k in ("install", "modify", "system", "registry", "password", "purchase", "send")):
            return RiskLevel.HIGH
        if any(k in t for k in ("move", "rename", "edit", "close", "download")):
            return RiskLevel.MEDIUM
        return RiskLevel.LOW


# ---------------------------------------------------------------------------
# Concrete providers
# ---------------------------------------------------------------------------


class OpenAIProvider(AIProvider):
    name = "openai"

    async def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        try:
            from openai import AsyncOpenAI  # type: ignore
        except ImportError as e:
            raise RuntimeError("openai package not installed") from e
        client = AsyncOpenAI(api_key=self.config.api_key, base_url=self.config.base_url)
        resp = await client.chat.completions.create(
            model=self.config.model or "gpt-4o-mini",
            messages=messages,
            temperature=kwargs.get("temperature", self.config.temperature),
            max_tokens=kwargs.get("max_tokens", self.config.max_tokens),
        )
        return resp.choices[0].message.content or ""


class AnthropicProvider(AIProvider):
    name = "anthropic"

    async def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        try:
            from anthropic import AsyncAnthropic  # type: ignore
        except ImportError as e:
            raise RuntimeError("anthropic package not installed") from e
        client = AsyncAnthropic(api_key=self.config.api_key)
        # Extract system message
        system_msgs = [m["content"] for m in messages if m["role"] == "system"]
        user_messages = [m for m in messages if m["role"] != "system"]
        resp = await client.messages.create(
            model=self.config.model or "claude-3-5-sonnet-20241022",
            system="\n\n".join(system_msgs) if system_msgs else None,
            messages=user_messages,
            max_tokens=kwargs.get("max_tokens", self.config.max_tokens),
            temperature=kwargs.get("temperature", self.config.temperature),
        )
        return resp.content[0].text if resp.content else ""


class GeminiProvider(AIProvider):
    name = "gemini"

    async def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        try:
            import google.generativeai as genai  # type: ignore
        except ImportError as e:
            raise RuntimeError("google-generativeai package not installed") from e
        genai.configure(api_key=self.config.api_key)
        model = genai.GenerativeModel(self.config.model or "gemini-1.5-flash")
        prompt = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
        resp = await model.generate_content_async(prompt)
        return resp.text


class OllamaProvider(AIProvider):
    """Local LLM via Ollama — master prompt §45 (offline mode)."""

    name = "ollama"

    async def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        import aiohttp
        base_url = self.config.base_url or "http://localhost:11434"
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{base_url}/api/chat",
                json={
                    "model": self.config.model or "llama3.1",
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "temperature": kwargs.get("temperature", self.config.temperature),
                        "num_predict": kwargs.get("max_tokens", self.config.max_tokens),
                    },
                },
            ) as resp:
                data = await resp.json()
                return data.get("message", {}).get("content", "")


class CustomProvider(AIProvider):
    """OpenAI-compatible custom endpoint (LM Studio, vLLM, etc.)."""

    name = "custom"

    async def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        # Reuse OpenAI client logic with custom base_url
        provider = OpenAIProvider(self.config)
        return await provider.complete(messages, **kwargs)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


_PROVIDERS: dict[str, type[AIProvider]] = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "gemini": GeminiProvider,
    "ollama": OllamaProvider,
    "custom": CustomProvider,
}


def get_provider(name: str, config: AIProviderConfig) -> AIProvider:
    if name not in _PROVIDERS:
        raise ValueError(f"Unknown AI provider: {name}. Available: {list(_PROVIDERS)}")
    return _PROVIDERS[name](config)


def list_providers() -> list[str]:
    return list(_PROVIDERS.keys())
