"""Credential Manager — master prompt §28 (Database Security).

Layered credential access:
1. OS keyring (preferred — secrets never touch disk in plaintext)
2. Environment variables (fallback — works on Linux servers without keyring)
3. .env file (last resort — only for local dev)

Provides:
- get_credential(service) -> Optional[str]
- set_credential(service, value) -> None
- require_credential(service) -> str  (raises if missing)

Master prompt §57 (Secret Protection): secrets are NEVER logged. Methods
that need to surface them in logs use `mask()` to redact.
"""

from __future__ import annotations

import os
import re
from typing import Optional

# Try to import keyring — if it's not available, fall back to env vars only.
try:
    import keyring  # type: ignore
    KEYRING_AVAILABLE = True
except ImportError:  # pragma: no cover
    KEYRING_AVAILABLE = False


SERVICE_NAME = "z-agent"


# ---------------------------------------------------------------------------
# Masking — master prompt §57
# ---------------------------------------------------------------------------


_SENSITIVE_PATTERNS = [
    re.compile(r"(sk-[a-zA-Z0-9]{4})[a-zA-Z0-9]+"),
    re.compile(r"(vck_[a-zA-Z0-9]{4})[a-zA-Z0-9]+"),
    re.compile(r"(vcp_[a-zA-Z0-9]{4})[a-zA-Z0-9]+"),
    re.compile(r"(ghp_[a-zA-Z0-9]{4})[a-zA-Z0-9]+"),
    re.compile(r"(github_pat_[a-zA-Z0-9_]{8})[a-zA-Z0-9_]+"),
    re.compile(r"(eyJ[a-zA-Z0-9_-]{8})[a-zA-Z0-9_.-]+"),
    re.compile(r"(bot[0-9]{4})[a-zA-Z0-9:_-]+"),  # Telegram bot tokens
]


def mask(value: Optional[str]) -> str:
    """Redact sensitive token-like values for safe logging."""
    if not value:
        return "<empty>"
    if len(value) < 12:
        return "<redacted>"
    masked = value
    for pat in _SENSITIVE_PATTERNS:
        masked = pat.sub(r"\1…<redacted>", masked)
    if len(masked) > 80:
        masked = masked[:80] + "…"
    return masked


# ---------------------------------------------------------------------------
# Get / Set
# ---------------------------------------------------------------------------


def get_credential(service: str) -> Optional[str]:
    """Retrieve a credential by service name.

    Order of resolution:
    1. OS keyring (if available)
    2. Environment variable (upper-snake-cased service name)
    """
    env_key = service.upper().replace("-", "_").replace(".", "_")

    # 1. Environment variable (most common in container/server deployments)
    val = os.environ.get(env_key)
    if val:
        return val

    # 2. OS keyring (for desktop installs where user has stored secrets via UI)
    if KEYRING_AVAILABLE:
        try:
            val = keyring.get_password(SERVICE_NAME, service)
            if val:
                return val
        except Exception:
            pass

    return None


def require_credential(service: str) -> str:
    """Retrieve a credential or raise if missing."""
    val = get_credential(service)
    if not val:
        raise RuntimeError(
            f"Missing required credential: '{service}'. "
            f"Set the {service.upper().replace('-', '_')} env var or store in OS keyring "
            f"under service='{SERVICE_NAME}', username='{service}'."
        )
    return val


def set_credential(service: str, value: str) -> None:
    """Store a credential in the OS keyring (if available)."""
    if not KEYRING_AVAILABLE:
        raise RuntimeError(
            "keyring package not installed. Install with: pip install keyring. "
            "Alternatively, set the env var directly."
        )
    keyring.set_password(SERVICE_NAME, service, value)


def list_known_services() -> list[str]:
    """Returns the canonical list of services this app knows about."""
    return [
        # AI providers
        "openai_api_key",
        "anthropic_api_key",
        "gemini_api_key",
        "deepseek_api_key",
        "mistral_api_key",
        "xai_api_key",
        "cohere_api_key",
        "groq_api_key",
        "together_api_key",
        "fireworks_api_key",
        "cerebras_api_key",
        "sambanova_api_key",
        "ai21_api_key",
        "perplexity_api_key",
        "openrouter_api_key",
        "huggingface_api_key",
        "nvidia_nim_api_key",
        "cloudflare_ai_api_key",
        "replicate_api_key",
        "stability_api_key",
        "voyage_api_key",
        "jina_api_key",
        "lepton_api_key",
        "friendliai_api_key",
        "baseten_api_key",
        "modal_api_key",
        "anyscale_api_key",
        "ai2_api_key",
        "aleph_alpha_api_key",
        "writer_api_key",
        "upstage_api_key",
        "baichuan_api_key",
        "zhipu_api_key",
        "qwen_api_key",
        "siliconflow_api_key",
        "hyperbolic_api_key",
        "nebius_api_key",
        # Cloud providers (Bedrock/Vertex/Azure/watsonx)
        "aws_access_key_id",
        "aws_secret_access_key",
        "google_vertex_project_id",
        "azure_ai_endpoint",
        "azure_ai_key",
        "ibm_watsonx_api_key",
        "ibm_watsonx_project_id",
        "databricks_token",
        # Aggregators
        "vercel_ai_gateway_key",
        "vercel_access_token",
        # Source control
        "github_token",
        # OAuth providers
        "google_oauth_client_id",
        "google_oauth_client_secret",
        "github_oauth_client_id",
        "github_oauth_client_secret",
        "facebook_oauth_app_id",
        "facebook_oauth_app_secret",
        # Email
        "email_smtp_username",
        "email_smtp_password",
        "email_imap_username",
        "email_imap_password",
        # Messaging
        "whatsapp_business_token",
        "whatsapp_phone_number_id",
        "whatsapp_verify_token",
        "telegram_bot_token",
        "discord_bot_token",
        "discord_application_id",
        "slack_bot_token",
        "slack_signing_secret",
        # Database
        "turso_auth_token",
    ]
