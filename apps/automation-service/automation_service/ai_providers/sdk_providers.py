"""Real SDK-backed provider implementations — Task 4-c.

This module hosts concrete :class:`AIProvider` subclasses for the providers
that have bespoke (non-OpenAI-compatible) HTTP APIs. The 8 providers in the
task table that ARE OpenAI-compatible (ai21, jina, ai2, lm_studio, meta,
sambanova_cloud, nocipium, nebius) are registered with
:class:`OpenAICompatibleProvider` in :mod:`automation_service.ai_providers.base`
— no extra code is needed here for them.

The 11 providers in this file are:

  - :class:`CohereProvider`        — https://api.cohere.ai/v1/chat
  - :class:`VoyageProvider`       — embeddings only (POST /v1/embeddings)
  - :class:`StabilityProvider`     — image generation (POST /v1/generation/.../text-to-image)
  - :class:`ReplicateProvider`     — POST /v1/predictions
  - :class:`CloudflareProvider`    — POST /client/v4/accounts/{acct}/ai/run/{model}
  - :class:`AWSBedrockProvider`    — boto3 if available, else manual SigV4
  - :class:`GoogleVertexProvider`  — google.auth if available, else RuntimeError
  - :class:`AzureAIProvider`       — raw HTTP against the Azure OpenAI REST surface
  - :class:`IBMWatsonxProvider`    — IBM IAM token + /ml/v1/text/chat
  - :class:`DatabricksProvider`    — POST /serving-endpoints/{name}/invocations

(amazon_nova reuses :class:`AWSBedrockProvider` — same Bedrock runtime API.)

Implementation rules (per task contract):
  - All HTTP via ``aiohttp`` (already in deps) with a 30-second timeout.
  - No new pip dependencies. AWS SigV4 uses stdlib (hmac, hashlib, urllib,
    base64) as the fallback when ``boto3`` is unavailable.
  - Mock mode (``AUTOMATION_MOCK_MODE=true``) short-circuits every HTTP
    method with a deterministic fixture so tests pass without network.
  - Construction NEVER raises — only ``complete()`` / ``embed()`` /
    ``generate_image()`` may raise (and only when actually invoked outside
    mock mode without the required dependency or credential).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import aiohttp

from loguru import logger

from .base import AIProvider, AIProviderConfig


# 30s per HTTP call — per task contract.
_HTTP_TIMEOUT_SECONDS = 30


# ---------------------------------------------------------------------------
# Mock-mode fixtures — keep deterministic so unit tests are stable
# ---------------------------------------------------------------------------

_MOCK_CHAT = "[mock-mode chat response]"
_MOCK_EMBEDDING = [0.0, 0.0, 0.0, 0.0]
_MOCK_IMAGE_URL = "https://mock.local/stable-image.png"


def _is_mock_mode() -> bool:
    """True when AUTOMATION_MOCK_MODE is set (env-level check so this module
    works whether imported by the automation-service or the zai CLI)."""
    return os.environ.get("AUTOMATION_MOCK_MODE", "true").lower() == "true"


def _require_registry_info(provider_name: str) -> dict:
    """Look up a provider's info from the top-level ai_providers.registry.

    Returns ``{}`` if the registry is not importable (defensive).
    """
    try:
        automation_root = str(Path(__file__).resolve().parents[3])
        if automation_root not in sys.path:
            sys.path.insert(0, automation_root)
        from ai_providers import registry as _reg  # type: ignore
        return _reg.PROVIDERS.get(provider_name, {}) or {}
    except Exception:
        return {}


def _resolve_api_key(provider: AIProvider, env_key_name: Optional[str]) -> Optional[str]:
    """Resolve the API key: config > env var > credential manager."""
    if provider.config.api_key:
        return provider.config.api_key
    if env_key_name:
        try:
            from ..security.credentials import get_credential
            return get_credential(env_key_name)
        except Exception:
            pass
        env_var = env_key_name.upper().replace("-", "_").replace(".", "_")
        return os.environ.get(env_var)
    return None


def _aiohttp_timeout() -> aiohttp.ClientTimeout:
    return aiohttp.ClientTimeout(total=_HTTP_TIMEOUT_SECONDS)


# ---------------------------------------------------------------------------
# Cohere — POST /v1/chat (NOT OpenAI-compatible)
# ---------------------------------------------------------------------------


class CohereProvider(AIProvider):
    """Cohere Web API — uses /v1/chat with chat_history shape.

    Cohere's chat endpoint expects:
        {
            "message": "<last user message>",
            "model": "command-r-plus",
            "chat_history": [{"role": "USER|CHATBOT|SYSTEM", "message": "..."}],
            "temperature": 0.2,
            "max_tokens": 2000
        }

    The response shape is ``{"text": "...", "generation_id": "..."}``.
    """

    name = "cohere"

    DEFAULT_BASE_URL = "https://api.cohere.ai/v1"
    DEFAULT_MODEL = "command-r-plus"

    def __init__(self, config: AIProviderConfig) -> None:
        super().__init__(config)
        if not self.config.base_url:
            self.config.base_url = self.DEFAULT_BASE_URL
        if not self.config.model:
            self.config.model = self.DEFAULT_MODEL

    @property
    def _base_url(self) -> str:
        return (self.config.base_url or self.DEFAULT_BASE_URL).rstrip("/")

    def _headers(self, api_key: str) -> dict[str, str]:
        # Cohere accepts both "Authorization: Bearer <key>" and "X-API-KEY: <key>".
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

    async def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        if _is_mock_mode():
            logger.debug("CohereProvider.complete mock-mode response")
            return _MOCK_CHAT

        info = _require_registry_info("cohere")
        api_key = _resolve_api_key(self, info.get("env_key"))
        if not api_key:
            raise RuntimeError(
                "Cohere API key missing. Set COHERE_API_KEY env var or store via "
                "the credential manager (service='z-agent', username='cohere_api_key')."
            )

        # Convert OpenAI messages -> Cohere shape: last user message goes in
        # `message`, the rest goes in `chat_history`.
        if not messages:
            raise ValueError("CohereProvider.complete requires at least one message")

        chat_history: list[dict[str, str]] = []
        last_user_msg = ""
        role_map = {"user": "USER", "assistant": "CHATBOT", "system": "SYSTEM"}
        for m in messages:
            role = role_map.get(m.get("role", ""), "USER")
            if role == "USER" and m is messages[-1]:
                last_user_msg = m.get("content", "")
            else:
                chat_history.append({"role": role, "message": m.get("content", "")})

        payload = {
            "message": last_user_msg or messages[-1].get("content", ""),
            "model": kwargs.get("model") or self.config.model or self.DEFAULT_MODEL,
            "chat_history": chat_history,
            "temperature": kwargs.get("temperature", self.config.temperature),
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
        }

        url = f"{self._base_url}/chat"
        try:
            async with aiohttp.ClientSession(timeout=_aiohttp_timeout()) as session:
                async with session.post(url, json=payload, headers=self._headers(api_key)) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    return data.get("text", "") or ""
        except Exception as exc:
            logger.error("CohereProvider.complete failed (err={})", exc)
            raise

    async def list_models(self) -> list[dict]:
        if _is_mock_mode():
            return [{"id": "command-r-plus", "display_name": "Command R+", "supports_vision": False}]
        info = _require_registry_info("cohere")
        api_key = _resolve_api_key(self, info.get("env_key"))
        if not api_key:
            return []
        url = f"{self._base_url}/models"
        try:
            async with aiohttp.ClientSession(timeout=_aiohttp_timeout()) as session:
                async with session.get(url, headers=self._headers(api_key)) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    raw = data.get("models", []) if isinstance(data, dict) else []
                    out: list[dict] = []
                    for m in raw:
                        if isinstance(m, dict):
                            mid = m.get("name") or m.get("id") or ""
                            if mid:
                                out.append({
                                    "id": mid,
                                    "display_name": m.get("name", mid),
                                    "supports_vision": False,
                                })
                    return out
        except Exception as exc:
            logger.error("CohereProvider.list_models failed (err={})", exc)
            return []


# ---------------------------------------------------------------------------
# Voyage AI — embeddings only (no chat completion)
# ---------------------------------------------------------------------------


class VoyageProvider(AIProvider):
    """Voyage AI — embeddings only.

    Calling :meth:`complete` raises :class:`NotImplementedError` because
    Voyage does not provide a chat-completions endpoint.
    """

    name = "voyage"

    DEFAULT_BASE_URL = "https://api.voyageai.com/v1"
    DEFAULT_MODEL = "voyage-3-large"

    def __init__(self, config: AIProviderConfig) -> None:
        super().__init__(config)
        if not self.config.base_url:
            self.config.base_url = self.DEFAULT_BASE_URL
        if not self.config.model:
            self.config.model = self.DEFAULT_MODEL

    @property
    def _base_url(self) -> str:
        return (self.config.base_url or self.DEFAULT_BASE_URL).rstrip("/")

    def _headers(self, api_key: str) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

    async def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        raise NotImplementedError(
            "Voyage AI is an embeddings-only service and does not support chat "
            "completions. Use VoyageProvider.embed(texts=[...]) instead."
        )

    async def embed(
        self, texts: list[str], model: Optional[str] = None, **kwargs: Any
    ) -> list[list[float]]:
        """Generate embeddings for a list of texts.

        Returns a list of embedding vectors (one per input text).
        """
        if _is_mock_mode():
            logger.debug("VoyageProvider.embed mock-mode response (count={})", len(texts))
            return [list(_MOCK_EMBEDDING) for _ in texts]

        info = _require_registry_info("voyage")
        api_key = _resolve_api_key(self, info.get("env_key"))
        if not api_key:
            raise RuntimeError(
                "Voyage API key missing. Set VOYAGE_API_KEY env var or store via "
                "the credential manager (service='z-agent', username='voyage_api_key')."
            )

        url = f"{self._base_url}/embeddings"
        payload = {
            "input": texts,
            "model": model or self.config.model or self.DEFAULT_MODEL,
        }
        try:
            async with aiohttp.ClientSession(timeout=_aiohttp_timeout()) as session:
                async with session.post(url, json=payload, headers=self._headers(api_key)) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    return [item["embedding"] for item in data.get("data", [])]
        except Exception as exc:
            logger.error("VoyageProvider.embed failed (err={})", exc)
            raise


# ---------------------------------------------------------------------------
# Stability AI — image generation only
# ---------------------------------------------------------------------------


class StabilityProvider(AIProvider):
    """Stability AI — image generation.

    Calling :meth:`complete` raises :class:`NotImplementedError` because
    Stability does not provide a chat-completions endpoint.
    """

    name = "stability"

    DEFAULT_BASE_URL = "https://api.stability.ai/v1"
    DEFAULT_MODEL = "stable-image-core"

    def __init__(self, config: AIProviderConfig) -> None:
        super().__init__(config)
        if not self.config.base_url:
            self.config.base_url = self.DEFAULT_BASE_URL
        if not self.config.model:
            self.config.model = self.DEFAULT_MODEL

    @property
    def _base_url(self) -> str:
        return (self.config.base_url or self.DEFAULT_BASE_URL).rstrip("/")

    def _headers(self, api_key: str, json_body: bool = True) -> dict[str, str]:
        h: dict[str, str] = {"Authorization": f"Bearer {api_key}"}
        if json_body:
            h["Content-Type"] = "application/json"
        h["Accept"] = "application/json"
        return h

    async def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        raise NotImplementedError(
            "Stability AI is an image-generation service and does not support "
            "chat completions. Use StabilityProvider.generate_image(prompt=...) instead."
        )

    async def generate_image(
        self, prompt: str, model: Optional[str] = None, **kwargs: Any
    ) -> dict:
        """Generate an image from a text prompt.

        Returns a dict with ``url`` and ``content_type`` keys (or ``b64_json``
        if the provider returns base64-encoded image data).
        """
        if _is_mock_mode():
            logger.debug("StabilityProvider.generate_image mock-mode response")
            return {"url": _MOCK_IMAGE_URL, "content_type": "image/png"}

        info = _require_registry_info("stability")
        api_key = _resolve_api_key(self, info.get("env_key"))
        if not api_key:
            raise RuntimeError(
                "Stability AI API key missing. Set STABILITY_API_KEY env var or "
                "store via the credential manager (service='z-agent', "
                "username='stability_api_key')."
            )

        model_id = model or self.config.model or self.DEFAULT_MODEL
        url = f"{self._base_url}/generation/{model_id}/text-to-image"
        payload = {
            "text_prompts": [{"text": prompt, "weight": 1.0}],
            "cfg_scale": kwargs.get("cfg_scale", 7),
            "steps": kwargs.get("steps", 30),
        }
        try:
            async with aiohttp.ClientSession(timeout=_aiohttp_timeout()) as session:
                async with session.post(
                    url, json=payload, headers=self._headers(api_key)
                ) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    artifacts = data.get("artifacts", [])
                    if artifacts:
                        first = artifacts[0]
                        b64 = first.get("base64")
                        if b64:
                            return {
                                "b64_json": b64,
                                "content_type": "image/png",
                            }
                        return {"url": first.get("url", ""), "content_type": "image/png"}
                    return {"url": "", "content_type": "image/png"}
        except Exception as exc:
            logger.error("StabilityProvider.generate_image failed (err={})", exc)
            raise


# ---------------------------------------------------------------------------
# Replicate — POST /v1/predictions
# ---------------------------------------------------------------------------


class ReplicateProvider(AIProvider):
    """Replicate — uses the /predictions endpoint with a model version.

    The model identifier is ``owner/name:hash`` (e.g. ``meta/llama-3.1-70b-instruct``).
    """

    name = "replicate"

    DEFAULT_BASE_URL = "https://api.replicate.com/v1"
    DEFAULT_MODEL = "meta/llama-3.1-70b-instruct"

    def __init__(self, config: AIProviderConfig) -> None:
        super().__init__(config)
        if not self.config.base_url:
            self.config.base_url = self.DEFAULT_BASE_URL
        if not self.config.model:
            self.config.model = self.DEFAULT_MODEL

    @property
    def _base_url(self) -> str:
        return (self.config.base_url or self.DEFAULT_BASE_URL).rstrip("/")

    def _headers(self, api_key: str) -> dict[str, str]:
        # Replicate prefers "Authorization: Bearer <token>" (also "Token <token>" works)
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "Prefer": "wait",  # ask the server to wait for completion
        }

    async def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        if _is_mock_mode():
            logger.debug("ReplicateProvider.complete mock-mode response")
            return _MOCK_CHAT

        info = _require_registry_info("replicate")
        api_key = _resolve_api_key(self, info.get("env_key"))
        if not api_key:
            raise RuntimeError(
                "Replicate API token missing. Set REPLICATE_API_KEY env var or "
                "store via the credential manager (service='z-agent', "
                "username='replicate_api_key')."
            )

        model_id = kwargs.get("model") or self.config.model or self.DEFAULT_MODEL
        prompt = "\n\n".join(
            f"{m.get('role', 'user').upper()}: {m.get('content', '')}" for m in messages
        )

        # Replicate accepts the model identifier directly as `version` (older API)
        # or as `model` (new API). Use `model` per current docs.
        url = f"{self._base_url}/predictions"
        payload: dict[str, Any] = {
            "model": model_id,
            "input": {"prompt": prompt},
        }
        try:
            async with aiohttp.ClientSession(timeout=_aiohttp_timeout()) as session:
                async with session.post(url, json=payload, headers=self._headers(api_key)) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    # Output can be a string (text), a list of strings, or a dict.
                    output = data.get("output", "")
                    if isinstance(output, list):
                        return "".join(str(x) for x in output)
                    return str(output) if output else ""
        except Exception as exc:
            logger.error("ReplicateProvider.complete failed (err={})", exc)
            raise

    async def list_models(self) -> list[dict]:
        if _is_mock_mode():
            return [{"id": "meta/llama-3.1-70b-instruct", "display_name": "Llama 3.1 70B Instruct", "supports_vision": False}]
        info = _require_registry_info("replicate")
        api_key = _resolve_api_key(self, info.get("env_key"))
        if not api_key:
            return []
        url = f"{self._base_url}/models"
        try:
            async with aiohttp.ClientSession(timeout=_aiohttp_timeout()) as session:
                async with session.get(url, headers=self._headers(api_key)) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    raw = data.get("results", []) if isinstance(data, dict) else []
                    out: list[dict] = []
                    for m in raw:
                        if isinstance(m, dict):
                            full = (m.get("owner") or "") + "/" + (m.get("name") or "")
                            full = full.strip("/")
                            if full:
                                out.append({
                                    "id": full,
                                    "display_name": full,
                                    "supports_vision": False,
                                })
                    return out
        except Exception as exc:
            logger.error("ReplicateProvider.list_models failed (err={})", exc)
            return []


# ---------------------------------------------------------------------------
# Cloudflare Workers AI — account_id in URL path
# ---------------------------------------------------------------------------


class CloudflareProvider(AIProvider):
    """Cloudflare Workers AI — POST /accounts/{account_id}/ai/run/{model}.

    Requires a Cloudflare account ID, supplied via the
    ``CLOUDFLARE_ACCOUNT_ID`` env var or via ``config.base_url`` (which is
    expected to end with ``/accounts/{account_id}``).
    """

    name = "cloudflare"

    DEFAULT_BASE_URL = "https://api.cloudflare.com/client/v4/accounts"
    DEFAULT_MODEL = "@cf/meta/llama-3.1-70b-instruct"

    def __init__(self, config: AIProviderConfig) -> None:
        super().__init__(config)
        if not self.config.base_url:
            self.config.base_url = self.DEFAULT_BASE_URL
        if not self.config.model:
            self.config.model = self.DEFAULT_MODEL

    @property
    def _account_id(self) -> Optional[str]:
        # Prefer an explicit env var, then try to extract from base_url path.
        acct = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
        if acct:
            return acct
        url = self.config.base_url or ""
        # base_url ends with /accounts/{account_id}
        parts = url.rstrip("/").split("/")
        if len(parts) >= 2 and parts[-2] == "accounts":
            return parts[-1]
        return None

    def _headers(self, api_key: str) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

    async def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        if _is_mock_mode():
            logger.debug("CloudflareProvider.complete mock-mode response")
            return _MOCK_CHAT

        info = _require_registry_info("cloudflare")
        api_key = _resolve_api_key(self, info.get("env_key"))
        if not api_key:
            raise RuntimeError(
                "Cloudflare AI API key missing. Set CLOUDFLARE_AI_API_KEY env var."
            )

        acct = self._account_id
        if not acct:
            raise RuntimeError(
                "Cloudflare account_id missing. Set CLOUDFLARE_ACCOUNT_ID env var "
                "or include it in config.base_url "
                "(https://api.cloudflare.com/client/v4/accounts/{account_id})."
            )

        model_id = kwargs.get("model") or self.config.model or self.DEFAULT_MODEL
        url = (
            f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/{model_id}"
        )
        payload = {
            "messages": messages,
            "temperature": kwargs.get("temperature", self.config.temperature),
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
        }
        try:
            async with aiohttp.ClientSession(timeout=_aiohttp_timeout()) as session:
                async with session.post(url, json=payload, headers=self._headers(api_key)) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    # Cloudflare wraps responses: {result: {response: "..."}, success: true}
                    if not data.get("success", True):
                        raise RuntimeError(f"Cloudflare API error: {data.get('errors')}")
                    result = data.get("result", {})
                    if isinstance(result, dict):
                        return result.get("response", "") or ""
                    return str(result)
        except Exception as exc:
            logger.error("CloudflareProvider.complete failed (err={})", exc)
            raise


# ---------------------------------------------------------------------------
# AWS Bedrock — boto3 preferred, manual SigV4 fallback
# ---------------------------------------------------------------------------


class AWSBedrockProvider(AIProvider):
    """AWS Bedrock Runtime — boto3 if installed, else manual SigV4.

    Handles both ``aws_bedrock`` (Claude / Llama / Titan models) and
    ``amazon_nova`` (Amazon Nova family) — same Bedrock runtime API.
    """

    name = "aws_bedrock"

    DEFAULT_REGION = "us-east-1"
    DEFAULT_MODEL = "anthropic.claude-3-5-sonnet-20241022-v2:0"

    def __init__(self, config: AIProviderConfig) -> None:
        super().__init__(config)
        # Preserve the registry slug so amazon_nova round-trips correctly
        # (this class is shared between aws_bedrock and amazon_nova).
        if config.name:
            self.name = config.name
        if not self.config.model:
            info = _require_registry_info(self.name)
            self.config.model = info.get("default_model") or self.DEFAULT_MODEL

    def _resolve_creds(self) -> tuple[Optional[str], Optional[str], str]:
        """Return (access_key, secret_key, region)."""
        access_key = os.environ.get("AWS_ACCESS_KEY_ID")
        secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY")
        # The credential manager stores these under 'aws_access_key_id' and
        # 'aws_secret_access_key' service names.
        try:
            from ..security.credentials import get_credential
            if not access_key:
                access_key = get_credential("aws_access_key_id")
            if not secret_key:
                secret_key = get_credential("aws_secret_access_key")
        except Exception:
            pass
        region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or self.DEFAULT_REGION
        return access_key, secret_key, region

    async def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        if _is_mock_mode():
            logger.debug("AWSBedrockProvider.complete mock-mode response")
            return _MOCK_CHAT

        access_key, secret_key, region = self._resolve_creds()
        if not access_key or not secret_key:
            raise RuntimeError(
                "AWS credentials missing. Set AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY "
                "env vars (or store via the credential manager under "
                "'aws_access_key_id' / 'aws_secret_access_key')."
            )

        model_id = kwargs.get("model") or self.config.model or self.DEFAULT_MODEL
        system_msgs = [m["content"] for m in messages if m.get("role") == "system"]
        user_messages = [m for m in messages if m.get("role") != "system"]
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            "temperature": kwargs.get("temperature", self.config.temperature),
            "system": "\n\n".join(system_msgs) if system_msgs else None,
            "messages": user_messages,
        })

        # Try boto3 first (preferred path)
        try:
            import boto3  # type: ignore
        except ImportError:
            boto3 = None  # type: ignore

        if boto3 is not None:
            try:
                import asyncio as _asyncio

                def _invoke() -> str:
                    client = boto3.client(
                        "bedrock-runtime",
                        region_name=region,
                        aws_access_key_id=access_key,
                        aws_secret_access_key=secret_key,
                    )
                    response = client.invoke_model(
                        modelId=model_id,
                        body=body,
                        contentType="application/json",
                        accept="application/json",
                    )
                    raw = response["body"].read().decode("utf-8")
                    data = json.loads(raw)
                    # Anthropic-style response: {content: [{text: "..."}]}
                    content = data.get("content", [])
                    if content and isinstance(content, list):
                        return content[0].get("text", "")
                    # Some Bedrock models return {generation: "..."} or {outputs: [...]}
                    return data.get("generation") or data.get("completion") or ""

                return await _asyncio.to_thread(_invoke)
            except Exception as exc:
                logger.error("AWSBedrockProvider.complete (boto3) failed (err={})", exc)
                raise

        # Fallback: manual SigV4 over aiohttp
        host = f"bedrock-runtime.{region}.amazonaws.com"
        url = f"https://{host}/model/{model_id}/invoke"
        headers = _sigv4_sign(
            method="POST",
            url=url,
            body=body,
            access_key=access_key or "",
            secret_key=secret_key or "",
            region=region,
            service="bedrock",
        )
        headers["Content-Type"] = "application/json"
        try:
            async with aiohttp.ClientSession(timeout=_aiohttp_timeout()) as session:
                async with session.post(url, data=body, headers=headers) as resp:
                    resp.raise_for_status()
                    raw = await resp.text()
                    data = json.loads(raw)
                    content = data.get("content", [])
                    if content and isinstance(content, list):
                        return content[0].get("text", "")
                    return data.get("generation") or data.get("completion") or ""
        except Exception as exc:
            logger.error("AWSBedrockProvider.complete (sigv4) failed (err={})", exc)
            raise


# ---------------------------------------------------------------------------
# Google Vertex AI — OAuth2 token via google.auth
# ---------------------------------------------------------------------------


class GoogleVertexProvider(AIProvider):
    """Google Vertex AI — uses google.auth for OAuth2 token acquisition.

    Requires ``GOOGLE_APPLICATION_CREDENTIALS`` env var pointing at a service
    account JSON file, plus ``GOOGLE_VERTEX_PROJECT_ID`` and
    ``GOOGLE_VERTEX_LOCATION`` (default ``us-central1``).
    """

    name = "google_vertex"

    DEFAULT_LOCATION = "us-central1"
    DEFAULT_MODEL = "gemini-1.5-flash"

    def __init__(self, config: AIProviderConfig) -> None:
        super().__init__(config)
        if not self.config.model:
            self.config.model = self.DEFAULT_MODEL

    def _resolve_project(self) -> Optional[str]:
        project = os.environ.get("GOOGLE_VERTEX_PROJECT_ID")
        if not project:
            try:
                from ..security.credentials import get_credential
                project = get_credential("google_vertex_project_id")
            except Exception:
                pass
        return project

    async def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        if _is_mock_mode():
            logger.debug("GoogleVertexProvider.complete mock-mode response")
            return _MOCK_CHAT

        project = self._resolve_project()
        if not project:
            raise RuntimeError(
                "Google Vertex project_id missing. Set GOOGLE_VERTEX_PROJECT_ID env var."
            )

        # Try google.auth for credentials
        try:
            import google.auth  # type: ignore
            from google.auth.transport.requests import Request  # type: ignore
            import google.auth.default  # type: ignore # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "google-auth package not installed. Install with: "
                "pip install google-auth google-auth-transport-requests. "
                "Also set GOOGLE_APPLICATION_CREDENTIALS to your service account JSON file."
            ) from exc

        location = os.environ.get("GOOGLE_VERTEX_LOCATION", self.DEFAULT_LOCATION)
        model_id = kwargs.get("model") or self.config.model or self.DEFAULT_MODEL

        # Acquire OAuth2 token (Application Default Credentials)
        try:
            import asyncio as _asyncio

            def _get_token() -> tuple[str, str]:
                creds, _ = google.auth.default(
                    scopes=["https://www.googleapis.com/auth/cloud-platform"]
                )
                if not creds.valid:
                    creds.refresh(Request())
                return creds.token, creds.quota_project_id or project

            token, _project = await _asyncio.to_thread(_get_token)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to acquire Google OAuth2 token: {exc}. "
                f"Set GOOGLE_APPLICATION_CREDENTIALS to your service account JSON file."
            ) from exc

        # Vertex AI raw REST endpoint:
        #   POST https://{location}-aiplatform.googleapis.com/v1/projects/{project}/locations/{location}/publishers/google/models/{model}:generateContent
        url = (
            f"https://{location}-aiplatform.googleapis.com/v1/"
            f"projects/{project}/locations/{location}/"
            f"publishers/google/models/{model_id}:generateContent"
        )
        # Convert OpenAI messages -> Vertex "contents" shape
        contents: list[dict] = []
        system_instruction: Optional[str] = None
        for m in messages:
            role = m.get("role", "user")
            if role == "system":
                system_instruction = m.get("content", "")
                continue
            vertex_role = "user" if role == "user" else "model"
            contents.append({
                "role": vertex_role,
                "parts": [{"text": m.get("content", "")}],
            })

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": kwargs.get("temperature", self.config.temperature),
                "maxOutputTokens": kwargs.get("max_tokens", self.config.max_tokens),
            },
        }
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }
        try:
            async with aiohttp.ClientSession(timeout=_aiohttp_timeout()) as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            return parts[0].get("text", "")
                    return ""
        except Exception as exc:
            logger.error("GoogleVertexProvider.complete failed (err={})", exc)
            raise


# ---------------------------------------------------------------------------
# Azure AI Foundry — raw HTTP against the Azure OpenAI REST surface
# ---------------------------------------------------------------------------


class AzureAIProvider(AIProvider):
    """Azure AI Foundry — uses the Azure OpenAI REST surface.

    Requires ``AZURE_AI_ENDPOINT`` (e.g. ``https://my-resource.openai.azure.com``)
    and ``AZURE_AI_KEY``. The model name (config.model) is interpreted as the
    Azure deployment name.
    """

    name = "azure_ai"

    DEFAULT_API_VERSION = "2024-02-15-preview"

    def __init__(self, config: AIProviderConfig) -> None:
        super().__init__(config)
        if not self.config.model:
            self.config.model = "gpt-4o"

    def _resolve_endpoint(self) -> Optional[str]:
        endpoint = os.environ.get("AZURE_AI_ENDPOINT")
        if not endpoint:
            try:
                from ..security.credentials import get_credential
                endpoint = get_credential("azure_ai_endpoint")
            except Exception:
                pass
        if endpoint and not self.config.base_url:
            self.config.base_url = endpoint.rstrip("/")
        return endpoint or self.config.base_url

    def _resolve_api_key(self) -> Optional[str]:
        key = os.environ.get("AZURE_AI_KEY")
        if not key:
            try:
                from ..security.credentials import get_credential
                key = get_credential("azure_ai_key")
            except Exception:
                pass
        if not key:
            key = self.config.api_key
        return key

    def _headers(self, api_key: str) -> dict[str, str]:
        # Azure uses the `api-key` header (NOT Bearer).
        return {
            "Content-Type": "application/json",
            "api-key": api_key,
        }

    async def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        if _is_mock_mode():
            logger.debug("AzureAIProvider.complete mock-mode response")
            return _MOCK_CHAT

        endpoint = self._resolve_endpoint()
        api_key = self._resolve_api_key()
        if not endpoint:
            raise RuntimeError(
                "Azure AI endpoint missing. Set AZURE_AI_ENDPOINT env var (e.g. "
                "https://my-resource.openai.azure.com)."
            )
        if not api_key:
            raise RuntimeError(
                "Azure AI key missing. Set AZURE_AI_KEY env var."
            )

        deployment = kwargs.get("model") or self.config.model or "gpt-4o"
        api_version = kwargs.get("api_version", self.DEFAULT_API_VERSION)
        url = (
            f"{endpoint.rstrip('/')}/openai/deployments/{deployment}"
            f"/chat/completions?api-version={api_version}"
        )
        payload = {
            "messages": messages,
            "temperature": kwargs.get("temperature", self.config.temperature),
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
        }
        try:
            async with aiohttp.ClientSession(timeout=_aiohttp_timeout()) as session:
                async with session.post(url, json=payload, headers=self._headers(api_key)) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"] or ""
        except Exception as exc:
            logger.error("AzureAIProvider.complete failed (err={})", exc)
            raise


# ---------------------------------------------------------------------------
# IBM watsonx.ai — Bearer IAM token + project_id
# ---------------------------------------------------------------------------


class IBMWatsonxProvider(AIProvider):
    """IBM watsonx.ai — Bearer token acquired from IAM, then /text/chat."""

    name = "ibm_watsonx"

    DEFAULT_BASE_URL = "https://us-south.ml.cloud.ibm.com"
    DEFAULT_MODEL = "ibm/granite-3-8b-instruct"
    IAM_TOKEN_URL = "https://iam.cloud.ibm.com/identity/token"

    def __init__(self, config: AIProviderConfig) -> None:
        super().__init__(config)
        if not self.config.base_url:
            self.config.base_url = self.DEFAULT_BASE_URL
        if not self.config.model:
            self.config.model = self.DEFAULT_MODEL

    @property
    def _base_url(self) -> str:
        return (self.config.base_url or self.DEFAULT_BASE_URL).rstrip("/")

    def _resolve_api_key(self) -> Optional[str]:
        key = os.environ.get("IBM_WATSONX_API_KEY")
        if not key:
            try:
                from ..security.credentials import get_credential
                key = get_credential("ibm_watsonx_api_key")
            except Exception:
                pass
        if not key:
            key = self.config.api_key
        return key

    def _resolve_project_id(self) -> Optional[str]:
        pid = os.environ.get("IBM_WATSONX_PROJECT_ID")
        if not pid:
            try:
                from ..security.credentials import get_credential
                pid = get_credential("ibm_watsonx_project_id")
            except Exception:
                pass
        return pid

    async def _get_iam_token(self, api_key: str) -> str:
        """Exchange the API key for an IAM access token."""
        body = f"grant_type=urn:ibm:params:oauth:grant-type:apikey&apikey={api_key}"
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        try:
            async with aiohttp.ClientSession(timeout=_aiohttp_timeout()) as session:
                async with session.post(self.IAM_TOKEN_URL, data=body, headers=headers) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    return data.get("access_token", "")
        except Exception as exc:
            logger.error("IBMWatsonxProvider._get_iam_token failed (err={})", exc)
            raise

    async def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        if _is_mock_mode():
            logger.debug("IBMWatsonxProvider.complete mock-mode response")
            return _MOCK_CHAT

        api_key = self._resolve_api_key()
        if not api_key:
            raise RuntimeError(
                "IBM watsonx API key missing. Set IBM_WATSONX_API_KEY env var."
            )
        project_id = self._resolve_project_id()
        if not project_id:
            raise RuntimeError(
                "IBM watsonx project_id missing. Set IBM_WATSONX_PROJECT_ID env var."
            )

        # Acquire IAM token
        token = await self._get_iam_token(api_key)
        if not token:
            raise RuntimeError("IBM watsonx IAM token exchange failed.")

        url = f"{self._base_url}/ml/v1/text/chat?version=2024-03-14"
        payload = {
            "model_id": kwargs.get("model") or self.config.model or self.DEFAULT_MODEL,
            "project_id": project_id,
            "messages": messages,
            "temperature": kwargs.get("temperature", self.config.temperature),
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }
        try:
            async with aiohttp.ClientSession(timeout=_aiohttp_timeout()) as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    choices = data.get("choices", [])
                    if choices:
                        return choices[0].get("message", {}).get("content", "") or ""
                    return ""
        except Exception as exc:
            logger.error("IBMWatsonxProvider.complete failed (err={})", exc)
            raise

    async def list_models(self) -> list[dict]:
        if _is_mock_mode():
            return [{"id": "ibm/granite-3-8b-instruct", "display_name": "Granite 3 8B", "supports_vision": False}]
        api_key = self._resolve_api_key()
        if not api_key:
            return []
        try:
            token = await self._get_iam_token(api_key)
        except Exception:
            return []
        url = f"{self._base_url}/ml/v1/foundation_model_specs?version=2024-03-14"
        headers = {"Authorization": f"Bearer {token}"}
        try:
            async with aiohttp.ClientSession(timeout=_aiohttp_timeout()) as session:
                async with session.get(url, headers=headers) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    raw = data.get("resources", []) if isinstance(data, dict) else []
                    out: list[dict] = []
                    for m in raw:
                        if isinstance(m, dict):
                            mid = m.get("model_id") or m.get("id") or ""
                            if mid:
                                out.append({
                                    "id": mid,
                                    "display_name": m.get("label", mid),
                                    "supports_vision": False,
                                })
                    return out
        except Exception as exc:
            logger.error("IBMWatsonxProvider.list_models failed (err={})", exc)
            return []


# ---------------------------------------------------------------------------
# Databricks — serving endpoints
# ---------------------------------------------------------------------------


class DatabricksProvider(AIProvider):
    """Databricks — serving-endpoints invocations.

    Requires ``DATABRICKS_HOST`` (e.g. ``https://<workspace>.cloud.databricks.com``)
    and ``DATABRICKS_TOKEN``. The model name (config.model) is interpreted
    as the serving-endpoint name.
    """

    name = "databricks"

    DEFAULT_MODEL = "databricks-dbrx-instruct"

    def __init__(self, config: AIProviderConfig) -> None:
        super().__init__(config)
        if not self.config.model:
            self.config.model = self.DEFAULT_MODEL

    def _resolve_host(self) -> Optional[str]:
        host = os.environ.get("DATABRICKS_HOST")
        if not host:
            try:
                from ..security.credentials import get_credential
                host = get_credential("databricks_host")
            except Exception:
                pass
        if host and not self.config.base_url:
            self.config.base_url = host.rstrip("/")
        return host or self.config.base_url

    def _resolve_token(self) -> Optional[str]:
        token = os.environ.get("DATABRICKS_TOKEN")
        if not token:
            try:
                from ..security.credentials import get_credential
                token = get_credential("databricks_token")
            except Exception:
                pass
        if not token:
            token = self.config.api_key
        return token

    def _headers(self, token: str) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }

    async def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        if _is_mock_mode():
            logger.debug("DatabricksProvider.complete mock-mode response")
            return _MOCK_CHAT

        host = self._resolve_host()
        token = self._resolve_token()
        if not host:
            raise RuntimeError(
                "Databricks host missing. Set DATABRICKS_HOST env var "
                "(e.g. https://<workspace>.cloud.databricks.com)."
            )
        if not token:
            raise RuntimeError(
                "Databricks token missing. Set DATABRICKS_TOKEN env var."
            )

        endpoint_name = kwargs.get("model") or self.config.model or self.DEFAULT_MODEL
        url = f"{host.rstrip('/')}/serving-endpoints/{endpoint_name}/invocations"
        # Databricks Foundation Model APIs accept OpenAI-shaped payloads
        payload = {
            "messages": messages,
            "temperature": kwargs.get("temperature", self.config.temperature),
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
        }
        try:
            async with aiohttp.ClientSession(timeout=_aiohttp_timeout()) as session:
                async with session.post(url, json=payload, headers=self._headers(token)) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    # OpenAI-shaped response
                    choices = data.get("choices", [])
                    if choices:
                        return choices[0].get("message", {}).get("content", "") or ""
                    return data.get("predictions", "") or ""
        except Exception as exc:
            logger.error("DatabricksProvider.complete failed (err={})", exc)
            raise

    async def list_models(self) -> list[dict]:
        if _is_mock_mode():
            return [{"id": "databricks-dbrx-instruct", "display_name": "DBRX Instruct", "supports_vision": False}]
        host = self._resolve_host()
        token = self._resolve_token()
        if not host or not token:
            return []
        url = f"{host.rstrip('/')}/api/2.0/serving-endpoints"
        try:
            async with aiohttp.ClientSession(timeout=_aiohttp_timeout()) as session:
                async with session.get(url, headers=self._headers(token)) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    endpoints = data.get("endpoints", []) if isinstance(data, dict) else []
                    out: list[dict] = []
                    for ep in endpoints:
                        if isinstance(ep, dict):
                            name = ep.get("name") or ""
                            if name:
                                out.append({
                                    "id": name,
                                    "display_name": name,
                                    "supports_vision": False,
                                })
                    return out
        except Exception as exc:
            logger.error("DatabricksProvider.list_models failed (err={})", exc)
            return []


# ---------------------------------------------------------------------------
# AWS SigV4 — stdlib-only manual signing (fallback when boto3 is absent)
# ---------------------------------------------------------------------------


def _sigv4_sign(
    *,
    method: str,
    url: str,
    body: str,
    access_key: str,
    secret_key: str,
    region: str,
    service: str,
) -> dict[str, str]:
    """Compute AWS SigV4 headers for the given request.

    Uses only stdlib (``hmac``, ``hashlib``, ``urllib``) — no external deps.
    Returns the headers dict (Authorization, x-amz-date, x-amz-content-sha256).
    """
    t = datetime.now(timezone.utc)
    amz_date = t.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = t.strftime("%Y%m%d")

    parsed = urlparse(url)
    host = parsed.netloc
    canonical_uri = parsed.path or "/"
    canonical_querystring = parsed.query

    payload_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()

    canonical_headers = (
        f"host:{host}\n"
        f"x-amz-content-sha256:{payload_hash}\n"
        f"x-amz-date:{amz_date}\n"
    )
    signed_headers = "host;x-amz-content-sha256;x-amz-date"

    canonical_request = (
        f"{method}\n{canonical_uri}\n{canonical_querystring}\n"
        f"{canonical_headers}\n{signed_headers}\n{payload_hash}"
    )

    credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = (
        f"AWS4-HMAC-SHA256\n{amz_date}\n{credential_scope}\n"
        f"{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
    )

    def _sign(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

    k_date = _sign(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k_region = _sign(k_date, region)
    k_service = _sign(k_region, service)
    k_signing = _sign(k_service, "aws4_request")
    signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    authorization_header = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    return {
        "Authorization": authorization_header,
        "x-amz-date": amz_date,
        "x-amz-content-sha256": payload_hash,
    }


__all__ = [
    "CohereProvider",
    "VoyageProvider",
    "StabilityProvider",
    "ReplicateProvider",
    "CloudflareProvider",
    "AWSBedrockProvider",
    "GoogleVertexProvider",
    "AzureAIProvider",
    "IBMWatsonxProvider",
    "DatabricksProvider",
]
