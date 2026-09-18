"""WhatsApp Business API client (Cloud API v18.0) — master prompt §54.

Endpoints:
- POST https://graph.facebook.com/v18.0/{phone_number_id}/messages
- Webhook verification uses plain GET with hub.mode / hub.verify_token /
  hub.challenge query params.

Secrets are read from the credential manager:
- ``whatsapp_business_token`` (Bearer)
- ``whatsapp_phone_number_id`` (path param)
- ``whatsapp_verify_token`` (webhook verification)

When ``settings.mock_mode`` is True, all HTTP calls are skipped and the
client returns deterministic fake responses.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import aiohttp
from loguru import logger
from pydantic import BaseModel, Field

from ..config import settings
from ..security.credentials import get_credential


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class WhatsAppMessage(BaseModel):
    """A single inbound WhatsApp message parsed from a webhook payload."""

    from_: str = Field(..., alias="from")
    to: str
    text: str = ""
    timestamp: Optional[datetime] = None
    message_id: str = ""
    raw_json: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class WhatsAppClient:
    """WhatsApp Business Cloud API client."""

    BASE_URL = "https://graph.facebook.com/v18.0"

    def __init__(self) -> None:
        self._token: Optional[str] = get_credential("whatsapp_business_token")
        self._phone_number_id: Optional[str] = get_credential("whatsapp_phone_number_id")
        self._verify_token: Optional[str] = get_credential("whatsapp_verify_token")

    @property
    def token(self) -> Optional[str]:
        return self._token

    @property
    def phone_number_id(self) -> Optional[str]:
        return self._phone_number_id

    @property
    def verify_token(self) -> Optional[str]:
        return self._verify_token

    def is_configured(self) -> bool:
        return bool(self._token) and bool(self._phone_number_id)

    # ---------- HTTP helpers ----------

    async def _post(self, url: str, json_body: dict[str, Any]) -> dict[str, Any]:
        timeout = aiohttp.ClientTimeout(total=30)
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=json_body, headers=headers) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    logger.error("WhatsApp POST {} failed status={} body={}", url, resp.status, text[:300])
                    raise RuntimeError(f"WhatsApp API error: HTTP {resp.status}")
                try:
                    return await resp.json()
                except Exception:
                    return {"raw": text}

    # ---------- public API ----------

    async def send_text(self, to: str, message: str) -> dict[str, Any]:
        """Send a plain text message to ``to`` (international format, no +)."""
        if settings.mock_mode:
            logger.info("[mock] WhatsApp send_text to={} msg_len={}", to, len(message))
            return {
                "message_id": f"mock-wa-msg-{abs(hash(to + message)) % 100000:05d}",
                "to": to,
                "mock": True,
            }
        if not self.is_configured():
            raise RuntimeError(
                "WhatsApp is not configured — set WHATSAPP_BUSINESS_TOKEN "
                "and WHATSAPP_PHONE_NUMBER_ID."
            )
        url = f"{self.BASE_URL}/{self._phone_number_id}/messages"
        body = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"body": message},
        }
        result = await self._post(url, body)
        # Extract the message_id from the standard WhatsApp response shape
        msg_id = ""
        if isinstance(result, dict):
            messages = result.get("messages") or []
            if messages and isinstance(messages, list):
                msg_id = messages[0].get("id", "")
        return {"message_id": msg_id, "raw": result}

    async def send_template(
        self, to: str, template_name: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Send a template message.

        ``params`` may contain ``language`` (default ``en_US``) and
        ``components`` (a list of header/body/button components).
        """
        if settings.mock_mode:
            logger.info(
                "[mock] WhatsApp send_template to={} name={}", to, template_name
            )
            return {
                "message_id": f"mock-wa-tpl-{abs(hash(to + template_name)) % 100000:05d}",
                "to": to,
                "template": template_name,
                "mock": True,
            }
        if not self.is_configured():
            raise RuntimeError(
                "WhatsApp is not configured — set WHATSAPP_BUSINESS_TOKEN "
                "and WHATSAPP_PHONE_NUMBER_ID."
            )
        url = f"{self.BASE_URL}/{self._phone_number_id}/messages"
        body = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": params.get("language", "en_US")},
                "components": params.get("components", []),
            },
        }
        result = await self._post(url, body)
        msg_id = ""
        if isinstance(result, dict):
            messages = result.get("messages") or []
            if messages and isinstance(messages, list):
                msg_id = messages[0].get("id", "")
        return {"message_id": msg_id, "raw": result}

    def verify_webhook(self, mode: str, token: str, challenge: str) -> Optional[str]:
        """Verify the WhatsApp webhook verification request.

        Returns the ``challenge`` string to echo back, or ``None`` if the
        verification fails (caller should return 403).
        """
        if mode == "subscribe" and token == (self._verify_token or ""):
            return challenge
        return None

    def receive_webhook(self, payload: dict[str, Any]) -> list[WhatsAppMessage]:
        """Parse an inbound webhook payload into :class:`WhatsAppMessage`s."""
        out: list[WhatsAppMessage] = []
        if not isinstance(payload, dict):
            return out
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                if value.get("messaging_product") != "whatsapp":
                    continue
                phone_number_id = value.get("metadata", {}).get("phone_number_id", "")
                for msg in value.get("messages", []):
                    text = ""
                    if msg.get("type") == "text":
                        text = msg.get("text", {}).get("body", "")
                    ts_str = msg.get("timestamp")
                    ts: Optional[datetime] = None
                    if ts_str:
                        try:
                            ts = datetime.fromtimestamp(int(ts_str), tz=timezone.utc)
                        except Exception:
                            ts = None
                    out.append(
                        WhatsAppMessage(
                            **{"from": msg.get("from", "")},
                            to=phone_number_id,
                            text=text,
                            timestamp=ts,
                            message_id=msg.get("id", ""),
                            raw_json=msg,
                        )
                    )
        return out


__all__ = ["WhatsAppMessage", "WhatsAppClient"]
