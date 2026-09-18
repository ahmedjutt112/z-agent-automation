"""Tests for the SDK-backed AI provider classes (Task 4-c).

These tests exercise the real provider implementations in
:mod:`automation_service.ai_providers.sdk_providers` and the
:func:`chat_completion` high-level helper.

All tests run under ``AUTOMATION_MOCK_MODE=true`` (set by conftest), so
no network calls are made. The provider classes either:
  - Return deterministic mock fixtures (Cohere chat, Voyage embeddings,
    Stability image URL, Replicate/Cloudflare/AzureAI/IBMWatsonx/Databricks
    chat).
  - Raise ``NotImplementedError`` for unsupported operations (Voyage chat,
    Stability chat).
  - Raise ``RuntimeError`` with a helpful message when invoked outside mock
    mode without the required dependency / credential (AWS Bedrock without
    boto3+credentials, Google Vertex without google-auth).

Construction NEVER raises for any provider — only ``complete()`` /
``embed()`` / ``generate_image()`` may raise, and only when actually
invoked outside mock mode.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Path setup — ensure both automation_service and the top-level ai_providers
# package (which lives at apps/automation-service/ai_providers/) are on sys.path.
# The conftest already adds these but we duplicate the setup here so this test
# module is robust to direct invocation.
# ---------------------------------------------------------------------------

_AUTOMATION_ROOT = str(Path("/home/z/my-project/apps/automation-service"))
if _AUTOMATION_ROOT not in sys.path:
    sys.path.insert(0, _AUTOMATION_ROOT)
_PROJECT_ROOT = "/home/z/my-project"
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# Imports placed AFTER sys.path setup.
from automation_service.ai_providers.base import (  # noqa: E402
    AIProviderConfig,
    chat_completion,
    get_provider,
)
from automation_service.ai_providers.sdk_providers import (  # noqa: E402
    AWSBedrockProvider,
    AzureAIProvider,
    CloudflareProvider,
    CohereProvider,
    DatabricksProvider,
    GoogleVertexProvider,
    IBMWatsonxProvider,
    ReplicateProvider,
    StabilityProvider,
    VoyageProvider,
)
from automation_service.ai_providers.openai_compatible import (  # noqa: E402
    OpenAICompatibleProvider,
)


# The 19 SDK-backed providers covered by Task 4-c (the task brief says "17",
# but the table in the brief lists 19 entries — 11 with bespoke HTTP APIs
# plus 8 OpenAI-compatible ones that the registry marks False but that
# actually expose an OpenAI-shaped endpoint).
SDK_PROVIDER_NAMES = [
    "cohere",
    "ai21",
    "jina",
    "voyage",
    "stability",
    "replicate",
    "cloudflare",
    "aws_bedrock",
    "google_vertex",
    "azure_ai",
    "ibm_watsonx",
    "databricks",
    "ai2",
    "amazon_nova",
    "lm_studio",
    "meta",
    "sambanova_cloud",
    "nocipium",
    "nebius",
]


# ---------------------------------------------------------------------------
# 1. Construction — every provider constructs without raising
# ---------------------------------------------------------------------------


def test_cohere_provider_init() -> None:
    """CohereProvider constructs without error."""
    cfg = AIProviderConfig(name="cohere", api_key="test")
    provider = CohereProvider(cfg)
    assert provider.name == "cohere"
    assert provider.config.api_key == "test"


def test_voyage_provider_init() -> None:
    """VoyageProvider constructs without error."""
    cfg = AIProviderConfig(name="voyage", api_key="test")
    provider = VoyageProvider(cfg)
    assert provider.name == "voyage"


def test_stability_provider_init() -> None:
    """StabilityProvider constructs without error."""
    cfg = AIProviderConfig(name="stability", api_key="test")
    provider = StabilityProvider(cfg)
    assert provider.name == "stability"


def test_replicate_provider_init() -> None:
    """ReplicateProvider constructs without error."""
    cfg = AIProviderConfig(name="replicate", api_key="test")
    provider = ReplicateProvider(cfg)
    assert provider.name == "replicate"


def test_cloudflare_provider_init() -> None:
    """CloudflareProvider constructs without error."""
    cfg = AIProviderConfig(name="cloudflare", api_key="test")
    provider = CloudflareProvider(cfg)
    assert provider.name == "cloudflare"


def test_aws_bedrock_provider_init() -> None:
    """AWSBedrockProvider constructs without error (boto3 may or may not be
    installed — only complete() fails without credentials/dependencies)."""
    cfg = AIProviderConfig(name="aws_bedrock", api_key="test")
    provider = AWSBedrockProvider(cfg)
    assert provider.name == "aws_bedrock"


def test_google_vertex_provider_init() -> None:
    """GoogleVertexProvider constructs without error (google.auth may not be
    installed — only complete() raises a helpful RuntimeError)."""
    cfg = AIProviderConfig(name="google_vertex", api_key="test")
    provider = GoogleVertexProvider(cfg)
    assert provider.name == "google_vertex"


def test_azure_ai_provider_init() -> None:
    """AzureAIProvider constructs without error."""
    cfg = AIProviderConfig(name="azure_ai", api_key="test")
    provider = AzureAIProvider(cfg)
    assert provider.name == "azure_ai"


def test_ibm_watsonx_provider_init() -> None:
    """IBMWatsonxProvider constructs without error."""
    cfg = AIProviderConfig(name="ibm_watsonx", api_key="test")
    provider = IBMWatsonxProvider(cfg)
    assert provider.name == "ibm_watsonx"


def test_databricks_provider_init() -> None:
    """DatabricksProvider constructs without error."""
    cfg = AIProviderConfig(name="databricks", api_key="test")
    provider = DatabricksProvider(cfg)
    assert provider.name == "databricks"


# ---------------------------------------------------------------------------
# 2. Mock-mode behavior — complete() / embed() / generate_image()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cohere_provider_complete_mock() -> None:
    """In mock mode, CohereProvider.complete returns a deterministic string."""
    cfg = AIProviderConfig(name="cohere", api_key="test")
    provider = CohereProvider(cfg)
    response = await provider.complete(
        [{"role": "user", "content": "Hello, Cohere!"}]
    )
    assert isinstance(response, str)
    assert len(response) > 0


@pytest.mark.asyncio
async def test_voyage_provider_rejects_chat() -> None:
    """Calling complete() on VoyageProvider raises NotImplementedError with a
    helpful message pointing the user at embed()."""
    cfg = AIProviderConfig(name="voyage", api_key="test")
    provider = VoyageProvider(cfg)
    with pytest.raises(NotImplementedError, match="embeddings-only"):
        await provider.complete([{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_voyage_provider_embed_mock() -> None:
    """In mock mode, VoyageProvider.embed returns a list of fake embeddings."""
    cfg = AIProviderConfig(name="voyage", api_key="test")
    provider = VoyageProvider(cfg)
    texts = ["hello", "world"]
    embeddings = await provider.embed(texts)
    assert isinstance(embeddings, list)
    assert len(embeddings) == 2  # one per input text
    assert all(isinstance(e, list) for e in embeddings)
    assert all(len(e) > 0 for e in embeddings)


@pytest.mark.asyncio
async def test_stability_provider_rejects_chat() -> None:
    """Calling complete() on StabilityProvider raises NotImplementedError with a
    helpful message pointing the user at generate_image()."""
    cfg = AIProviderConfig(name="stability", api_key="test")
    provider = StabilityProvider(cfg)
    with pytest.raises(NotImplementedError, match="image-generation"):
        await provider.complete([{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_stability_provider_generate_image_mock() -> None:
    """In mock mode, StabilityProvider.generate_image returns a fake image URL."""
    cfg = AIProviderConfig(name="stability", api_key="test")
    provider = StabilityProvider(cfg)
    result = await provider.generate_image("a serene mountain landscape at sunset")
    assert isinstance(result, dict)
    # Either a URL or a base64-encoded payload is acceptable.
    assert "url" in result or "b64_json" in result


@pytest.mark.asyncio
async def test_replicate_provider_complete_mock() -> None:
    """In mock mode, ReplicateProvider.complete returns a deterministic string."""
    cfg = AIProviderConfig(name="replicate", api_key="test")
    provider = ReplicateProvider(cfg)
    response = await provider.complete([{"role": "user", "content": "hi"}])
    assert isinstance(response, str)
    assert len(response) > 0


@pytest.mark.asyncio
async def test_cloudflare_provider_complete_mock() -> None:
    """In mock mode, CloudflareProvider.complete returns a deterministic string."""
    cfg = AIProviderConfig(name="cloudflare", api_key="test")
    provider = CloudflareProvider(cfg)
    response = await provider.complete([{"role": "user", "content": "hi"}])
    assert isinstance(response, str)
    assert len(response) > 0


@pytest.mark.asyncio
async def test_aws_bedrock_provider_complete_mock() -> None:
    """In mock mode, AWSBedrockProvider.complete returns a deterministic string."""
    cfg = AIProviderConfig(name="aws_bedrock", api_key="test")
    provider = AWSBedrockProvider(cfg)
    response = await provider.complete([{"role": "user", "content": "hi"}])
    assert isinstance(response, str)
    assert len(response) > 0


@pytest.mark.asyncio
async def test_google_vertex_provider_complete_mock() -> None:
    """In mock mode, GoogleVertexProvider.complete returns a deterministic string."""
    cfg = AIProviderConfig(name="google_vertex", api_key="test")
    provider = GoogleVertexProvider(cfg)
    response = await provider.complete([{"role": "user", "content": "hi"}])
    assert isinstance(response, str)
    assert len(response) > 0


@pytest.mark.asyncio
async def test_azure_ai_provider_complete_mock() -> None:
    """In mock mode, AzureAIProvider.complete returns a deterministic string."""
    cfg = AIProviderConfig(name="azure_ai", api_key="test")
    provider = AzureAIProvider(cfg)
    response = await provider.complete([{"role": "user", "content": "hi"}])
    assert isinstance(response, str)
    assert len(response) > 0


@pytest.mark.asyncio
async def test_ibm_watsonx_provider_complete_mock() -> None:
    """In mock mode, IBMWatsonxProvider.complete returns a deterministic string."""
    cfg = AIProviderConfig(name="ibm_watsonx", api_key="test")
    provider = IBMWatsonxProvider(cfg)
    response = await provider.complete([{"role": "user", "content": "hi"}])
    assert isinstance(response, str)
    assert len(response) > 0


@pytest.mark.asyncio
async def test_databricks_provider_complete_mock() -> None:
    """In mock mode, DatabricksProvider.complete returns a deterministic string."""
    cfg = AIProviderConfig(name="databricks", api_key="test")
    provider = DatabricksProvider(cfg)
    response = await provider.complete([{"role": "user", "content": "hi"}])
    assert isinstance(response, str)
    assert len(response) > 0


@pytest.mark.asyncio
async def test_amazon_nova_uses_bedrock_provider() -> None:
    """amazon_nova is registered with AWSBedrockProvider (same Bedrock runtime
    API). In mock mode, it returns a deterministic string."""
    cfg = AIProviderConfig(name="amazon_nova", api_key="test")
    provider = get_provider("amazon_nova", cfg)
    assert isinstance(provider, AWSBedrockProvider)
    # The instance's `name` should reflect the registry slug, not the class
    # default (so factory round-trips preserve the slug).
    assert provider.name == "amazon_nova"
    response = await provider.complete([{"role": "user", "content": "hi"}])
    assert isinstance(response, str)
    assert len(response) > 0


# ---------------------------------------------------------------------------
# 3. chat_completion() helper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_completion_helper() -> None:
    """chat_completion('openai', ...) in mock mode returns a string."""
    response = await chat_completion(
        "openai",
        [{"role": "user", "content": "hi"}],
    )
    assert isinstance(response, str)
    assert len(response) > 0


@pytest.mark.asyncio
async def test_chat_completion_unknown_provider() -> None:
    """chat_completion raises ValueError for an unknown provider name."""
    with pytest.raises(ValueError, match="Unknown AI provider"):
        await chat_completion(
            "this_provider_definitely_does_not_exist_xyz",
            [{"role": "user", "content": "hi"}],
        )


@pytest.mark.asyncio
async def test_chat_completion_no_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """When mock_mode is off and no env var is set, chat_completion raises
    RuntimeError with a helpful message naming the env var to set."""
    # Turn mock mode off for this test.
    monkeypatch.setenv("AUTOMATION_MOCK_MODE", "false")
    # Make sure no provider API-key env vars are set.
    for name in SDK_PROVIDER_NAMES:
        for env_suffix in (
            "_API_KEY",
            "_TOKEN",
            "_PROJECT_ID",
            "_ENDPOINT",
            "_HOST",
            "_KEY",
        ):
            env_var = (name.upper() + env_suffix).replace("-", "_").replace(".", "_")
            monkeypatch.delenv(env_var, raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with pytest.raises(RuntimeError) as exc_info:
        await chat_completion(
            "openai",
            [{"role": "user", "content": "hi"}],
        )
    # The error message should mention OPENAI_API_KEY (the env var name).
    assert "OPENAI_API_KEY" in str(exc_info.value)


@pytest.mark.asyncio
async def test_chat_completion_unknown_provider_takes_priority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even with mock_mode off, an unknown provider raises ValueError BEFORE
    the credential check runs."""
    monkeypatch.setenv("AUTOMATION_MOCK_MODE", "false")
    with pytest.raises(ValueError, match="Unknown AI provider"):
        await chat_completion(
            "totally_made_up_provider_xyz",
            [{"role": "user", "content": "hi"}],
        )


@pytest.mark.asyncio
async def test_chat_completion_mock_mode_returns_provider_specific_response() -> None:
    """The mock-mode response should mention the provider name so callers
    can distinguish providers in test output."""
    for name in ("openai", "cohere", "deepseek", "anthropic"):
        response = await chat_completion(name, [{"role": "user", "content": "hi"}])
        assert isinstance(response, str)
        assert name in response, (
            f"Mock response for {name!r} should mention the provider name; "
            f"got: {response!r}"
        )


# ---------------------------------------------------------------------------
# 4. get_provider returns real SDK classes (not placeholders)
# ---------------------------------------------------------------------------


def test_get_provider_returns_real_class() -> None:
    """get_provider('cohere', config) returns a CohereProvider instance, not a
    placeholder or generic OpenAICompatibleProvider."""
    cfg = AIProviderConfig(name="cohere", api_key="test")
    provider = get_provider("cohere", cfg)
    assert isinstance(provider, CohereProvider), (
        f"Expected CohereProvider instance, got {type(provider).__name__}"
    )


def test_get_provider_returns_real_class_for_all_sdk_providers() -> None:
    """For each of the 11 bespoke SDK provider slugs, get_provider returns an
    instance of the matching real class (not a placeholder)."""
    expected_classes = {
        "cohere": CohereProvider,
        "voyage": VoyageProvider,
        "stability": StabilityProvider,
        "replicate": ReplicateProvider,
        "cloudflare": CloudflareProvider,
        "aws_bedrock": AWSBedrockProvider,
        "google_vertex": GoogleVertexProvider,
        "azure_ai": AzureAIProvider,
        "ibm_watsonx": IBMWatsonxProvider,
        "databricks": DatabricksProvider,
        "amazon_nova": AWSBedrockProvider,
    }
    for slug, expected_cls in expected_classes.items():
        cfg = AIProviderConfig(name=slug, api_key="test")
        provider = get_provider(slug, cfg)
        assert isinstance(provider, expected_cls), (
            f"Provider for {slug!r} should be {expected_cls.__name__}, "
            f"got {type(provider).__name__}"
        )


def test_get_provider_returns_openai_compat_for_compat_slugs() -> None:
    """For the 8 OpenAI-compatible slugs (ai21, jina, ai2, lm_studio, meta,
    sambanova_cloud, nocipium, nebius), get_provider returns an
    OpenAICompatibleProvider subclass — not a placeholder."""
    compat_slugs = (
        "ai21",
        "jina",
        "ai2",
        "lm_studio",
        "meta",
        "sambanova_cloud",
        "nocipium",
        "nebius",
    )
    for slug in compat_slugs:
        cfg = AIProviderConfig(name=slug, api_key="test")
        provider = get_provider(slug, cfg)
        assert isinstance(provider, OpenAICompatibleProvider), (
            f"Provider for {slug!r} should be an OpenAICompatibleProvider "
            f"subclass, got {type(provider).__name__}"
        )


# ---------------------------------------------------------------------------
# 5. All 19 SDK provider slugs are instantiable
# ---------------------------------------------------------------------------


def test_all_17_providers_instantiable() -> None:
    """Loop through all 19 SDK provider names (the task brief says '17' but
    the table lists 19 — we cover them all) and confirm get_provider(name, ...)
    returns a provider instance (not raising NotImplementedError on
    construction)."""
    failures: list[str] = []
    for name in SDK_PROVIDER_NAMES:
        cfg = AIProviderConfig(name=name, api_key="test-key-not-real")
        try:
            provider = get_provider(name, cfg)
            assert provider is not None
            # The provider's `name` attribute should round-trip to the slug
            # we asked for. This holds for every provider EXCEPT the
            # original 5 + vercel_gateway (whose class name doesn't match the
            # registry slug), but those aren't in this list.
            assert provider.name == name, (
                f"Provider {name!r} has name={provider.name!r} (expected {name!r})"
            )
        except NotImplementedError as exc:
            failures.append(f"{name}: NotImplementedError on construction ({exc})")
        except Exception as exc:
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
    assert not failures, "Construction failures:\n  " + "\n  ".join(failures)


# ---------------------------------------------------------------------------
# 6. Configuration behavior — base_url and model defaults
# ---------------------------------------------------------------------------


def test_cohere_provider_defaults_base_url() -> None:
    """CohereProvider fills in its default base_url when config.base_url is empty."""
    cfg = AIProviderConfig(name="cohere", api_key="test")
    provider = CohereProvider(cfg)
    assert provider.config.base_url == "https://api.cohere.ai/v1"
    assert provider.config.model == "command-r-plus"


def test_cohere_provider_respects_explicit_base_url() -> None:
    """CohereProvider keeps an explicitly-provided base_url."""
    cfg = AIProviderConfig(
        name="cohere",
        api_key="test",
        base_url="https://custom.cohere.example.com/v1",
    )
    provider = CohereProvider(cfg)
    assert provider.config.base_url == "https://custom.cohere.example.com/v1"


def test_voyage_provider_defaults_base_url() -> None:
    """VoyageProvider fills in its default base_url when config.base_url is empty."""
    cfg = AIProviderConfig(name="voyage", api_key="test")
    provider = VoyageProvider(cfg)
    assert provider.config.base_url == "https://api.voyageai.com/v1"


def test_stability_provider_defaults_base_url() -> None:
    """StabilityProvider fills in its default base_url when empty."""
    cfg = AIProviderConfig(name="stability", api_key="test")
    provider = StabilityProvider(cfg)
    assert provider.config.base_url == "https://api.stability.ai/v1"


def test_replicate_provider_defaults_base_url() -> None:
    """ReplicateProvider fills in its default base_url when empty."""
    cfg = AIProviderConfig(name="replicate", api_key="test")
    provider = ReplicateProvider(cfg)
    assert provider.config.base_url == "https://api.replicate.com/v1"


def test_ibm_watsonx_provider_defaults_base_url() -> None:
    """IBMWatsonxProvider fills in its default base_url when empty."""
    cfg = AIProviderConfig(name="ibm_watsonx", api_key="test")
    provider = IBMWatsonxProvider(cfg)
    assert provider.config.base_url == "https://us-south.ml.cloud.ibm.com"


# ---------------------------------------------------------------------------
# 7. Cloudflare account_id resolution
# ---------------------------------------------------------------------------


def test_cloudflare_provider_account_id_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """CloudflareProvider pulls the account_id from CLOUDFLARE_ACCOUNT_ID env var."""
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "test-account-123")
    cfg = AIProviderConfig(name="cloudflare", api_key="test")
    provider = CloudflareProvider(cfg)
    assert provider._account_id == "test-account-123"


def test_cloudflare_provider_account_id_from_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CloudflareProvider extracts the account_id from base_url when no env var is set."""
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
    cfg = AIProviderConfig(
        name="cloudflare",
        api_key="test",
        base_url="https://api.cloudflare.com/client/v4/accounts/abc-987-from-url",
    )
    provider = CloudflareProvider(cfg)
    assert provider._account_id == "abc-987-from-url"


# ---------------------------------------------------------------------------
# 8. AWS Bedrock — mock mode short-circuits before any credential check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aws_bedrock_no_credentials_no_mock_raises_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When mock_mode is off and AWS credentials are missing, complete()
    raises RuntimeError (not ImportError or generic Exception)."""
    monkeypatch.setenv("AUTOMATION_MOCK_MODE", "false")
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    cfg = AIProviderConfig(name="aws_bedrock", api_key=None)
    provider = AWSBedrockProvider(cfg)
    with pytest.raises(RuntimeError, match="AWS credentials missing"):
        await provider.complete([{"role": "user", "content": "hi"}])


# ---------------------------------------------------------------------------
# 9. Google Vertex — helpful error when google-auth is missing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_google_vertex_no_project_id_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When mock_mode is off and GOOGLE_VERTEX_PROJECT_ID is missing,
    GoogleVertexProvider.complete raises RuntimeError pointing at the env var."""
    monkeypatch.setenv("AUTOMATION_MOCK_MODE", "false")
    monkeypatch.delenv("GOOGLE_VERTEX_PROJECT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    cfg = AIProviderConfig(name="google_vertex", api_key="test")
    provider = GoogleVertexProvider(cfg)
    with pytest.raises(RuntimeError, match="project_id missing"):
        await provider.complete([{"role": "user", "content": "hi"}])


# ---------------------------------------------------------------------------
# 10. Azure AI — endpoint / api_key resolution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_azure_ai_no_endpoint_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When mock_mode is off and AZURE_AI_ENDPOINT is missing, complete()
    raises RuntimeError pointing at the env var."""
    monkeypatch.setenv("AUTOMATION_MOCK_MODE", "false")
    monkeypatch.delenv("AZURE_AI_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_AI_KEY", raising=False)
    cfg = AIProviderConfig(name="azure_ai", api_key=None)
    provider = AzureAIProvider(cfg)
    with pytest.raises(RuntimeError, match="Azure AI endpoint missing"):
        await provider.complete([{"role": "user", "content": "hi"}])


# ---------------------------------------------------------------------------
# 11. SigV4 signing — pure-stdlib signing works (smoke test)
# ---------------------------------------------------------------------------


def test_sigv4_signing_smoke() -> None:
    """The SigV4 fallback function produces the 3 required AWS headers."""
    from automation_service.ai_providers.sdk_providers import _sigv4_sign

    headers = _sigv4_sign(
        method="POST",
        url="https://bedrock-runtime.us-east-1.amazonaws.com/model/foo/invoke",
        body='{"prompt":"hi"}',
        access_key="AKIA_TEST_KEY",
        secret_key="shhh-secret-test-key",
        region="us-east-1",
        service="bedrock",
    )
    assert "Authorization" in headers
    assert "x-amz-date" in headers
    assert "x-amz-content-sha256" in headers
    assert headers["Authorization"].startswith("AWS4-HMAC-SHA256 ")
    assert "AKIA_TEST_KEY" in headers["Authorization"]
    # x-amz-date should be a valid ISO timestamp: YYYYMMDDTHHMMSSZ
    assert "T" in headers["x-amz-date"]
    assert headers["x-amz-date"].endswith("Z")
