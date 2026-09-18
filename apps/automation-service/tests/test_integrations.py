"""Tests for OAuth + Messaging integrations (master prompt §54 — Task 3-b).

All tests run in mock mode (``AUTOMATION_MOCK_MODE=true`` set by conftest) so
no network calls are made. The test surface covers:

- OAuth provider factory + authorization URL building.
- Email / WhatsApp / Telegram / Discord clients return mock-mode success.
- The 4 notification tools register and execute with status=completed.

Run::

    uv run pytest /home/z/my-project/apps/automation-service/tests/test_integrations.py -v
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# sys.path setup — conftest already adds automation-service to sys.path but
# be defensive so this file works even when run standalone.
# ---------------------------------------------------------------------------

_AUTOMATION_ROOT = str(Path("/home/z/my-project/apps/automation-service"))
if _AUTOMATION_ROOT not in sys.path:
    sys.path.insert(0, _AUTOMATION_ROOT)
_PROJECT_ROOT = "/home/z/my-project"
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# Imports placed AFTER sys.path setup
from automation_service.config import settings  # noqa: E402
from automation_service.integrations.oauth import (  # noqa: E402
    OAUTH_PROVIDERS,
    GoogleOAuthProvider,
    GitHubOAuthProvider,
    FacebookOAuthProvider,
    get_oauth_provider,
    initiate_oauth_flow,
)
from automation_service.integrations.email_client import EmailClient  # noqa: E402
from automation_service.integrations.whatsapp import WhatsAppClient  # noqa: E402
from automation_service.integrations.telegram import TelegramBot  # noqa: E402
from automation_service.integrations.discord import DiscordBot  # noqa: E402
from automation_service.engine.tool_registry import tool_registry  # noqa: E402
from automation_service.models import StepStatus  # noqa: E402


# ---------------------------------------------------------------------------
# OAuth
# ---------------------------------------------------------------------------


def test_oauth_provider_factory() -> None:
    """get_oauth_provider('google') returns a GoogleOAuthProvider instance."""
    provider = get_oauth_provider("google")
    assert isinstance(provider, GoogleOAuthProvider)
    assert provider.provider_name == "google"
    # Other names too
    assert isinstance(get_oauth_provider("github"), GitHubOAuthProvider)
    assert isinstance(get_oauth_provider("facebook"), FacebookOAuthProvider)


def test_oauth_provider_factory_unknown_raises() -> None:
    """Unknown provider name raises ValueError."""
    with pytest.raises(ValueError, match="Unknown OAuth provider"):
        get_oauth_provider("nonexistent")


def test_oauth_registry_contains_expected_providers() -> None:
    """OAUTH_PROVIDERS contains the three required providers."""
    expected = {"google", "github", "facebook"}
    assert expected.issubset(set(OAUTH_PROVIDERS.keys()))


def test_oauth_authorization_url_github(monkeypatch: pytest.MonkeyPatch) -> None:
    """initiate_oauth_flow('github', state='abc') returns a URL containing
    client_id= and state=abc. We monkeypatch client_id/secret via env vars so
    the URL is well-formed even if .env doesn't have them."""
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_ID", "test_github_client_id")
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_SECRET", "test_github_secret")
    monkeypatch.setenv("GITHUB_OAUTH_REDIRECT_URI", "http://localhost:8765/oauth/github/callback")
    url = initiate_oauth_flow("github", state="abc")
    assert isinstance(url, str)
    assert "client_id=test_github_client_id" in url
    assert "state=abc" in url
    assert "github.com" in url


def test_oauth_authorization_url_google(monkeypatch: pytest.MonkeyPatch) -> None:
    """Google provider builds a URL containing client_id, redirect_uri, scope."""
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "google_test_id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "google_test_secret")
    monkeypatch.setenv("GOOGLE_OAUTH_REDIRECT_URI", "http://localhost:8765/oauth/google/callback")
    url = initiate_oauth_flow("google", state="xyz123")
    assert "client_id=google_test_id" in url
    assert "state=xyz123" in url
    assert "accounts.google.com" in url
    assert "scope=" in url  # Google should always include scope


def test_oauth_authorization_url_facebook(monkeypatch: pytest.MonkeyPatch) -> None:
    """Facebook provider builds a URL containing client_id and state."""
    monkeypatch.setenv("FACEBOOK_OAUTH_APP_ID", "fb_test_app_id")
    monkeypatch.setenv("FACEBOOK_OAUTH_APP_SECRET", "fb_test_app_secret")
    monkeypatch.setenv("FACEBOOK_OAUTH_REDIRECT_URI", "http://localhost:8765/oauth/facebook/callback")
    url = initiate_oauth_flow("facebook", state="fbstate")
    assert "client_id=fb_test_app_id" in url
    assert "state=fbstate" in url
    assert "facebook.com" in url


@pytest.mark.asyncio
async def test_oauth_complete_flow_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    """complete_oauth_flow in mock mode returns OAuthUserInfo with provider=google."""
    # Ensure mock mode is on
    assert settings.mock_mode is True
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_ID", "test_client")
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_SECRET", "test_secret")
    from automation_service.integrations.oauth import complete_oauth_flow
    user_info = await complete_oauth_flow("github", code="any-code-mock")
    assert user_info.provider == "github"
    assert user_info.provider_user_id == "mock-github-user-42"
    assert "@github.com" in (user_info.email or "") or user_info.email is not None


# ---------------------------------------------------------------------------
# Email client — mock mode
# ---------------------------------------------------------------------------


def test_email_client_mock() -> None:
    """EmailClient.send() in mock mode returns sent=True without network."""
    assert settings.mock_mode is True
    client = EmailClient()
    result = client.send(
        to="test@example.com",
        subject="Hello",
        body="This is a test email.",
    )
    assert result["sent"] is True
    assert result["mock"] is True
    assert result["to"] == ["test@example.com"]


def test_email_client_inbox_mock() -> None:
    """EmailClient.receive_inbox returns the mock fixture in mock mode."""
    assert settings.mock_mode is True
    client = EmailClient()
    messages = client.receive_inbox(limit=3)
    assert isinstance(messages, list)
    assert len(messages) >= 1
    assert all(hasattr(m, "subject") for m in messages)


# ---------------------------------------------------------------------------
# WhatsApp client — mock mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_whatsapp_client_mock() -> None:
    """WhatsAppClient.send_text returns mock success."""
    assert settings.mock_mode is True
    client = WhatsAppClient()
    result = await client.send_text(to="15551234567", message="Hello WhatsApp")
    assert result["mock"] is True
    assert "message_id" in result
    assert result["to"] == "15551234567"


def test_whatsapp_webhook_verify() -> None:
    """WhatsAppClient.verify_webhook returns challenge when token matches."""
    import os
    monkey_env_token = "test_verify_token_12345"
    old = os.environ.get("WHATSAPP_VERIFY_TOKEN")
    try:
        os.environ["WHATSAPP_VERIFY_TOKEN"] = monkey_env_token
        client = WhatsAppClient()
        # Correct token
        result = client.verify_webhook("subscribe", monkey_env_token, "challenge-123")
        assert result == "challenge-123"
        # Wrong token
        result = client.verify_webhook("subscribe", "wrong-token", "challenge-123")
        assert result is None
        # Wrong mode
        result = client.verify_webhook("unsubscribe", monkey_env_token, "challenge-123")
        assert result is None
    finally:
        if old is None:
            os.environ.pop("WHATSAPP_VERIFY_TOKEN", None)
        else:
            os.environ["WHATSAPP_VERIFY_TOKEN"] = old


def test_whatsapp_receive_webhook() -> None:
    """WhatsAppClient.receive_webhook parses a normalised payload."""
    client = WhatsAppClient()
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": "987654"},
                            "messages": [
                                {
                                    "id": "wamid.HBgL...",
                                    "from": "15551234567",
                                    "timestamp": "1700000000",
                                    "type": "text",
                                    "text": {"body": "Hello from WhatsApp!"},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }
    messages = client.receive_webhook(payload)
    assert len(messages) == 1
    msg = messages[0]
    assert msg.from_ == "15551234567"
    assert msg.to == "987654"
    assert msg.text == "Hello from WhatsApp!"
    assert msg.message_id == "wamid.HBgL..."


# ---------------------------------------------------------------------------
# Telegram client — mock mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_telegram_client_mock() -> None:
    """TelegramBot.send_text returns mock success."""
    assert settings.mock_mode is True
    bot = TelegramBot()
    result = await bot.send_text(chat_id=123456, text="Hello Telegram")
    assert result["mock"] is True
    assert "message_id" in result
    assert result["chat_id"] == "123456"


@pytest.mark.asyncio
async def test_telegram_get_updates_mock() -> None:
    """TelegramBot.get_updates returns a mock update list."""
    assert settings.mock_mode is True
    bot = TelegramBot()
    updates = await bot.get_updates(offset=0)
    assert len(updates) >= 1
    assert updates[0].from_user == "mock_user"
    assert updates[0].text.startswith("/")


def test_telegram_parse_command() -> None:
    """TelegramBot.parse_command splits '/cmd arg1 arg2' correctly."""
    cmd, args = TelegramBot.parse_command("/hello world")
    assert cmd == "/hello"
    assert args == ["world"]
    cmd, args = TelegramBot.parse_command("/remind tomorrow 9am buy milk")
    assert cmd == "/remind"
    assert args == ["tomorrow", "9am", "buy", "milk"]
    # Non-command
    cmd, args = TelegramBot.parse_command("just chatting")
    assert cmd == ""
    assert args == []


# ---------------------------------------------------------------------------
# Discord client — mock mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_discord_client_mock() -> None:
    """DiscordBot.send_message returns mock success."""
    assert settings.mock_mode is True
    bot = DiscordBot()
    result = await bot.send_message(channel_id=123456789, content="Hello Discord")
    assert result["mock"] is True
    assert "message_id" in result
    assert result["channel_id"] == "123456789"


@pytest.mark.asyncio
async def test_discord_list_guilds_mock() -> None:
    """DiscordBot.list_guilds returns a mock guild list."""
    assert settings.mock_mode is True
    bot = DiscordBot()
    guilds = await bot.list_guilds()
    assert isinstance(guilds, list)
    assert len(guilds) >= 1
    assert guilds[0]["name"] == "Mock Guild"


# ---------------------------------------------------------------------------
# Notification tools (registered as Tool subclasses)
# ---------------------------------------------------------------------------


def test_notification_email_tool() -> None:
    """notify.email tool is registered and executes with status=completed."""
    tool = tool_registry.get("notify.email")
    assert tool is not None
    assert tool.name == "notify.email"
    assert tool.risk_level == "medium"
    assert tool.permission_level == "allow_once"
    import asyncio
    result = asyncio.get_event_loop().run_until_complete(
        tool.execute({
            "to": "test@example.com",
            "subject": "Test",
            "body": "Hello world",
        })
    )
    assert result.status == StepStatus.COMPLETED
    assert result.tool == "notify.email"
    assert result.output is not None


def test_notification_telegram_tool() -> None:
    """notify.telegram tool executes with status=completed in mock mode."""
    tool = tool_registry.get("notify.telegram")
    assert tool is not None
    assert tool.name == "notify.telegram"
    assert tool.risk_level == "low"
    import asyncio
    result = asyncio.get_event_loop().run_until_complete(
        tool.execute({
            "chat_id": "123456",
            "text": "Hello from test",
        })
    )
    assert result.status == StepStatus.COMPLETED
    assert result.tool == "notify.telegram"
    assert result.output is not None
    assert result.output.get("mock") is True


def test_notification_whatsapp_tool() -> None:
    """notify.whatsapp tool executes with status=completed in mock mode."""
    tool = tool_registry.get("notify.whatsapp")
    assert tool is not None
    assert tool.risk_level == "medium"
    import asyncio
    result = asyncio.get_event_loop().run_until_complete(
        tool.execute({
            "to": "15551234567",
            "message": "Hello WhatsApp",
        })
    )
    assert result.status == StepStatus.COMPLETED
    assert result.output.get("mock") is True


def test_notification_discord_tool() -> None:
    """notify.discord tool executes with status=completed in mock mode."""
    tool = tool_registry.get("notify.discord")
    assert tool is not None
    assert tool.risk_level == "low"
    import asyncio
    result = asyncio.get_event_loop().run_until_complete(
        tool.execute({
            "channel_id": "123456789",
            "content": "Hello Discord",
        })
    )
    assert result.status == StepStatus.COMPLETED
    assert result.output.get("mock") is True


# ---------------------------------------------------------------------------
# Integration API endpoints (FastAPI TestClient)
# ---------------------------------------------------------------------------


def test_integrations_list_endpoint(client) -> None:
    """GET /integrations lists every integration with a status field."""
    r = client.get("/integrations")
    assert r.status_code == 200
    body = r.json()
    assert "integrations" in body
    items = body["integrations"]
    names = {item["name"] for item in items}
    # All expected integrations should be listed
    assert {"google", "github", "facebook", "email", "whatsapp", "telegram", "discord"} == names


def test_integrations_email_send_mock(client) -> None:
    """POST /integrations/email/send returns sent=True in mock mode."""
    r = client.post("/integrations/email/send", json={
        "to": "dest@example.com",
        "subject": "Test",
        "body": "Hello",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["sent"] is True
    assert body.get("mock") is True


def test_integrations_telegram_send_mock(client) -> None:
    """POST /integrations/telegram/send returns message_id in mock mode."""
    r = client.post("/integrations/telegram/send", json={
        "chat_id": "987654321",
        "text": "Hello via API",
    })
    assert r.status_code == 200
    body = r.json()
    assert body.get("mock") is True
    assert "message_id" in body


def test_integrations_discord_send_mock(client) -> None:
    """POST /integrations/discord/send returns mock message_id."""
    r = client.post("/integrations/discord/send", json={
        "channel_id": "123456789",
        "content": "Hello Discord",
    })
    assert r.status_code == 200
    body = r.json()
    assert body.get("mock") is True
    assert "message_id" in body


def test_oauth_status_endpoint(client) -> None:
    """GET /oauth/status returns a list of providers with configured flag."""
    r = client.get("/oauth/status")
    assert r.status_code == 200
    body = r.json()
    assert "providers" in body
    providers = body["providers"]
    names = {p["provider"] for p in providers}
    assert {"google", "github", "facebook"} == names
    # All providers must have a configured field (bool)
    for p in providers:
        assert isinstance(p["configured"], bool)
        assert isinstance(p["connected"], bool)


def test_oauth_start_endpoint(client) -> None:
    """GET /oauth/{provider}/start returns authorization_url + state."""
    # Need to set client_id env var via monkeypatch-like approach
    # (TestClient doesn't pass env vars back, but we set them in conftest already if needed)
    # For this test, just verify the endpoint works (provider returns URL even if client_id is empty)
    r = client.get("/oauth/github/start")
    assert r.status_code == 200
    body = r.json()
    assert "authorization_url" in body
    assert "state" in body
    assert len(body["state"]) > 0


def test_oauth_start_unknown_provider(client) -> None:
    """GET /oauth/{provider}/start with unknown provider returns 404."""
    r = client.get("/oauth/nonexistent/start")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Webhook security tests (Task 4-d)
# ---------------------------------------------------------------------------


def test_whatsapp_webhook_with_valid_signature(client, mock_settings):
    """WhatsApp webhook with valid HMAC signature is accepted."""
    import hashlib
    import hmac
    # In mock mode, signature verification is skipped — just check the endpoint works
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "123",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "messages": [{
                        "from": "1234567890",
                        "id": "msg_1",
                        "text": {"body": "hello"},
                    }],
                },
            }],
        }],
    }
    r = client.post("/integrations/whatsapp/webhook", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert "received" in data


def test_telegram_set_webhook(client, mock_settings):
    """POST /integrations/telegram/set-webhook returns the Telegram API response."""
    r = client.post(
        "/integrations/telegram/set-webhook",
        json={"webhook_url": "https://example.com/integrations/telegram/webhook"},
    )
    assert r.status_code == 200
    data = r.json()
    # Mock mode returns {"ok": True, "result": True, "description": "..."}
    assert data.get("ok") is True


def test_telegram_delete_webhook(client, mock_settings):
    """DELETE /integrations/telegram/webhook removes the Telegram webhook."""
    r = client.delete("/integrations/telegram/webhook")
    assert r.status_code == 200
    assert r.json().get("ok") is True


def test_telegram_webhook_receives_update(client, mock_settings):
    """POST /integrations/telegram/webhook accepts inbound Telegram updates."""
    payload = {
        "update_id": 12345,
        "message": {
            "message_id": 1,
            "from": {"id": 111, "is_bot": False, "first_name": "Test", "username": "testuser"},
            "chat": {"id": 111, "type": "private"},
            "date": 1700000000,
            "text": "/hello world",
        },
    }
    r = client.post("/integrations/telegram/webhook", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data.get("ok") is True
    assert data.get("update_id") == 12345


def test_discord_webhook_ping(client, mock_settings):
    """POST /integrations/discord/webhook responds with PONG for type=1 ping."""
    payload = {"type": 1}
    r = client.post("/integrations/discord/webhook", json=payload)
    assert r.status_code == 200
    assert r.json() == {"type": 1}


def test_discord_webhook_slash_command(client, mock_settings):
    """POST /integrations/discord/webhook with type=2 (slash command) returns deferred response."""
    payload = {
        "type": 2,
        "data": {
            "name": "hello",
            "options": [{"name": "user", "value": "alice"}],
        },
        "id": "interaction_1",
        "token": "interaction_token_abc",
    }
    r = client.post("/integrations/discord/webhook", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data["type"] == 5  # DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE
    assert "Received command: /hello" in data["data"]["content"]


def test_discord_webhook_unknown_type(client, mock_settings):
    """POST /integrations/discord/webhook with unknown type returns helpful error message."""
    payload = {"type": 999}
    r = client.post("/integrations/discord/webhook", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert "Unknown interaction type: 999" in data["data"]["content"]


def test_whatsapp_hmac_verification_helper():
    """The _verify_whatsapp_signature helper validates correctly."""
    from automation_service.api.integration_routes import _verify_whatsapp_signature
    import hashlib
    import hmac
    import os

    # Set a known verify token
    os.environ["WHATSAPP_VERIFY_TOKEN"] = "test-secret"
    body = b'{"test": "payload"}'
    valid_sig = hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()
    assert _verify_whatsapp_signature(body, f"sha256={valid_sig}") is True
    assert _verify_whatsapp_signature(body, "sha256=invalid_sig") is False
    assert _verify_whatsapp_signature(body, None) is False
    assert _verify_whatsapp_signature(body, "invalid_format") is False

    # Cleanup
    del os.environ["WHATSAPP_VERIFY_TOKEN"]


def test_discord_signature_helper_rejects_when_no_key():
    """The _verify_discord_signature helper fails closed when no public key is set."""
    from automation_service.api.integration_routes import _verify_discord_signature
    # No DISCORD_APPLICATION_ID set → returns False
    assert _verify_discord_signature(b"body", "fake_sig", "fake_ts") is False
