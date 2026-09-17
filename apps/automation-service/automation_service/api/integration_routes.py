"""Integration HTTP routes — master prompt §54.

Endpoints (mounted under ``/integrations`` in main.py):
- ``GET /integrations`` — list all configured integrations with status.
- ``POST /integrations/email/send`` — body: {to, subject, body, html?}.
- ``GET /integrations/email/inbox`` — query: limit (default 10).
- ``POST /integrations/whatsapp/send-text`` — body: {to, message}.
- ``POST /integrations/whatsapp/webhook`` — receives WhatsApp webhooks (no
  IPC token — relies on the verify_token instead).
- ``GET /integrations/whatsapp/verify`` — WhatsApp webhook verification.
- ``POST /integrations/telegram/send`` — body: {chat_id, text, parse_mode?}.
- ``POST /integrations/discord/send`` — body: {channel_id, content}.

All POST routes (except the WhatsApp webhook receiver) require the IPC bearer
token via the ``_verify_ipc_token`` dependency.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from loguru import logger
from pydantic import BaseModel, Field

from ..config import settings
from ..integrations.email_client import EmailClient
from ..integrations.whatsapp import WhatsAppClient
from ..integrations.telegram import TelegramBot
from ..integrations.discord import DiscordBot
from ..integrations.oauth import OAUTH_PROVIDERS, get_oauth_provider


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
async def whatsapp_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    """Receive an inbound WhatsApp webhook payload.

    Public endpoint — relies on the provider having verified the webhook URL
    via ``/whatsapp/verify`` (which checks the verify_token). Payloads are
    parsed for inbound messages and logged for downstream processing.
    """
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


__all__ = ["router"]
