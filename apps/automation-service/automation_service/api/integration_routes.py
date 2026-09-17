"""Integration HTTP routes — master prompt §54.

Endpoints (mounted under ``/integrations`` in main.py):
- ``GET /integrations`` — list all configured integrations with status.
- ``POST /integrations/email/send`` — body: {to, subject, body, html?}.
- ``GET /integrations/email/inbox`` — query: limit (default 10).
- ``POST /integrations/whatsapp/send-text`` — body: {to, message}.
- ``POST /integrations/whatsapp/webhook`` — receives WhatsApp webhooks (with
  X-Hub-Signature-256 HMAC verification).
- ``GET /integrations/whatsapp/verify`` — WhatsApp webhook verification.
- ``POST /integrations/telegram/send`` — body: {chat_id, text, parse_mode?}.
- ``POST /integrations/telegram/set-webhook`` — body: {webhook_url}.
- ``DELETE /integrations/telegram/webhook`` — removes Telegram webhook.
- ``POST /integrations/telegram/webhook`` — receives Telegram updates.
- ``POST /integrations/discord/send`` — body: {channel_id, content}.
- ``POST /integrations/discord/webhook`` — Discord interactions endpoint
  (slash command handler; verifies Ed25519 signature).

All POST routes (except the public webhook receivers) require the IPC bearer
token via the ``_verify_ipc_token`` dependency.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from loguru import logger
from pydantic import BaseModel, Field

from ..config import settings
from ..integrations.email_client import EmailClient
from ..integrations.whatsapp import WhatsAppClient
from ..integrations.telegram import TelegramBot
from ..integrations.discord import DiscordBot
from ..integrations.oauth import OAUTH_PROVIDERS, get_oauth_provider
from ..security.credentials import get_credential


router = APIRouter()


# ---------------------------------------------------------------------------
# Auth dependency (lazy to avoid circular import)
# ---------------------------------------------------------------------------


async def _verify_ipc_token(authorization: str | None = None) -> None:
    from ..main import verify_ipc_token
    await verify_ipc_token(authorization)


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class EmailSendRequest(BaseModel):
    to: str
    subject: str
    body: str
    html: bool = False


class WhatsAppSendRequest(BaseModel):
    to: str
    message: str


class TelegramSendRequest(BaseModel):
    chat_id: str | int
    text: str
    parse_mode: str = "HTML"


class DiscordSendRequest(BaseModel):
    channel_id: str | int
    content: str


class TelegramWebhookRequest(BaseModel):
    webhook_url: str


class DiscordInteraction(BaseModel):
    """Discord slash-command interaction payload (application/json)."""
    type: int  # 1=PING, 2=APPLICATION_COMMAND, 3=MESSAGE_COMPONENT
    data: dict[str, Any] | None = None
    id: str | None = None
    token: str | None = None  # interaction token (for followups)


# ---------------------------------------------------------------------------
# HMAC verification helpers
# ---------------------------------------------------------------------------


def _verify_whatsapp_signature(raw_body: bytes, signature_header: str | None) -> bool:
    """Verify the X-Hub-Signature-256 header against the app's verify token.

    WhatsApp Cloud API signs webhook POST bodies with HMAC-SHA256 using the
    app's WHATSAPP_VERIFY_TOKEN as the secret (App Secret). We compute the
    expected signature and compare in constant time to prevent timing attacks.
    """
    if not signature_header:
        return False
    if not signature_header.startswith("sha256="):
        return False
    expected_sig = signature_header.removeprefix("sha256=")

    app_secret = get_credential("whatsapp_verify_token") or "default-secret"
    computed = hmac.new(
        app_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(computed, expected_sig)


def _verify_discord_signature(
    raw_body: bytes,
    signature: str | None,
    timestamp: str | None,
) -> bool:
    """Verify Discord interactions webhook signature (Ed25519 over timestamp + body).

    Discord signs every interaction with the bot's public key. We use
    PyNaCl if available; otherwise we fail closed (reject the request).

    Master prompt §55: never accept unsigned interactions.
    """
    if not signature or not timestamp:
        return False
    public_key = get_credential("discord_application_id")
    if not public_key:
        return False
    try:
        from nacl.signing import VerifyKey  # type: ignore
        from nacl.exceptions import BadSignatureError  # type: ignore

        verify_key = VerifyKey(bytes.fromhex(public_key))
        verify_key.verify(f"{timestamp}{raw_body.decode('utf-8')}".encode(), bytes.fromhex(signature))
        return True
    except ImportError:
        # PyNaCl not installed — fail closed
        logger.warning("PyNaCl not installed; rejecting Discord interaction. Install with: pip install pynacl")
        return False
    except (BadSignatureError, ValueError, Exception) as exc:
        logger.warning("Discord signature verification failed: {}", exc)
        return False


# ---------------------------------------------------------------------------
# GET /integrations — list all
# ---------------------------------------------------------------------------


@router.get("", dependencies=[Depends(_verify_ipc_token)])
async def list_integrations() -> dict[str, Any]:
    """List all configured integrations with their status.

    Status values: ``configured`` (credentials present), ``missing_credentials``,
    or ``connected`` (only for OAuth — checks the api_credentials table).
    """
    oauth_status: list[dict[str, Any]] = []
    for name in sorted(OAUTH_PROVIDERS.keys()):
        provider = get_oauth_provider(name)
        configured = provider.is_configured()
        oauth_status.append(
            {
                "name": name,
                "category": "oauth",
                "configured": configured,
                "status": "configured" if configured else "missing_credentials",
            }
        )

    # Email
    email = EmailClient()
    email_configured = email.is_configured()
    email_status = {
        "name": "email",
        "category": "messaging",
        "configured": email_configured,
        "status": "configured" if email_configured else "missing_credentials",
    }

    # WhatsApp
    whatsapp = WhatsAppClient()
    wa_configured = whatsapp.is_configured()
    whatsapp_status = {
        "name": "whatsapp",
        "category": "messaging",
        "configured": wa_configured,
        "status": "configured" if wa_configured else "missing_credentials",
    }

    # Telegram
    telegram = TelegramBot()
    tg_configured = telegram.is_configured()
    telegram_status = {
        "name": "telegram",
        "category": "messaging",
        "configured": tg_configured,
        "status": "configured" if tg_configured else "missing_credentials",
    }

    # Discord
    discord = DiscordBot()
    dc_configured = discord.is_configured()
    discord_status = {
        "name": "discord",
        "category": "messaging",
        "configured": dc_configured,
        "status": "configured" if dc_configured else "missing_credentials",
    }

    return {
        "integrations": oauth_status + [email_status, whatsapp_status, telegram_status, discord_status],
    }


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------


@router.post("/email/send", dependencies=[Depends(_verify_ipc_token)])
async def email_send(req: EmailSendRequest) -> dict[str, Any]:
    client = EmailClient()
    try:
        result = client.send(req.to, req.subject, req.body, html=req.html)
    except Exception as exc:
        logger.error("Email send failed: {}", exc)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc))
    return result


@router.get("/email/inbox", dependencies=[Depends(_verify_ipc_token)])
async def email_inbox(limit: int = Query(10, ge=1, le=100)) -> dict[str, Any]:
    client = EmailClient()
    try:
        messages = client.receive_inbox(limit=limit)
    except Exception as exc:
        logger.error("Email inbox fetch failed: {}", exc)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc))
    return {"messages": [m.model_dump(by_alias=True) for m in messages]}


# ---------------------------------------------------------------------------
# WhatsApp
# ---------------------------------------------------------------------------


@router.post("/whatsapp/send-text", dependencies=[Depends(_verify_ipc_token)])
async def whatsapp_send_text(req: WhatsAppSendRequest) -> dict[str, Any]:
    client = WhatsAppClient()
    try:
        result = await client.send_text(req.to, req.message)
    except Exception as exc:
        logger.error("WhatsApp send_text failed: {}", exc)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc))
    return result


@router.get("/whatsapp/verify")
async def whatsapp_verify(
    hub_mode: str = Query("", alias="hub.mode"),
    hub_verify_token: str = Query("", alias="hub.verify_token"),
    hub_challenge: str = Query("", alias="hub.challenge"),
) -> str:
    """WhatsApp webhook verification — public endpoint.

    Returns the ``hub.challenge`` value if verification succeeds; otherwise
    raises 403.
    """
    client = WhatsAppClient()
    challenge = client.verify_webhook(hub_mode, hub_verify_token, hub_challenge)
    if challenge is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Webhook verification failed")
    return challenge


@router.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request) -> dict[str, Any]:
    """Receive an inbound WhatsApp webhook payload with HMAC verification.

    Master prompt §55: verify the X-Hub-Signature-256 header to ensure the
    payload is genuinely from Meta. If verification fails, return 403.

    In mock mode (settings.mock_mode=True), signature verification is skipped
    so tests and local development can use unverified payloads.
    """
    raw_body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")

    if not settings.mock_mode:
        if not _verify_whatsapp_signature(raw_body, signature):
            logger.warning("WhatsApp webhook signature verification failed")
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid signature")

    try:
        payload: dict[str, Any] = await request.json()
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid JSON: {exc}")

    client = WhatsAppClient()
    messages = client.receive_webhook(payload)
    for m in messages:
        logger.info(
            "WhatsApp inbound from={} text={}", m.from_, m.text[:50] if m.text else ""
        )
    return {"received": len(messages)}


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------


@router.post("/telegram/send", dependencies=[Depends(_verify_ipc_token)])
async def telegram_send(req: TelegramSendRequest) -> dict[str, Any]:
    client = TelegramBot()
    try:
        result = await client.send_text(req.chat_id, req.text, parse_mode=req.parse_mode)
    except Exception as exc:
        logger.error("Telegram send failed: {}", exc)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc))
    return result


@router.post("/telegram/set-webhook", dependencies=[Depends(_verify_ipc_token)])
async def telegram_set_webhook(req: TelegramWebhookRequest) -> dict[str, Any]:
    """Register a webhook URL with Telegram for inbound messages.

    Telegram will POST updates to {webhook_url} — typically you'd point this
    at https://your-domain/integrations/telegram/webhook.
    """
    client = TelegramBot()
    try:
        result = await client.set_webhook(req.webhook_url)
    except Exception as exc:
        logger.error("Telegram setWebhook failed: {}", exc)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc))
    return result


@router.delete("/telegram/webhook", dependencies=[Depends(_verify_ipc_token)])
async def telegram_delete_webhook() -> dict[str, Any]:
    """Remove the Telegram webhook (revert to long-polling getUpdates)."""
    client = TelegramBot()
    try:
        result = await client.delete_webhook()
    except Exception as exc:
        logger.error("Telegram deleteWebhook failed: {}", exc)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc))
    return result


@router.post("/telegram/webhook")
async def telegram_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    """Receive an inbound Telegram update via webhook.

    Public endpoint — Telegram doesn't sign webhook payloads with a shared
    secret by default. For production, you should:
    1. Use a long unguessable URL (e.g. /integrations/telegram/webhook/{secret_token})
    2. Or set the `secret_token` parameter in setWebhook and verify it via
       the X-Telegram-Bot-Api-Secret-Token header.
    """
    # Telegram raw payload has nested message.from/chat/text. We normalize it
    # into TelegramUpdate via the bot's static _normalize_update method
    # (which extracts update_id, chat_id, from_user, text from the raw payload).
    from ..integrations.telegram import TelegramUpdate
    client = TelegramBot()
    try:
        update = TelegramBot._normalize_update(payload)
        if update.text:
            cmd, args = client.parse_command(update.text)
            logger.info(
                "Telegram inbound chat={} from={} text={} cmd={} args={}",
                update.chat_id,
                update.from_user,
                update.text[:50],
                cmd,
                args,
            )
        return {"ok": True, "update_id": update.update_id}
    except Exception as exc:
        logger.error("Telegram webhook processing failed: {}", exc)
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Discord
# ---------------------------------------------------------------------------


@router.post("/discord/send", dependencies=[Depends(_verify_ipc_token)])
async def discord_send(req: DiscordSendRequest) -> dict[str, Any]:
    client = DiscordBot()
    try:
        result = await client.send_message(int(req.channel_id), req.content)
    except Exception as exc:
        logger.error("Discord send failed: {}", exc)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc))
    return result


@router.post("/discord/webhook")
async def discord_webhook(request: Request) -> dict[str, Any]:
    """Discord interactions endpoint — receives slash commands and other events.

    Master prompt §55: verify the Ed25519 signature on every request using
    the bot's public key. Unverified requests get 401.

    Returns:
    - PONG (type 1) for ping/verification requests
    - A deferred response for APPLICATION_COMMAND (type 2) interactions
    """
    raw_body = await request.body()
    signature = request.headers.get("X-Signature-Ed25519")
    timestamp = request.headers.get("X-Signature-Timestamp")

    if not settings.mock_mode:
        if not _verify_discord_signature(raw_body, signature, timestamp):
            logger.warning("Discord interaction signature verification failed")
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid request signature")

    try:
        payload: dict[str, Any] = await request.json()
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid JSON: {exc}")

    interaction_type = payload.get("type", 0)

    # Discord interaction types
    if interaction_type == 1:
        # PING — Discord sends this when you register the webhook URL
        return {"type": 1}
    elif interaction_type == 2:
        # APPLICATION_COMMAND — slash command invocation
        data = payload.get("data", {})
        cmd_name = data.get("name", "unknown")
        cmd_options = {opt["name"]: opt["value"] for opt in data.get("options", [])}
        logger.info("Discord slash command: {} args={}", cmd_name, cmd_options)

        # Acknowledge with a deferred message (we have 15 min to follow up via
        # the original interaction token)
        return {
            "type": 5,  # DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE
            "data": {"content": f"Received command: /{cmd_name}"},
        }
    elif interaction_type == 3:
        # MESSAGE_COMPONENT — button/select menu interaction
        logger.info("Discord message component interaction: {}", payload.get("data", {}))
        return {"type": 6}  # DEFERRED_UPDATE_MESSAGE
    elif interaction_type == 4:
        # APPLICATION_COMMAND_AUTOCOMPLETE
        return {"type": 8}  # APPLICATION_COMMAND_AUTOCOMPLETE_RESULT
    elif interaction_type == 5:
        # MODAL_SUBMIT
        return {"type": 4, "data": {"content": "Modal received"}}
    else:
        logger.warning("Discord unknown interaction type: {}", interaction_type)
        return {"type": 4, "data": {"content": f"Unknown interaction type: {interaction_type}"}}


__all__ = ["router"]
