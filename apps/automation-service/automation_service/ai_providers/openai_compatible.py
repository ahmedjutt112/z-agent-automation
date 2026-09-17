"""Generic OpenAI-compatible AI provider — master prompt §6 (expanded scope).

Most third-party LLM providers (DeepSeek, Mistral, xAI, Groq, Together,
Fireworks, Cerebras, SambaNova, Perplexity, OpenRouter, Hugging Face,
NVIDIA NIM, Novita, SiliconFlow, Hyperbolic, Lepton, FriendliAI, Baseten,
Modal, Anyscale, Aleph Alpha, Writer, Upstage, Baichuan, Zhipu, Qwen,
Together Computer, Cerebrium) expose an OpenAI-compatible REST API at
``{base_url}/chat/completions`` and ``{base_url}/models``.

This module implements a single concrete :class:`OpenAICompatibleProvider`
that can be reused for every such provider — only the ``base_url`` differs.

Implementation notes:
- Uses ``aiohttp`` (already in deps) with a 30s timeout per HTTP call.
- Secrets are never logged — see :mod:`automation_service.security.credentials`.
- In mock mode (``settings.mock_mode = True``), :meth:`list_models` returns a
  small fake list so tests pass without network access (master prompt §64).
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any, Optional

import aiohttp

from loguru import logger

from .base import AIProvider, AIProviderConfig


# 30-second timeout per HTTP call — per task contract.
_HTTP_TIMEOUT_SECONDS = 30


# ---------------------------------------------------------------------------
# Mock-mode fixtures — keep deterministic for tests
# ---------------------------------------------------------------------------


_MOCK_MODELS = [
    {"id": "gpt-4o-mini", "display_name": "GPT-4o mini", "supports_vision": True},
    {"id": "claude-3-5-sonnet", "display_name": "Claude 3.5 Sonnet", "supports_vision": True},
]


_MOCK_COMPLETION = "Hello! This is a mock response from the OpenAI-compatible provider."


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class OpenAICompatibleProvider(AIProvider):
    """Concrete provider that talks the OpenAI-compatible REST surface.

    Subclasses (or instances configured via :class:`AIProviderConfig`) only
    need to set ``base_url`` and ``api_key`` — everything else uses the same
    HTTP request/response shape.
    """

    name: str = "openai_compatible"

    #: Default base_url — subclasses override this with the provider's URL.
    default_base_url: Optional[str] = None

    def __init__(self, config: AIProviderConfig) -> None:
        super().__init__(config)
        # Resolve base_url: explicit config > class default > empty
        if not self.config.base_url and self.default_base_url:
            self.config.base_url = self.default_base_url

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def _base_url(self) -> str:
        return (self.config.base_url or "").rstrip("/")

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self.config.api_key:
            # OpenAI-compatible auth: Bearer <api_key>
            h["Authorization"] = f"Bearer {self.config.api_key}"
        return h

    @staticmethod
    def _is_mock_mode() -> bool:
        """True when AUTOMATION_MOCK_MODE is set (env-level check so this
        module works whether imported by the automation-service or the zai CLI)."""
        return os.environ.get("AUTOMATION_MOCK_MODE", "true").lower() == "true"

    # ------------------------------------------------------------------
    # complete
    # ------------------------------------------------------------------

    async def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        if self._is_mock_mode():
            logger.debug("OpenAICompatibleProvider.complete mock-mode response (provider={})", self.name)
            return _MOCK_COMPLETION

        url = f"{self._base_url}/chat/completions"
        payload = {
            "model": kwargs.get("model") or self.config.model or "gpt-4o-mini",
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
            logger.error("OpenAICompatibleProvider.complete failed (provider={} err={})", self.name, exc)
            raise

    # ------------------------------------------------------------------
    # list_models — calls GET {base_url}/models
    # ------------------------------------------------------------------

    async def list_models(self) -> list[dict]:
        """Fetch the list of available models.

        Returns a list of dicts shaped like::

            [{"id": "gpt-4o-mini", "display_name": "...", "supports_vision": bool}, ...]

        In mock mode (or when the provider has no API key configured), returns
        a small deterministic fixture so callers can proceed without network.
        """
        if self._is_mock_mode():
            logger.debug("list_models mock-mode response (provider={})", self.name)
            return list(_MOCK_MODELS)

        if not self.config.api_key or not self._base_url:
            logger.warning(
                "list_models skipped (provider={} reason=missing_api_key_or_base_url)", self.name
            )
            return []

        url = f"{self._base_url}/models"
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=_HTTP_TIMEOUT_SECONDS)) as session:
                async with session.get(url, headers=self._headers()) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    # OpenAI-shaped response: {"data": [{"id": "...", ...}, ...]}
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
                    logger.info("list_models ok (provider={} count={})", self.name, len(out))
                    return out
        except Exception as exc:
            logger.error("list_models failed (provider={} err={})", self.name, exc)
            return []

    # ------------------------------------------------------------------
    # complete_with_vision — uses image_url content with base64-encoded data
    # ------------------------------------------------------------------

    async def complete_with_vision(
        self, messages: list[dict[str, str]], image_paths: list[str], **kwargs: Any
    ) -> str:
        if self._is_mock_mode():
            logger.debug("complete_with_vision mock-mode response (provider={})", self.name)
            return _MOCK_COMPLETION

        # Build the OpenAI vision-shaped message list. The last user message
        # gets image_url content parts appended (one per image, base64-encoded).
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

        # Walk the original messages; turn the LAST user message into a
        # multi-part content array (text + images).
        for msg in messages:
            if msg.get("role") == "user" and image_parts:
                text = msg.get("content", "")
                new_messages.append(
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": text}] + image_parts,
                    }
                )
                image_parts = []  # only attach to the first user message
            else:
                new_messages.append(msg)

        # If there were no user messages, append one carrying just the images.
        if image_parts:
            new_messages.append({"role": "user", "content": image_parts})

        # Reuse complete() with the new message list. Most OpenAI-compatible
        # providers accept the vision content block shape natively.
        return await self.complete(new_messages, **kwargs)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _guess_mime(suffix: str) -> str:
    """Map a file extension to a MIME type for the data URL."""
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }.get(suffix, "application/octet-stream")


__all__ = ["OpenAICompatibleProvider"]
