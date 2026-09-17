"""Tests for the expanded AI provider abstraction (master prompt §6 — Task 3-a).

Covers:
  - registry has at least 50 providers with required metadata fields.
  - OpenAICompatibleProvider can be constructed from an AIProviderConfig.
  - VercelAIGatewayProvider reads VERCEL_AI_GATEWAY_KEY from env (via
    the credential manager).
  - get_provider_from_credentials returns None when no credential is set,
    and returns a provider instance when the env var is provided.
  - get_provider(name, config) succeeds for every name in registry.PROVIDERS.
  - sync_models() returns a dict with every provider, count=0 when no
    credentials are present.

All tests run with ``AUTOMATION_MOCK_MODE=true`` (set by the conftest) so
no network calls are made.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Path setup — the conftest already adds automation-service to sys.path,
# but we also need it for the top-level ai_providers package.
# ---------------------------------------------------------------------------

_AUTOMATION_ROOT = str(Path("/home/z/my-project/apps/automation-service"))
if _AUTOMATION_ROOT not in sys.path:
    sys.path.insert(0, _AUTOMATION_ROOT)
_PROJECT_ROOT = "/home/z/my-project"
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# Imports placed AFTER sys.path setup so the top-level ai_providers package
# (which lives at apps/automation-service/ai_providers/, OUTSIDE the
# automation_service package) is discoverable.
from ai_providers import registry as provider_registry  # type: ignore  # noqa: E402
from automation_service.ai_providers.base import (  # noqa: E402
    AIProviderConfig,
    get_provider,
    get_provider_from_credentials,
    list_providers,
)
from automation_service.ai_providers.openai_compatible import (  # noqa: E402
    OpenAICompatibleProvider,
)
from automation_service.ai_providers.vercel_gateway import (  # noqa: E402
    VercelAIGatewayProvider,
)


# ---------------------------------------------------------------------------
# 1. Registry shape
# ---------------------------------------------------------------------------


def test_registry_has_50_providers() -> None:
    """registry.PROVIDERS must contain at least 50 entries."""
    assert len(provider_registry.PROVIDERS) >= 50, (
        f"Expected >= 50 providers in registry, got {len(provider_registry.PROVIDERS)}"
    )


def test_registry_entries_have_required_fields() -> None:
    """Every registry entry must have all required metadata fields."""
    required_fields = {
        "display_name",
        "base_url",
        "env_key",
        "docs_url",
        "openai_compatible",
        "supports_model_list",
        "default_model",
        "notes",
    }
    for name, info in provider_registry.PROVIDERS.items():
        missing = required_fields - set(info.keys())
        assert not missing, f"Provider {name!r} missing fields: {missing}"


def test_registry_includes_key_providers() -> None:
    """Spot-check that the headline names from the task are present."""
    expected = {
        "openai",
        "anthropic",
        "gemini",
        "deepseek",
        "mistral",
        "xai",
        "groq",
        "together",
        "openrouter",
        "vercel_gateway",
        "ollama",
        "lm_studio",
        "sambanova_cloud",
        "together_computer",
        "cerebrium",
    }
    found = set(provider_registry.PROVIDERS.keys())
    missing = expected - found
    assert not missing, f"Registry missing providers: {missing}"


# ---------------------------------------------------------------------------
# 2. OpenAICompatibleProvider construction
# ---------------------------------------------------------------------------


def test_openai_compatible_provider_init() -> None:
    """OpenAICompatibleProvider can be constructed from an AIProviderConfig."""
    cfg = AIProviderConfig(
        name="deepseek",
        api_key="test-key-not-real",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-chat",
    )
    provider = OpenAICompatibleProvider(cfg)
    assert provider.name == "openai_compatible"
    assert provider.config.api_key == "test-key-not-real"
    assert provider.config.base_url == "https://api.deepseek.com/v1"
    assert provider.config.model == "deepseek-chat"


def test_openai_compatible_provider_uses_default_base_url() -> None:
    """A subclass with default_base_url set fills in config.base_url when missing."""
    cfg = AIProviderConfig(name="groq", api_key="test", model="llama-3.3-70b")

    class _GroqProvider(OpenAICompatibleProvider):
        name = "groq"
        default_base_url = "https://api.groq.com/openai/v1"

    provider = _GroqProvider(cfg)
    assert provider.config.base_url == "https://api.groq.com/openai/v1"


# ---------------------------------------------------------------------------
# 3. VercelAIGatewayProvider construction
# ---------------------------------------------------------------------------


def test_vercel_gateway_init_no_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """VercelAIGatewayProvider can be constructed even without an env var
    set — it just leaves api_key=None."""
    # Ensure the env var is unset
    monkeypatch.delenv("VERCEL_AI_GATEWAY_KEY", raising=False)
    cfg = AIProviderConfig(name="vercel_gateway", model="openai/gpt-4o-mini")
    provider = VercelAIGatewayProvider(cfg)
    assert provider.name == "vercel_gateway"
    assert provider.config.api_key is None
    # base_url should fall back to the default
    assert "ai-gateway.vercel.sh" in (provider.config.base_url or "")


def test_vercel_gateway_init_reads_env_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """VercelAIGatewayProvider loads the API key from
    VERCEL_AI_GATEWAY_KEY via the credential manager."""
    monkeypatch.setenv("VERCEL_AI_GATEWAY_KEY", "vck_test_fake_key_value_xxxxxxxx")
    cfg = AIProviderConfig(name="vercel_gateway", model="openai/gpt-4o-mini")
    provider = VercelAIGatewayProvider(cfg)
    assert provider.config.api_key == "vck_test_fake_key_value_xxxxxxxx"
    assert provider.config.api_key is not None


# ---------------------------------------------------------------------------
# 4. get_provider_from_credentials
# ---------------------------------------------------------------------------


def test_get_provider_from_credentials_returns_none_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no env var set, get_provider_from_credentials returns None."""
    # Clear all provider credential env vars that the registry knows about.
    for name, info in provider_registry.PROVIDERS.items():
        env_key = info.get("env_key")
        if env_key:
            env_var = env_key.upper().replace("-", "_").replace(".", "_")
            monkeypatch.delenv(env_var, raising=False)

    result = get_provider_from_credentials("deepseek")
    assert result is None, "Expected None when DEEPSEEK_API_KEY is unset"


def test_get_provider_from_credentials_returns_provider_when_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the env var is set, get_provider_from_credentials returns a
    constructed provider with the API key loaded from env."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-fake-deepseek-key-value")
    result = get_provider_from_credentials("deepseek")
    assert result is not None, "Expected a provider when DEEPSEEK_API_KEY is set"
    assert result.name == "deepseek"
    assert result.config.api_key == "sk-test-fake-deepseek-key-value"
    # base_url should be populated from the registry entry
    assert result.config.base_url == "https://api.deepseek.com/v1"
    assert result.config.model == "deepseek-chat"


def test_get_provider_from_credentials_for_local_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Local providers (ollama, lm_studio) have env_key=None — they should
    still be constructible via get_provider_from_credentials when the env
    is unset, because they don't need a credential."""
    # Make sure no stray env var leaks in.
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    monkeypatch.delenv("LM_STUDIO_API_KEY", raising=False)
    result = get_provider_from_credentials("ollama")
    # Ollama is registered (existing class) — should construct successfully.
    assert result is not None
    assert result.name == "ollama"


# ---------------------------------------------------------------------------
# 5. Factory: get_provider succeeds for every registry entry
# ---------------------------------------------------------------------------


def test_provider_factory_all_names() -> None:
    """get_provider(name, config) must succeed for every entry in
    registry.PROVIDERS — no exceptions during instantiation."""
    failures: list[str] = []
    for name in provider_registry.PROVIDERS:
        cfg = AIProviderConfig(
            name=name,
            api_key="test-key-not-real",
            base_url=provider_registry.PROVIDERS[name].get("base_url"),
            model=provider_registry.PROVIDERS[name].get("default_model", ""),
        )
        try:
            provider = get_provider(name, cfg)
            assert provider is not None
            assert provider.name == name or provider.name in {
                "openai_compatible",
                "placeholder",
                "openai",
                "anthropic",
                "gemini",
                "ollama",
                "custom",
                "vercel_gateway",
            }
        except Exception as exc:
            failures.append(f"{name}: {exc}")
    assert not failures, "Factory failures: " + "; ".join(failures)


def test_list_providers_includes_all_registry_names() -> None:
    """list_providers() must include every registry entry + custom + vercel_gateway."""
    listed = set(list_providers())
    for name in provider_registry.PROVIDERS:
        assert name in listed, f"Provider {name!r} missing from list_providers()"
    # The original 5 + vercel_gateway + custom should all be there
    for must_have in ("openai", "anthropic", "gemini", "ollama", "custom", "vercel_gateway"):
        assert must_have in listed


def test_get_provider_unknown_name_raises() -> None:
    """get_provider raises ValueError for an unknown name."""
    cfg = AIProviderConfig(name="unknown", api_key="x")
    with pytest.raises(ValueError, match="Unknown AI provider"):
        get_provider("does_not_exist_xyz", cfg)


# ---------------------------------------------------------------------------
# 6. sync_models — graceful handling when no credentials are present
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_model_sync_skips_missing_credentials(
    monkeypatch: pytest.MonkeyPatch,
    db_session,
) -> None:
    """sync_models() returns a dict with every provider, count=0 for those
    without credentials (which is all of them in a clean test env)."""
    # Clear every provider credential env var so the test is deterministic.
    for name, info in provider_registry.PROVIDERS.items():
        env_key = info.get("env_key")
        if env_key:
            env_var = env_key.upper().replace("-", "_").replace(".", "_")
            monkeypatch.delenv(env_var, raising=False)

    from automation_service.ai_providers.model_sync import sync_models

    results = await sync_models(session=db_session, include_vercel_gateway=True)

    # Every provider in the registry must be in the results dict.
    for name in provider_registry.PROVIDERS:
        assert name in results, f"Provider {name!r} missing from sync_models() result"

    # Without credentials, every count must be zero.
    nonzero = {n: c for n, c in results.items() if c > 0}
    assert not nonzero, f"Expected all-zero counts, but got non-zero: {nonzero}"


@pytest.mark.asyncio
async def test_model_sync_returns_dict_for_every_provider(
    monkeypatch: pytest.MonkeyPatch,
    db_session,
) -> None:
    """The sync_models() result dict has exactly the same set of keys as
    registry.PROVIDERS (no more, no less)."""
    for name, info in provider_registry.PROVIDERS.items():
        env_key = info.get("env_key")
        if env_key:
            env_var = env_key.upper().replace("-", "_").replace(".", "_")
            monkeypatch.delenv(env_var, raising=False)

    from automation_service.ai_providers.model_sync import sync_models

    results = await sync_models(session=db_session, include_vercel_gateway=True)

    assert set(results.keys()) == set(provider_registry.PROVIDERS.keys()), (
        f"sync_models result keys differ from registry keys: "
        f"missing={set(provider_registry.PROVIDERS) - set(results)} "
        f"extra={set(results) - set(provider_registry.PROVIDERS)}"
    )


# ---------------------------------------------------------------------------
# 7. Mock-mode behaviour — list_models returns fixtures without HTTP
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_compat_list_models_mock_mode() -> None:
    """In mock mode, OpenAICompatibleProvider.list_models returns a small
    deterministic fixture without making any HTTP call."""
    cfg = AIProviderConfig(
        name="deepseek",
        api_key="test-key",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-chat",
    )
    provider = OpenAICompatibleProvider(cfg)
    models = await provider.list_models()
    assert isinstance(models, list)
    assert len(models) >= 2  # the mock fixture has 2 entries
    assert all(isinstance(m, dict) for m in models)
    assert all("id" in m for m in models)


@pytest.mark.asyncio
async def test_vercel_gateway_list_models_mock_mode() -> None:
    """In mock mode, VercelAIGatewayProvider.list_models returns a fixture
    list (with provider-prefixed model ids) without HTTP."""
    cfg = AIProviderConfig(
        name="vercel_gateway",
        api_key="test-key",
        model="openai/gpt-4o-mini",
    )
    provider = VercelAIGatewayProvider(cfg)
    models = await provider.list_models()
    assert isinstance(models, list)
    assert len(models) >= 3
    # Each model id should contain a "/" since the gateway prefixes with provider
    assert all("/" in m["id"] for m in models), "Gateway model ids should be prefixed"


@pytest.mark.asyncio
async def test_openai_compat_complete_mock_mode() -> None:
    """In mock mode, complete() returns a deterministic string without HTTP."""
    cfg = AIProviderConfig(
        name="groq",
        api_key="test-key",
        base_url="https://api.groq.com/openai/v1",
        model="llama-3.3-70b",
    )
    provider = OpenAICompatibleProvider(cfg)
    response = await provider.complete(
        [{"role": "user", "content": "Hello"}]
    )
    assert isinstance(response, str)
    assert len(response) > 0
