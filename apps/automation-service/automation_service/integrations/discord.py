"""Discord Bot API client — master prompt §54.

API base: https://discord.com/api/v10

Secrets read from the credential manager:
- ``discord_bot_token`` (Bot authorization)
- ``discord_application_id`` (for slash-command registration)

When ``settings.mock_mode`` is True, all HTTP calls are skipped and the
client returns deterministic fake responses.
"""

from __future__ import annotations

from typing import Any, Optional

import aiohttp
from loguru import logger
from pydantic import BaseModel, Field

from ..config import settings
from ..security.credentials import get_credential


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class DiscordChannel(BaseModel):
    id: str
    name: str = ""
    type: int = 0
    raw_json: dict[str, Any] = Field(default_factory=dict)


class DiscordGuild(BaseModel):
    id: str
    name: str = ""
    icon: Optional[str] = None
    raw_json: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class DiscordBot:
    """Discord Bot API client (v10)."""

    BASE_URL = "https://discord.com/api/v10"

    def __init__(self) -> None:
        self._token: Optional[str] = get_credential("discord_bot_token")
        self._application_id: Optional[str] = get_credential("discord_application_id")

    @property
    def bot_token(self) -> Optional[str]:
        return self._token

    @property
    def application_id(self) -> Optional[str]:
        return self._application_id

    def is_configured(self) -> bool:
        return bool(self._token)

    # ---------- HTTP helpers ----------

    def _headers(self) -> dict[str, str]:
        if not self._token:
            raise RuntimeError(
                "Discord bot is not configured — set DISCORD_BOT_TOKEN."
            )
        return {
            "Authorization": f"Bot {self._token}",
            "Content-Type": "application/json",
        }

    async def _post_json(self, url: str, body: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=body or {}, headers=self._headers()) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    logger.error("Discord POST {} failed status={} body={}", url, resp.status, text[:300])
                    raise RuntimeError(f"Discord API error: HTTP {resp.status}")
                if not text:
                    return {}
                try:
                    return await resp.json()
                except Exception:
                    return {"raw": text}

    async def _get_json(self, url: str) -> dict[str, Any]:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=self._headers()) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    logger.error("Discord GET {} failed status={} body={}", url, resp.status, text[:300])
                    raise RuntimeError(f"Discord API error: HTTP {resp.status}")
                if not text:
                    return {}
                try:
                    return await resp.json()
                except Exception:
                    return {"raw": text}

    # ---------- public API ----------

    async def send_message(self, channel_id: int, content: str) -> dict[str, Any]:
        """POST /channels/{channel_id}/messages."""
        if settings.mock_mode:
            logger.info("[mock] Discord send_message channel={} len={}", channel_id, len(content))
            return {
                "message_id": f"mock-discord-msg-{abs(hash(str(channel_id) + content)) % 100000:05d}",
                "channel_id": str(channel_id),
                "mock": True,
            }
        if not self.is_configured():
            raise RuntimeError("Discord bot is not configured — set DISCORD_BOT_TOKEN.")
        url = f"{self.BASE_URL}/channels/{channel_id}/messages"
        result = await self._post_json(url, {"content": content})
        return {"message_id": result.get("id", ""), "raw": result}

    async def send_embed(self, channel_id: int, embed: dict[str, Any]) -> dict[str, Any]:
        """POST /channels/{channel_id}/messages with an embed payload."""
        if settings.mock_mode:
            logger.info("[mock] Discord send_embed channel={}", channel_id)
            return {
                "message_id": f"mock-discord-embed-{abs(hash(str(channel_id))) % 100000:05d}",
                "channel_id": str(channel_id),
                "mock": True,
            }
        if not self.is_configured():
            raise RuntimeError("Discord bot is not configured — set DISCORD_BOT_TOKEN.")
        url = f"{self.BASE_URL}/channels/{channel_id}/messages"
        result = await self._post_json(url, {"embeds": [embed]})
        return {"message_id": result.get("id", ""), "raw": result}

    async def get_channel(self, channel_id: int) -> dict[str, Any]:
        """GET /channels/{channel_id}."""
        if settings.mock_mode:
            return {
                "id": str(channel_id),
                "name": f"mock-channel-{channel_id}",
                "type": 0,
                "mock": True,
            }
        if not self.is_configured():
            raise RuntimeError("Discord bot is not configured — set DISCORD_BOT_TOKEN.")
        url = f"{self.BASE_URL}/channels/{channel_id}"
        return await self._get_json(url)

    async def list_guilds(self) -> list[dict[str, Any]]:
        """GET /users/@me/guilds."""
        if settings.mock_mode:
            return [
                {
                    "id": "111111111111111111",
                    "name": "Mock Guild",
                    "icon": None,
                    "mock": True,
                }
            ]
        if not self.is_configured():
            raise RuntimeError("Discord bot is not configured — set DISCORD_BOT_TOKEN.")
        url = f"{self.BASE_URL}/users/@me/guilds"
        result = await self._get_json(url)
        if isinstance(result, list):
            return result
        return [result]

    async def register_slash_command(
        self,
        name: str,
        description: str,
        options: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        """POST /applications/{app_id}/commands — register a global slash command."""
        if settings.mock_mode:
            logger.info("[mock] Discord register_slash_command name={}", name)
            return {
                "id": f"mock-cmd-{abs(hash(name)) % 100000:05d}",
                "name": name,
                "mock": True,
            }
        if not self.is_configured():
            raise RuntimeError("Discord bot is not configured — set DISCORD_BOT_TOKEN.")
        if not self._application_id:
            raise RuntimeError(
                "Discord application_id is not configured — set DISCORD_APPLICATION_ID."
            )
        url = f"{self.BASE_URL}/applications/{self._application_id}/commands"
        body: dict[str, Any] = {
            "name": name,
            "description": description,
            "type": 1,  # CHAT_INPUT command
        }
        if options:
            body["options"] = options
        result = await self._post_json(url, body)
        return {"command_id": result.get("id", ""), "raw": result}


__all__ = ["DiscordChannel", "DiscordGuild", "DiscordBot"]
