"""Real-credential integration tests — Task 7-c.

These tests are marked ``@pytest.mark.integration`` and are SKIPPED by
default (see ``conftest.py::pytest_collection_modifyitems``). To run them
you must pass ``--run-integration`` to pytest AND have the relevant
credentials set in env vars.

Coverage:
  - AI providers (openai / anthropic / gemini / deepseek / groq + vercel gateway)
  - OAuth providers (google / github)
  - Messaging integrations (email / telegram / discord)
  - Turso (libsql) database connectivity
  - Model sync (vercel gateway -> ai_models table)

Each test follows the same pattern:
  1. Read the required credential from env vars.
  2. If the credential is missing, ``pytest.skip(...)`` with a clear message.
  3. Force ``AUTOMATION_MOCK_MODE=false`` + ``settings.mock_mode=False`` so
     the provider's HTTP path runs (not the mock short-circuit).
  4. Make the real API call (async — we use ``asyncio.run``).
  5. Assert the response shape.
  6. Restore the previous mock-mode state in the ``finally`` block.

Master prompt §57 — credentials are NEVER logged. We only log success /
failure and the response length (never the response body if it might
contain echoes of the prompt).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# sys.path setup — needed so the top-level ``ai_providers`` package and
# ``automation_service`` are both importable.
# ---------------------------------------------------------------------------


_AUTOMATION_ROOT = str(Path("/home/z/my-project/apps/automation-service"))
if _AUTOMATION_ROOT not in sys.path:
    sys.path.insert(0, _AUTOMATION_ROOT)
_PROJECT_ROOT = "/home/z/my-project"
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ---------------------------------------------------------------------------
# Helper: force mock-mode OFF for the duration of a real-credential test.
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _real_mode():
    """Context manager that disables mock mode for the duration of the block.

    Sets BOTH ``settings.mock_mode = False`` (in-memory) AND
    ``AUTOMATION_MOCK_MODE=false`` (env var), because some providers check
    the env var directly rather than the settings object (e.g.
    :class:`OpenAICompatibleProvider`, :class:`VercelAIGatewayProvider`).

    Restores the previous values on exit so the rest of the test suite still
    runs in mock mode.
    """
    import automation_service.config as cfg
    prev_mock = cfg.settings.mock_mode
    prev_env = os.environ.get("AUTOMATION_MOCK_MODE")
    cfg.settings.mock_mode = False
    os.environ["AUTOMATION_MOCK_MODE"] = "false"
    try:
        yield
    finally:
        cfg.settings.mock_mode = prev_mock
        if prev_env is None:
            os.environ.pop("AUTOMATION_MOCK_MODE", None)
        else:
            os.environ["AUTOMATION_MOCK_MODE"] = prev_env


def _run(coro):
    """Run ``coro`` to completion using a fresh event loop.

    ``asyncio.get_event_loop().run_until_complete(...)`` is deprecated in
    Python 3.12+ when no loop is running — ``asyncio.run`` is the
    recommended replacement.
    """
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# AI provider tests — chat completions
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_openai_real_chat() -> None:
    """Calls OpenAIProvider.complete() with a short prompt.

    Skips if OPENAI_API_KEY is not set or the ``openai`` SDK is not
    installed (the OpenAIProvider class imports it lazily inside complete()).
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        pytest.skip("OPENAI_API_KEY not set — skipping real integration test")

    from automation_service.ai_providers.base import AIProviderConfig, get_provider
    provider = get_provider(
        "openai",
        AIProviderConfig(api_key=api_key, model="gpt-4o-mini"),
    )

    with _real_mode():
        try:
            response = _run(provider.complete([
                {"role": "user", "content": "Say hello in 5 words."},
            ]))
        except RuntimeError as exc:
            if "openai package not installed" in str(exc):
                pytest.skip(f"openai SDK not installed: {exc}")
            raise

    assert isinstance(response, str)
    assert len(response) > 0


@pytest.mark.integration
def test_anthropic_real_chat() -> None:
    """Calls AnthropicProvider.complete() with a short prompt.

    Skips if ANTHROPIC_API_KEY is not set or the ``anthropic`` SDK is
    not installed.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        pytest.skip("ANTHROPIC_API_KEY not set — skipping real integration test")

    from automation_service.ai_providers.base import AIProviderConfig, get_provider
    provider = get_provider(
        "anthropic",
        AIProviderConfig(api_key=api_key, model="claude-3-5-sonnet-20241022"),
    )

    with _real_mode():
        try:
            response = _run(provider.complete([
                {"role": "user", "content": "Say hello in 5 words."},
            ]))
        except RuntimeError as exc:
            if "anthropic package not installed" in str(exc):
                pytest.skip(f"anthropic SDK not installed: {exc}")
            raise

    assert isinstance(response, str)
    assert len(response) > 0


@pytest.mark.integration
def test_gemini_real_chat() -> None:
    """Calls GeminiProvider.complete() with a short prompt.

    Skips if GEMINI_API_KEY is not set or the ``google-generativeai`` SDK
    is not installed.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        pytest.skip("GEMINI_API_KEY not set — skipping real integration test")

    from automation_service.ai_providers.base import AIProviderConfig, get_provider
    provider = get_provider(
        "gemini",
        AIProviderConfig(api_key=api_key, model="gemini-1.5-flash"),
    )

    with _real_mode():
        try:
            response = _run(provider.complete([
                {"role": "user", "content": "Say hello in 5 words."},
            ]))
        except RuntimeError as exc:
            if "google-generativeai package not installed" in str(exc):
                pytest.skip(f"google-generativeai SDK not installed: {exc}")
            raise

    assert isinstance(response, str)
    assert len(response) > 0


@pytest.mark.integration
def test_deepseek_real_chat() -> None:
    """Calls DeepSeek (OpenAI-compatible) complete() with a short prompt.

    Skips if DEEPSEEK_API_KEY is not set.
    """
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        pytest.skip("DEEPSEEK_API_KEY not set — skipping real integration test")

    from automation_service.ai_providers.base import AIProviderConfig, get_provider
    provider = get_provider(
        "deepseek",
        AIProviderConfig(api_key=api_key, model="deepseek-chat"),
    )

    with _real_mode():
        response = _run(provider.complete([
            {"role": "user", "content": "Say hello in 5 words."},
        ]))

    assert isinstance(response, str)
    assert len(response) > 0


@pytest.mark.integration
def test_groq_real_chat() -> None:
    """Calls Groq (OpenAI-compatible) complete() with a short prompt.

    Skips if GROQ_API_KEY is not set.
    """
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        pytest.skip("GROQ_API_KEY not set — skipping real integration test")

    from automation_service.ai_providers.base import AIProviderConfig, get_provider
    provider = get_provider(
        "groq",
        AIProviderConfig(api_key=api_key, model="llama-3.3-70b-versatile"),
    )

    with _real_mode():
        response = _run(provider.complete([
            {"role": "user", "content": "Say hello in 5 words."},
        ]))

    assert isinstance(response, str)
    assert len(response) > 0


# ---------------------------------------------------------------------------
# AI provider tests — model listing
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_openai_real_list_models() -> None:
    """Calls OpenAIProvider.list_models() — but OpenAIProvider doesn't
    expose list_models() (it's only on OpenAICompatibleProvider). We use
    the OpenAI-compatible client pointed at api.openai.com instead.

    Skips if OPENAI_API_KEY is not set.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        pytest.skip("OPENAI_API_KEY not set — skipping real integration test")

    from automation_service.ai_providers.openai_compatible import OpenAICompatibleProvider
    from automation_service.ai_providers.base import AIProviderConfig

    cfg = AIProviderConfig(
        api_key=api_key,
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
    )
    provider = OpenAICompatibleProvider(cfg)

    with _real_mode():
        models = _run(provider.list_models())

    assert isinstance(models, list)
    assert len(models) >= 1
    # Spot-check that the OpenAI list includes a gpt-4* model.
    model_ids = {m.get("id") for m in models}
    assert any(mid and mid.startswith("gpt-") for mid in model_ids), \
        f"expected at least one gpt-* model, got {sorted(model_ids)[:10]}"


@pytest.mark.integration
def test_vercel_gateway_real_chat() -> None:
    """Calls VercelAIGatewayProvider.complete() with a short prompt.

    Skips if VERCEL_AI_GATEWAY_KEY is not set.
    """
    api_key = os.environ.get("VERCEL_AI_GATEWAY_KEY")
    if not api_key:
        pytest.skip("VERCEL_AI_GATEWAY_KEY not set — skipping real integration test")

    from automation_service.ai_providers.vercel_gateway import VercelAIGatewayProvider
    from automation_service.ai_providers.base import AIProviderConfig

    cfg = AIProviderConfig(api_key=api_key, model="openai/gpt-4o-mini")
    provider = VercelAIGatewayProvider(cfg)

    with _real_mode():
        response = _run(provider.complete([
            {"role": "user", "content": "Say hello in 5 words."},
        ]))

    assert isinstance(response, str)
    assert len(response) > 0


@pytest.mark.integration
def test_vercel_gateway_real_list_models() -> None:
    """Calls VercelAIGatewayProvider.list_models() — asserts at least 5 models.

    Skips if VERCEL_AI_GATEWAY_KEY is not set.
    """
    api_key = os.environ.get("VERCEL_AI_GATEWAY_KEY")
    if not api_key:
        pytest.skip("VERCEL_AI_GATEWAY_KEY not set — skipping real integration test")

    from automation_service.ai_providers.vercel_gateway import VercelAIGatewayProvider
    from automation_service.ai_providers.base import AIProviderConfig

    cfg = AIProviderConfig(api_key=api_key, model="openai/gpt-4o-mini")
    provider = VercelAIGatewayProvider(cfg)

    with _real_mode():
        models = _run(provider.list_models())

    assert isinstance(models, list)
    assert len(models) >= 5, f"expected >= 5 models from gateway, got {len(models)}"


# ---------------------------------------------------------------------------
# OAuth providers — real user info
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_github_oauth_real_user_info() -> None:
    """Exchanges a real GitHub OAuth authorization code for tokens and
    fetches the user info.

    Skips unless BOTH ``GITHUB_OAUTH_CLIENT_ID`` is set AND a valid
    ``GITHUB_OAUTH_TEST_CODE`` env var is supplied (the code is short-lived
    so this test is only run on demand during manual integration testing).
    """
    client_id = os.environ.get("GITHUB_OAUTH_CLIENT_ID")
    test_code = os.environ.get("GITHUB_OAUTH_TEST_CODE")
    if not client_id or not test_code:
        pytest.skip(
            "GITHUB_OAUTH_CLIENT_ID or GITHUB_OAUTH_TEST_CODE not set — "
            "skipping real OAuth integration test"
        )

    from automation_service.integrations.oauth import GitHubOAuthProvider
    provider = GitHubOAuthProvider()

    with _real_mode():
        tokens = _run(provider.exchange_code(test_code))
        user_info = _run(provider.get_user_info(tokens))

    assert user_info.provider == "github"
    assert user_info.provider_user_id, "expected non-empty provider_user_id"
    # We do NOT log the email or name here — master prompt §57.


@pytest.mark.integration
def test_google_oauth_real_user_info() -> None:
    """Exchanges a real Google OAuth authorization code for tokens and
    fetches the user info.

    Skips unless BOTH ``GOOGLE_OAUTH_CLIENT_ID`` is set AND a valid
    ``GOOGLE_OAUTH_TEST_CODE`` env var is supplied.
    """
    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
    test_code = os.environ.get("GOOGLE_OAUTH_TEST_CODE")
    if not client_id or not test_code:
        pytest.skip(
            "GOOGLE_OAUTH_CLIENT_ID or GOOGLE_OAUTH_TEST_CODE not set — "
            "skipping real OAuth integration test"
        )

    from automation_service.integrations.oauth import GoogleOAuthProvider
    provider = GoogleOAuthProvider()

    with _real_mode():
        tokens = _run(provider.exchange_code(test_code))
        user_info = _run(provider.get_user_info(tokens))

    assert user_info.provider == "google"
    assert user_info.provider_user_id, "expected non-empty provider_user_id"


# ---------------------------------------------------------------------------
# Messaging integrations
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_email_real_send() -> None:
    """Sends a test email to the address in TEST_EMAIL_TO.

    Skips unless BOTH EMAIL_SMTP_USERNAME and EMAIL_SMTP_PASSWORD are set.
    The recipient address defaults to the SMTP username (i.e. send-to-self)
    unless TEST_EMAIL_TO is set.
    """
    username = os.environ.get("EMAIL_SMTP_USERNAME")
    password = os.environ.get("EMAIL_SMTP_PASSWORD")
    if not username or not password:
        pytest.skip(
            "EMAIL_SMTP_USERNAME or EMAIL_SMTP_PASSWORD not set — "
            "skipping real email integration test"
        )

    to_addr = os.environ.get("TEST_EMAIL_TO") or username
    from automation_service.integrations.email_client import EmailClient
    client = EmailClient()

    with _real_mode():
        result = client.send(
            to=to_addr,
            subject="[z-agent test suite] integration test email",
            body="This is a test email from the z-agent integration test suite.",
        )

    assert result["sent"] is True
    assert to_addr in result["to"]


@pytest.mark.integration
def test_telegram_real_send() -> None:
    """Sends 'Hello from z-agent test suite' to TELEGRAM_TEST_CHAT_ID.

    Skips unless BOTH TELEGRAM_BOT_TOKEN and TELEGRAM_TEST_CHAT_ID are set.
    """
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_TEST_CHAT_ID")
    if not bot_token or not chat_id:
        pytest.skip(
            "TELEGRAM_BOT_TOKEN or TELEGRAM_TEST_CHAT_ID not set — "
            "skipping real Telegram integration test"
        )

    from automation_service.integrations.telegram import TelegramBot
    bot = TelegramBot()

    with _real_mode():
        result = _run(bot.send_text(
            chat_id=chat_id,
            text="Hello from z-agent test suite",
        ))

    assert "message_id" in result
    assert result["message_id"]


@pytest.mark.integration
def test_discord_real_send() -> None:
    """Sends 'Hello from z-agent' to DISCORD_TEST_CHANNEL_ID.

    Skips unless BOTH DISCORD_BOT_TOKEN and DISCORD_TEST_CHANNEL_ID are set.
    """
    bot_token = os.environ.get("DISCORD_BOT_TOKEN")
    channel_id = os.environ.get("DISCORD_TEST_CHANNEL_ID")
    if not bot_token or not channel_id:
        pytest.skip(
            "DISCORD_BOT_TOKEN or DISCORD_TEST_CHANNEL_ID not set — "
            "skipping real Discord integration test"
        )

    from automation_service.integrations.discord import DiscordBot
    bot = DiscordBot()

    with _real_mode():
        result = _run(bot.send_message(
            channel_id=int(channel_id),
            content="Hello from z-agent",
        ))

    assert "message_id" in result
    assert result["message_id"]


# ---------------------------------------------------------------------------
# Database — Turso (libsql)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_turso_real_query() -> None:
    """Executes ``SELECT 1`` against a Turso (libsql://) database.

    Skips unless DATABASE_URL starts with ``libsql://`` AND
    ``TURSO_AUTH_TOKEN`` is set. Also skips if the ``libsql_experimental``
    Python package isn't installed.
    """
    database_url = os.environ.get("DATABASE_URL", "")
    auth_token = os.environ.get("TURSO_AUTH_TOKEN")
    if not database_url.startswith("libsql://"):
        pytest.skip("DATABASE_URL does not start with libsql:// — skipping Turso test")
    if not auth_token:
        pytest.skip("TURSO_AUTH_TOKEN not set — skipping Turso test")

    try:
        import libsql_experimental as libsql  # type: ignore
    except ImportError:
        try:
            import libsql_client as libsql  # type: ignore
        except ImportError:
            pytest.skip(
                "libsql_experimental (or libsql_client) is not installed — "
                "install with: pip install libsql-experimental"
            )

    with _real_mode():
        conn = libsql.connect(database_url, auth_token=auth_token)
        try:
            cur = conn.execute("SELECT 1")
            row = cur.fetchone()
        finally:
            try:
                conn.close()
            except Exception:
                pass

    assert row is not None
    assert row[0] == 1


# ---------------------------------------------------------------------------
# Model sync — Vercel AI Gateway
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_model_sync_real() -> None:
    """Calls sync_models() against the live Vercel AI Gateway.

    Skips if VERCEL_AI_GATEWAY_KEY is not set. Asserts that the gateway
    returns at least 5 models.
    """
    api_key = os.environ.get("VERCEL_AI_GATEWAY_KEY")
    if not api_key:
        pytest.skip("VERCEL_AI_GATEWAY_KEY not set — skipping model sync test")

    # The sync_models() routine needs an open SQLAlchemy session to upsert
    # the results into ai_models. We use an in-memory SQLite session for
    # the test so we don't pollute the real database.
    try:
        from database.base import Base, SessionLocal
        from database.models import schema  # noqa: F401 — registers metadata
    except Exception as exc:
        pytest.skip(f"database module not importable: {exc}")

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestSession()

    from automation_service.ai_providers.model_sync import sync_models

    with _real_mode():
        try:
            results = _run(sync_models(session=session))
        finally:
            session.close()
            engine.dispose()

    # sync_models returns a dict {provider_name: count} for EVERY provider
    # in the registry, plus the vercel_gateway. We only assert on the
    # gateway count since the others need per-provider credentials.
    assert "vercel_gateway" in results
    assert results["vercel_gateway"] >= 5, (
        f"expected >= 5 models from vercel_gateway, got {results['vercel_gateway']}"
    )
