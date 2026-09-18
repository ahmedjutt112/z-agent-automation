"""Notification tools — master prompt §54 + §8.

Wraps the messaging integration clients as Tool subclasses so the AI planner
can call them. Each tool falls back to mock mode when ``settings.mock_mode``
is True (no real messages are sent).

Registered tools:
- ``notify.email``    (risk=medium, permission=allow_once)
- ``notify.whatsapp`` (risk=medium, permission=allow_once)
- ``notify.telegram`` (risk=low,    permission=allow_once)
- ``notify.discord``  (risk=low,    permission=allow_once)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..engine.tool_registry import register_tool, Tool
from ..models import ActionResult, StepStatus
from ..config import settings


@register_tool
class NotificationEmailTool(Tool):
    name = "notify.email"
    description = "Send an email via the configured SMTP account."
    permission_level = "allow_once"
    risk_level = "medium"
    timeout_ms = 30_000
    rollback_strategy = "Email cannot be unsent — confirm recipient before sending."
    verification_strategy = "Check SMTP success return code."
    input_schema = {
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "Recipient email (comma-separated list OK)."},
            "subject": {"type": "string"},
            "body": {"type": "string"},
            "html": {"type": "boolean", "default": False},
        },
        "required": ["to", "subject", "body"],
    }

    async def execute(self, args: dict[str, Any]) -> ActionResult:
        start = datetime.now(timezone.utc)
        try:
            from ..integrations.email_client import EmailClient

            client = EmailClient()
            result = client.send(
                to=args["to"],
                subject=args["subject"],
                body=args["body"],
                html=bool(args.get("html", False)),
            )
            return ActionResult(
                tool=self.name,
                status=StepStatus.COMPLETED,
                output=result,
                finished_at=datetime.now(timezone.utc),
                duration_ms=int((datetime.now(timezone.utc) - start).total_seconds() * 1000),
            )
        except Exception as exc:
            return ActionResult(
                tool=self.name,
                status=StepStatus.FAILED,
                error=str(exc),
                finished_at=datetime.now(timezone.utc),
                duration_ms=int((datetime.now(timezone.utc) - start).total_seconds() * 1000),
            )


@register_tool
class NotificationWhatsAppTool(Tool):
    name = "notify.whatsapp"
    description = "Send a WhatsApp Business text message."
    permission_level = "allow_once"
    risk_level = "medium"
    timeout_ms = 30_000
    rollback_strategy = "WhatsApp messages cannot be unsent."
    verification_strategy = "Check WhatsApp API response for message_id."
    input_schema = {
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "Phone number in international format, no '+'."},
            "message": {"type": "string"},
        },
        "required": ["to", "message"],
    }

    async def execute(self, args: dict[str, Any]) -> ActionResult:
        start = datetime.now(timezone.utc)
        try:
            from ..integrations.whatsapp import WhatsAppClient

            client = WhatsAppClient()
            result = await client.send_text(args["to"], args["message"])
            return ActionResult(
                tool=self.name,
                status=StepStatus.COMPLETED,
                output=result,
                finished_at=datetime.now(timezone.utc),
                duration_ms=int((datetime.now(timezone.utc) - start).total_seconds() * 1000),
            )
        except Exception as exc:
            return ActionResult(
                tool=self.name,
                status=StepStatus.FAILED,
                error=str(exc),
                finished_at=datetime.now(timezone.utc),
                duration_ms=int((datetime.now(timezone.utc) - start).total_seconds() * 1000),
            )


@register_tool
class NotificationTelegramTool(Tool):
    name = "notify.telegram"
    description = "Send a Telegram message via the configured bot."
    permission_level = "allow_once"
    risk_level = "low"
    timeout_ms = 30_000
    rollback_strategy = "Telegram messages cannot be unsent."
    verification_strategy = "Check Telegram API response for message_id."
    input_schema = {
        "type": "object",
        "properties": {
            "chat_id": {"type": "string", "description": "Numeric chat ID or @channelname."},
            "text": {"type": "string"},
            "parse_mode": {"type": "string", "enum": ["HTML", "Markdown", "MarkdownV2"], "default": "HTML"},
        },
        "required": ["chat_id", "text"],
    }

    async def execute(self, args: dict[str, Any]) -> ActionResult:
        start = datetime.now(timezone.utc)
        try:
            from ..integrations.telegram import TelegramBot

            client = TelegramBot()
            result = await client.send_text(
                args["chat_id"], args["text"],
                parse_mode=args.get("parse_mode", "HTML"),
            )
            return ActionResult(
                tool=self.name,
                status=StepStatus.COMPLETED,
                output=result,
                finished_at=datetime.now(timezone.utc),
                duration_ms=int((datetime.now(timezone.utc) - start).total_seconds() * 1000),
            )
        except Exception as exc:
            return ActionResult(
                tool=self.name,
                status=StepStatus.FAILED,
                error=str(exc),
                finished_at=datetime.now(timezone.utc),
                duration_ms=int((datetime.now(timezone.utc) - start).total_seconds() * 1000),
            )


@register_tool
class NotificationDiscordTool(Tool):
    name = "notify.discord"
    description = "Send a Discord message to a channel via the configured bot."
    permission_level = "allow_once"
    risk_level = "low"
    timeout_ms = 30_000
    rollback_strategy = "Discord messages can be deleted via DELETE /channels/{id}/messages/{mid}."
    verification_strategy = "Check Discord API response for message_id."
    input_schema = {
        "type": "object",
        "properties": {
            "channel_id": {"type": "string", "description": "Discord channel ID (numeric)."},
            "content": {"type": "string"},
        },
        "required": ["channel_id", "content"],
    }

    async def execute(self, args: dict[str, Any]) -> ActionResult:
        start = datetime.now(timezone.utc)
        try:
            from ..integrations.discord import DiscordBot

            client = DiscordBot()
            result = await client.send_message(int(args["channel_id"]), args["content"])
            return ActionResult(
                tool=self.name,
                status=StepStatus.COMPLETED,
                output=result,
                finished_at=datetime.now(timezone.utc),
                duration_ms=int((datetime.now(timezone.utc) - start).total_seconds() * 1000),
            )
        except Exception as exc:
            return ActionResult(
                tool=self.name,
                status=StepStatus.FAILED,
                error=str(exc),
                finished_at=datetime.now(timezone.utc),
                duration_ms=int((datetime.now(timezone.utc) - start).total_seconds() * 1000),
            )


__all__ = [
    "NotificationEmailTool",
    "NotificationWhatsAppTool",
    "NotificationTelegramTool",
    "NotificationDiscordTool",
]
