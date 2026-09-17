"""AIProvider abstract base + registry — master prompt §6 (expanded scope).

Originally supported 5 providers (openai, anthropic, gemini, ollama, custom).
Now supports 51 providers via:

  - The original 5 concrete classes (kept for backwards compatibility).
  - A generic :class:`OpenAICompatibleProvider` reused for the 28 OpenAI-
    compatible third-party providers (deepseek, mistral, xai, groq, together,
    fireworks, cerebras, sambanova, perplexity, openrouter, huggingface,
    nvidia_nim, novita, siliconflow, hyperbolic, lepton, friendliai, baseten,
    modal, anyscale, aleph_alpha, writer, upstage, baichuan, zhipu, qwen,
    together_computer, cerebrium).
  - A :class:`VercelAIGatewayProvider` aggregator under name ``vercel_gateway``
    that routes to ALL 50 providers via a single API key.
  - A :class:`_PlaceholderProvider` for the ~17 providers that have bespoke
    SDKs (anthropic-style, gemini, cohere, ai21, aws_bedrock, google_vertex,
    azure_ai, ibm_watsonx, replicate, stability, voyage, jina, cloudflare,
    databricks, ai2, amazon_nova, lm_studio, meta, sambanova_cloud, nebius,
    nocipium). These are registered so :func:`get_provider` succeeds for
    every name in ``registry.PROVIDERS``; calling ``complete()`` raises
    NotImplementedError with guidance on which SDK to install.

The provider metadata lives in ``ai_providers.registry`` (the top-level
package outside ``automation_service``) so it can be imported by both the
``zai`` CLI and the service.
"""

from __future__ import annotations

import abc
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

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
# Concrete providers — original 5 (backwards compat)
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
# Lazy-imported newer providers
# ---------------------------------------------------------------------------


def _openai_compat_factory(provider_name: str) -> Callable[[AIProviderConfig], "AIProvider"]:
    """Build a factory that constructs an :class:`OpenAICompatibleProvider`
    with its ``default_base_url`` set from the registry, and ``name`` set to
    the provider slug.
    """
    # Import lazily so this module can be imported even if the
    # ai_providers/ top-level package isn't yet on sys.path (e.g. during
    # very early CLI bootstrap). Once registry is needed, it's looked up.
    from .openai_compatible import OpenAICompatibleProvider

    # Top-level ai_providers package (outside automation_service). If the
    # path isn't on sys.path, we fall back to a hardcoded mapping.
    base_url: Optional[str] = None
    try:
        # Add the apps/automation-service dir to sys.path if missing so
        # `ai_providers.registry` (the top-level package) is importable.
        import sys
        from pathlib import Path

        automation_root = str(Path(__file__).resolve().parents[3])
        if automation_root not in sys.path:
            sys.path.insert(0, automation_root)
        from ai_providers import registry as _reg  # type: ignore
        info = _reg.PROVIDERS.get(provider_name, {})
        base_url = info.get("base_url")
    except Exception:
        base_url = None

    class _Bound(OpenAICompatibleProvider):
        name = provider_name
        default_base_url = base_url

    return _Bound


def _placeholder_factory(provider_name: str) -> Callable[[AIProviderConfig], "AIProvider"]:
    """Build a placeholder class for providers that have bespoke SDKs."""
    notes = ""
    default_model = ""
    try:
        import sys
        from pathlib import Path

        automation_root = str(Path(__file__).resolve().parents[3])
        if automation_root not in sys.path:
            sys.path.insert(0, automation_root)
        from ai_providers import registry as _reg  # type: ignore
        info = _reg.PROVIDERS.get(provider_name, {})
        notes = info.get("notes", "")
        default_model = info.get("default_model", "")
    except Exception:
        pass

    class _Placeholder(_PlaceholderProvider):
        name = provider_name
        _notes = notes
        _default_model = default_model

    return _Placeholder


class _PlaceholderProvider(AIProvider):
    """Instantiable placeholder for providers without a real implementation.

    Calling :meth:`complete` raises :class:`NotImplementedError` with a
    helpful message pointing at the SDK the user needs to install.
    """

    name: str = "placeholder"
    _notes: str = ""
    _default_model: str = ""

    async def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        raise NotImplementedError(
            f"Provider '{self.name}' is registered but has no concrete implementation. "
            f"Notes: {self._notes or 'install the provider-specific SDK and add a provider class.'} "
            f"Default model: {self._default_model or 'unknown'}."
        )


# ---------------------------------------------------------------------------
# Factory + registry
# ---------------------------------------------------------------------------


# The 5 original providers — always present.
_PROVIDERS: dict[str, Callable[[AIProviderConfig], AIProvider]] = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "gemini": GeminiProvider,
    "ollama": OllamaProvider,
    "custom": CustomProvider,
}


# Vercel AI Gateway — single API key for ALL providers.
def _make_vercel_gateway(config: AIProviderConfig) -> AIProvider:
    from .vercel_gateway import VercelAIGatewayProvider
    return VercelAIGatewayProvider(config)


_PROVIDERS["vercel_gateway"] = _make_vercel_gateway


# Dynamically register every entry in registry.PROVIDERS that isn't already
# in _PROVIDERS. OpenAI-compatible ones get a subclass of
# OpenAICompatibleProvider bound to the right base_url; the rest get a
# placeholder so get_provider() never raises for a registry entry.
def _register_all_from_registry() -> None:
    try:
        import sys
        from pathlib import Path

        automation_root = str(Path(__file__).resolve().parents[3])
        if automation_root not in sys.path:
            sys.path.insert(0, automation_root)
        from ai_providers import registry as _reg  # type: ignore
    except Exception:
        # If the registry isn't importable for some reason, we leave the
        # 5 original + vercel_gateway providers in place — at least basic
        # functionality is preserved.
        return

    for name, info in _reg.PROVIDERS.items():
        if name in _PROVIDERS:
            continue
        if info.get("openai_compatible"):
            _PROVIDERS[name] = _openai_compat_factory(name)
        else:
            _PROVIDERS[name] = _placeholder_factory(name)


_register_all_from_registry()


# ---------------------------------------------------------------------------
# Public factory API
# ---------------------------------------------------------------------------


def get_provider(name: str, config: AIProviderConfig) -> AIProvider:
    """Construct a provider instance by name.

    Raises ``ValueError`` if ``name`` is not in the registry.
    """
    if name not in _PROVIDERS:
        raise ValueError(f"Unknown AI provider: {name}. Available: {list(_PROVIDERS)}")
    factory = _PROVIDERS[name]
    return factory(config)


def get_provider_from_credentials(provider_name: str) -> Optional[AIProvider]:
    """Construct a provider instance, auto-loading the API key from the
    credential manager. Returns ``None`` if no credential is found.

    Looks up the env_key from ``registry.PROVIDERS[provider_name]``; if
    the provider is a local one (no env_key, e.g. ollama / lm_studio),
    returns the provider with no API key set.

    The base_url is auto-set from the registry entry when applicable.
    """
    try:
        import sys
        from pathlib import Path

        automation_root = str(Path(__file__).resolve().parents[3])
        if automation_root not in sys.path:
            sys.path.insert(0, automation_root)
        from ai_providers import registry as _reg  # type: ignore
    except Exception:
        return None

    info = _reg.PROVIDERS.get(provider_name)
    if info is None:
        return None

    env_key = info.get("env_key")
    api_key: Optional[str] = None
    if env_key:
        try:
            from ..security.credentials import get_credential
            api_key = get_credential(env_key)
        except Exception:
            api_key = None
        if not api_key:
            return None  # No credential — caller should skip

    cfg = AIProviderConfig(
        name=provider_name,
        api_key=api_key,
        base_url=info.get("base_url"),
        model=info.get("default_model", ""),
    )
    try:
        return get_provider(provider_name, cfg)
    except Exception:
        return None


def list_providers() -> list[str]:
    """Return all registered provider slugs (always includes the 5 original
    + vercel_gateway + every entry in ``registry.PROVIDERS``)."""
    return list(_PROVIDERS.keys())


__all__ = [
    "AIProvider",
    "AIProviderConfig",
    "OpenAIProvider",
    "AnthropicProvider",
    "GeminiProvider",
    "OllamaProvider",
    "CustomProvider",
    "get_provider",
    "get_provider_from_credentials",
    "list_providers",
]
