"""Telegram Bot API client — master prompt §54.

API base: https://api.telegram.org/bot{TOKEN}/<method>

Secrets read from the credential manager:
- ``telegram_bot_token`` (the bot token issued by BotFather)

When ``settings.mock_mode`` is True, all HTTP calls are skipped and the
client returns deterministic fake responses.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote

import aiohttp
from loguru import logger
from pydantic import BaseModel, Field

from ..config import settings
from ..security.credentials import get_credential


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class TelegramUpdate(BaseModel):
    """A normalised Telegram update (message-only — edits/callbacks flattened)."""

    update_id: int
    chat_id: str = ""
    from_user: str = ""
    text: str = ""
    received_at: Optional[datetime] = None
    raw_json: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class TelegramBot:
    """Telegram Bot API client."""

    BASE_URL = "https://api.telegram.org"

    def __init__(self) -> None:
        self._token: Optional[str] = get_credential("telegram_bot_token")

    @property
    def bot_token(self) -> Optional[str]:
        return self._token

    def is_configured(self) -> bool:
        return bool(self._token)

    # ---------- HTTP helpers ----------

    def _method_url(self, method: str) -> str:
        if not self._token:
            raise RuntimeError(
                "Telegram bot is not configured — set TELEGRAM_BOT_TOKEN."
            )
        return f"{self.BASE_URL}/bot{self._token}/{method}"

    async def _post_json(self, url: str, json_body: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=json_body or {}) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    logger.error("Telegram POST {} failed status={} body={}", url, resp.status, text[:300])
                    raise RuntimeError(f"Telegram API error: HTTP {resp.status}")
                try:
                    return await resp.json()
                except Exception:
                    return {"raw": text}

    async def _get_json(self, url: str) -> dict[str, Any]:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    logger.error("Telegram GET {} failed status={} body={}", url, resp.status, text[:300])
                    raise RuntimeError(f"Telegram API error: HTTP {resp.status}")
                try:
                    return await resp.json()
                except Exception:
                    return {"raw": text}

    # ---------- public API ----------

    async def send_text(self, chat_id: int | str, text: str, parse_mode: str = "HTML") -> dict[str, Any]:
        """Send a plain text message."""
        if settings.mock_mode:
            logger.info("[mock] Telegram send_text chat={} len={}", chat_id, len(text))
            return {
                "message_id": abs(hash(str(chat_id) + text)) % 1000000,
                "chat_id": str(chat_id),
                "mock": True,
            }
        if not self.is_configured():
            raise RuntimeError(
                "Telegram bot is not configured — set TELEGRAM_BOT_TOKEN."
            )
        body = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        result = await self._post_json(self._method_url("sendMessage"), body)
        msg_id = 0
        if isinstance(result, dict):
            ok = result.get("ok", False)
            if ok and isinstance(result.get("result"), dict):
                msg_id = result["result"].get("message_id", 0)
        return {"message_id": msg_id, "ok": result.get("ok", False) if isinstance(result, dict) else False, "raw": result}

    async def send_photo(self, chat_id: int | str, photo_path: str) -> dict[str, Any]:
        """Upload a photo from local filesystem."""
        if settings.mock_mode:
            logger.info("[mock] Telegram send_photo chat={} path={}", chat_id, photo_path)
            return {"message_id": abs(hash(str(chat_id) + photo_path)) % 1000000, "mock": True}
        if not self.is_configured():
            raise RuntimeError("Telegram bot is not configured — set TELEGRAM_BOT_TOKEN.")
        if not os.path.isfile(photo_path):
            raise FileNotFoundError(f"Photo not found: {photo_path}")
        url = self._method_url("sendPhoto")
        timeout = aiohttp.ClientTimeout(total=60)
        # Use multipart/form-data for file uploads
        async with aiohttp.ClientSession(timeout=timeout) as session:
            with open(photo_path, "rb") as f:
                data = aiohttp.FormData()
                data.add_field("chat_id", str(chat_id))
                data.add_field("photo", f, filename=os.path.basename(photo_path))
                async with session.post(url, data=data) as resp:
                    text = await resp.text()
                    if resp.status >= 400:
                        logger.error("Telegram sendPhoto failed status={} body={}", resp.status, text[:300])
                        raise RuntimeError(f"Telegram sendPhoto failed: HTTP {resp.status}")
                    result = await resp.json()
        msg_id = 0
        if isinstance(result, dict) and isinstance(result.get("result"), dict):
            msg_id = result["result"].get("message_id", 0)
        return {"message_id": msg_id, "ok": result.get("ok", False) if isinstance(result, dict) else False}

    async def send_document(self, chat_id: int | str, document_path: str) -> dict[str, Any]:
        """Upload a file as a document."""
        if settings.mock_mode:
            logger.info("[mock] Telegram send_document chat={} path={}", chat_id, document_path)
            return {"message_id": abs(hash(str(chat_id) + document_path)) % 1000000, "mock": True}
        if not self.is_configured():
            raise RuntimeError("Telegram bot is not configured — set TELEGRAM_BOT_TOKEN.")
        if not os.path.isfile(document_path):
            raise FileNotFoundError(f"Document not found: {document_path}")
        url = self._method_url("sendDocument")
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            with open(document_path, "rb") as f:
                data = aiohttp.FormData()
                data.add_field("chat_id", str(chat_id))
                data.add_field("document", f, filename=os.path.basename(document_path))
                async with session.post(url, data=data) as resp:
                    text = await resp.text()
                    if resp.status >= 400:
                        logger.error("Telegram sendDocument failed status={} body={}", resp.status, text[:300])
                        raise RuntimeError(f"Telegram sendDocument failed: HTTP {resp.status}")
                    result = await resp.json()
        msg_id = 0
        if isinstance(result, dict) and isinstance(result.get("result"), dict):
            msg_id = result["result"].get("message_id", 0)
        return {"message_id": msg_id, "ok": result.get("ok", False) if isinstance(result, dict) else False}

    async def get_updates(self, offset: int = 0) -> list[TelegramUpdate]:
        """Fetch pending updates (long-polling)."""
        if settings.mock_mode:
            return [
                TelegramUpdate(
                    update_id=offset + 1,
                    chat_id="123456789",
                    from_user="mock_user",
                    text="/hello world",
                    received_at=datetime.now(timezone.utc),
                    raw_json={"mock": True},
                )
            ]
        if not self.is_configured():
            raise RuntimeError("Telegram bot is not configured — set TELEGRAM_BOT_TOKEN.")
        url = f"{self._method_url('getUpdates')}?offset={offset}&timeout=0"
        result = await self._get_json(url)
        out: list[TelegramUpdate] = []
        if not isinstance(result, dict) or not result.get("ok"):
            return out
        for upd in result.get("result", []):
            out.append(self._normalize_update(upd))
        return out

    @staticmethod
    def _normalize_update(upd: dict[str, Any]) -> TelegramUpdate:
        """Normalize a raw Telegram update dict into a TelegramUpdate model.

        Handles `message`, `edited_message`, `channel_post`, and `callback_query`.
        Used by both get_updates() and the webhook receiver.
        """
        msg = upd.get("message") or upd.get("edited_message") or upd.get("channel_post") or {}
        # callback_query has its own message subfield
        if not msg and upd.get("callback_query"):
            msg = upd["callback_query"].get("message", {})
        chat_id = msg.get("chat", {}).get("id", "")
        from_info = msg.get("from", {}) or upd.get("callback_query", {}).get("from", {})
        from_user = from_info.get("username") or from_info.get("first_name", "")
        text = msg.get("text", "") or upd.get("callback_query", {}).get("data", "")
        ts = msg.get("date") or upd.get("callback_query", {}).get("message", {}).get("date")
        received = datetime.fromtimestamp(int(ts), tz=timezone.utc) if ts else None
        return TelegramUpdate(
            update_id=upd.get("update_id", 0),
            chat_id=str(chat_id),
            from_user=from_user,
            text=text,
            received_at=received,
            raw_json=upd,
        )

    async def set_webhook(self, url: str) -> dict[str, Any]:
        """Register a webhook URL — Telegram will POST updates there."""
        if settings.mock_mode:
            logger.info("[mock] Telegram set_webhook url={}", url)
            return {"ok": True, "url": url, "mock": True}
        if not self.is_configured():
            raise RuntimeError("Telegram bot is not configured — set TELEGRAM_BOT_TOKEN.")
        body = {"url": url}
        return await self._post_json(self._method_url("setWebhook"), body)

    async def delete_webhook(self) -> dict[str, Any]:
        """Remove the webhook (switches back to long-polling getUpdates)."""
        if settings.mock_mode:
            return {"ok": True, "mock": True}
        if not self.is_configured():
            raise RuntimeError("Telegram bot is not configured — set TELEGRAM_BOT_TOKEN.")
        return await self._post_json(self._method_url("deleteWebhook"), {})

    @staticmethod
    def parse_command(text: str) -> tuple[str, list[str]]:
        """Parse a bot command like ``/cmd arg1 arg2`` -> ``("/cmd", ["arg1", "arg2"])``.

        Returns ``("", [])`` for non-command text.
        """
        if not text or not text.startswith("/"):
            return ("", [])
        parts = text.strip().split()
        return (parts[0], parts[1:])


__all__ = ["TelegramUpdate", "TelegramBot"]
