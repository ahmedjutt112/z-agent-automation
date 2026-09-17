"""Vercel AI Gateway provider — single API key routing to ALL 50 providers.

The Vercel AI Gateway (https://ai-gateway.vercel.sh/v1) is an aggregator
that exposes a single OpenAI-compatible REST surface. Model names are
prefixed with the underlying provider, e.g.::

    openai/gpt-4o
    anthropic/claude-3-5-sonnet
    meta/llama-3.1-70b-instruct
    google/gemini-1.5-flash

A single ``VERCEL_AI_GATEWAY_KEY`` therefore unlocks every provider on the
master list — the gateway handles the per-provider auth internally.

Implementation notes:
- Uses ``aiohttp`` with a 30s timeout per HTTP call (per task contract).
- ``VERCEL_AI_GATEWAY_URL`` env var overrides the default base URL.
- ``VERCEL_AI_GATEWAY_KEY`` credential is resolved via
  :func:`automation_service.security.credentials.get_credential`.
- Mock mode (``AUTOMATION_MOCK_MODE=true``) returns fixtures without HTTP.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any, Optional

import aiohttp

from loguru import logger

from .base import AIProvider, AIProviderConfig


# Defaults
_DEFAULT_BASE_URL = "https://ai-gateway.vercel.sh/v1"
_HTTP_TIMEOUT_SECONDS = 30


# Mock-mode fixtures — a representative slice of what the gateway would return.
_MOCK_MODELS = [
    {"id": "openai/gpt-4o", "display_name": "OpenAI GPT-4o", "supports_vision": True},
    {"id": "openai/gpt-4o-mini", "display_name": "OpenAI GPT-4o mini", "supports_vision": True},
    {"id": "anthropic/claude-3-5-sonnet", "display_name": "Anthropic Claude 3.5 Sonnet", "supports_vision": True},
    {"id": "meta/llama-3.1-70b-instruct", "display_name": "Meta Llama 3.1 70B Instruct", "supports_vision": False},
    {"id": "google/gemini-1.5-flash", "display_name": "Google Gemini 1.5 Flash", "supports_vision": True},
]

_MOCK_COMPLETION = "Hello! This is a mock response from the Vercel AI Gateway."


class VercelAIGatewayProvider(AIProvider):
    """Routes to ALL 50 providers via the Vercel AI Gateway.

    Construct this provider with an :class:`AIProviderConfig` whose ``model``
    field is the gateway-prefixed model name (e.g. ``"openai/gpt-4o"``).
    The API key is auto-loaded from ``VERCEL_AI_GATEWAY_KEY`` if not present
    on the config.
    """

    name: str = "vercel_gateway"

    def __init__(self, config: AIProviderConfig) -> None:
        super().__init__(config)
        # Resolve base_url: config > env > default
        if not self.config.base_url:
            self.config.base_url = os.environ.get(
                "VERCEL_AI_GATEWAY_URL", _DEFAULT_BASE_URL
            )
        # Resolve API key: config > credentials manager
        if not self.config.api_key:
            try:
                from ..security.credentials import get_credential
                self.config.api_key = get_credential("vercel_ai_gateway_key")
            except Exception as exc:  # pragma: no cover — defensive
                logger.warning("vercel_gateway: could not load credential ({})", exc)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def _base_url(self) -> str:
        return (self.config.base_url or _DEFAULT_BASE_URL).rstrip("/")

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self.config.api_key:
            h["Authorization"] = f"Bearer {self.config.api_key}"
        return h

    @staticmethod
    def _is_mock_mode() -> bool:
        return os.environ.get("AUTOMATION_MOCK_MODE", "true").lower() == "true"

    # ------------------------------------------------------------------
    # complete
    # ------------------------------------------------------------------

    async def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        if self._is_mock_mode():
            logger.debug("vercel_gateway.complete mock-mode response")
            return _MOCK_COMPLETION

        url = f"{self._base_url}/chat/completions"
        payload = {
            "model": kwargs.get("model") or self.config.model or "openai/gpt-4o-mini",
            "messages": messages,
            "temperature": kwargs.get("temperature", self.config.temperature),
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
        }
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=_HTTP_TIMEOUT_SECONDS)) as session:
                async with session.post(url, json=payload, headers=self._headers()) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"] or ""
        except Exception as exc:
            logger.error("vercel_gateway.complete failed (err={})", exc)
            raise

    # ------------------------------------------------------------------
    # list_models — aggregates ALL underlying providers
    # ------------------------------------------------------------------

    async def list_models(self) -> list[dict]:
        """GET {base_url}/models — the gateway aggregates every provider."""
        if self._is_mock_mode():
            logger.debug("vercel_gateway.list_models mock-mode response (count={})", len(_MOCK_MODELS))
            return list(_MOCK_MODELS)

        if not self.config.api_key:
            logger.warning("vercel_gateway.list_models skipped (reason=missing_api_key)")
            return []

        url = f"{self._base_url}/models"
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=_HTTP_TIMEOUT_SECONDS)) as session:
                async with session.get(url, headers=self._headers()) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    raw_models = data.get("data") if isinstance(data, dict) else data
                    if not isinstance(raw_models, list):
                        return []
                    out: list[dict] = []
                    for m in raw_models:
                        if not isinstance(m, dict):
                            continue
                        model_id = m.get("id") or m.get("name") or ""
                        if not model_id:
                            continue
                        out.append(
                            {
                                "id": model_id,
                                "display_name": m.get("display_name") or model_id,
                                "supports_vision": bool(m.get("supports_vision", False)),
                            }
                        )
                    logger.info("vercel_gateway.list_models ok (count={})", len(out))
                    return out
        except Exception as exc:
            logger.error("vercel_gateway.list_models failed (err={})", exc)
            return []

    # ------------------------------------------------------------------
    # complete_with_vision — same OpenAI-shaped image_url content
    # ------------------------------------------------------------------

    async def complete_with_vision(
        self, messages: list[dict[str, str]], image_paths: list[str], **kwargs: Any
    ) -> str:
        if self._is_mock_mode():
            logger.debug("vercel_gateway.complete_with_vision mock-mode response")
            return _MOCK_COMPLETION

        new_messages: list[dict] = []
        image_parts: list[dict] = []
        for img_path in image_paths:
            try:
                p = Path(img_path)
                if not p.exists():
                    logger.warning("vision image not found, skipping (path={})", img_path)
                    continue
                mime = _guess_mime(p.suffix.lower())
                b64 = base64.b64encode(p.read_bytes()).decode("ascii")
                image_parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                    }
                )
            except Exception as exc:
                logger.error("vision image read failed (path={} err={})", img_path, exc)

        for msg in messages:
            if msg.get("role") == "user" and image_parts:
                text = msg.get("content", "")
                new_messages.append(
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": text}] + image_parts,
                    }
                )
                image_parts = []
            else:
                new_messages.append(msg)

        if image_parts:
            new_messages.append({"role": "user", "content": image_parts})

        return await self.complete(new_messages, **kwargs)


def _guess_mime(suffix: str) -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }.get(suffix, "application/octet-stream")


__all__ = ["VercelAIGatewayProvider"]
