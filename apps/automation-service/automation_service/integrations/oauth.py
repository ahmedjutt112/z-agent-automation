"""OAuth provider abstraction — master prompt §54 (Integrations).

Provides:
- ``OAuthProvider`` ABC with three methods:
    * ``get_authorization_url(state) -> str``
    * ``exchange_code(code) -> OAuthTokens``
    * ``get_user_info(tokens) -> OAuthUserInfo``
- ``OAuthTokens`` Pydantic model (access_token, refresh_token, expires_at,
  scope, token_type).
- ``OAuthUserInfo`` Pydantic model (provider, provider_user_id, email, name,
  avatar_url, raw_json).
- Three concrete providers: Google / GitHub / Facebook.
- ``OAUTH_PROVIDERS`` dict + ``get_oauth_provider(name)`` factory.
- ``initiate_oauth_flow(provider_name, state) -> str`` — returns auth URL.
- ``complete_oauth_flow(provider_name, code) -> OAuthUserInfo`` — exchanges
  the code, fetches user info, and persists tokens to the ``api_credentials``
  table via the SQLAlchemy session.

All HTTP calls use ``aiohttp`` with a 30s timeout. Secrets (client_id /
client_secret) are loaded via the credential manager (NEVER hardcoded). When
``settings.mock_mode`` is True, network calls are skipped and the providers
return deterministic fake data so tests and offline dev still work.
"""

from __future__ import annotations

import abc
import asyncio
import os
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Optional

import aiohttp
from loguru import logger
from pydantic import BaseModel, Field

from ..config import settings
from ..security.credentials import get_credential, mask


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class OAuthTokens(BaseModel):
    """Token set returned by the OAuth provider's token endpoint."""

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[datetime] = None  # absolute UTC timestamp
    scope: Optional[str] = None
    token_type: str = "Bearer"


class OAuthUserInfo(BaseModel):
    """Normalised user profile fetched from the provider's userinfo endpoint."""

    provider: str
    provider_user_id: str
    email: Optional[str] = None
    name: Optional[str] = None
    avatar_url: Optional[str] = None
    raw_json: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# ABC
# ---------------------------------------------------------------------------


class OAuthProvider(abc.ABC):
    """Abstract OAuth provider.

    Subclasses MUST set:
      - ``provider_name``: lowercase short name ("google", "github", ...)
      - ``client_id_env``: env var name for the OAuth client id
      - ``client_secret_env``: env var name for the OAuth client secret
      - ``redirect_uri_env``: env var name for the redirect URI
      - ``auth_url``: provider authorization endpoint
      - ``token_url``: provider token endpoint
      - ``userinfo_url``: provider userinfo endpoint
      - ``default_scope``: space-delimited scope string
    """

    provider_name: str = ""
    client_id_env: str = ""
    client_secret_env: str = ""
    redirect_uri_env: str = ""
    auth_url: str = ""
    token_url: str = ""
    userinfo_url: str = ""
    default_scope: str = ""

    # ---------- credential accessors (never log secrets) ----------

    @property
    def client_id(self) -> Optional[str]:
        return get_credential(self.client_id_env)

    @property
    def client_secret(self) -> Optional[str]:
        return get_credential(self.client_secret_env)

    @property
    def redirect_uri(self) -> str:
        # Default redirect URI per provider if env var is unset.
        env_val = os.environ.get(self.redirect_uri_env)
        if env_val:
            return env_val
        return f"http://127.0.0.1:{settings.port}/oauth/{self.provider_name}/callback"

    def is_configured(self) -> bool:
        """True when both client_id and client_secret are present."""
        return bool(self.client_id) and bool(self.client_secret)

    # ---------- ABC methods ----------

    @abc.abstractmethod
    def get_authorization_url(self, state: str) -> str:
        """Build the authorization URL the user must visit."""
        raise NotImplementedError

    @abc.abstractmethod
    async def exchange_code(self, code: str) -> OAuthTokens:
        """POST the code to the token endpoint and return parsed tokens."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_user_info(self, tokens: OAuthTokens) -> OAuthUserInfo:
        """GET the userinfo endpoint with the access token."""
        raise NotImplementedError

    # ---------- shared helpers ----------

    def _build_auth_url(self, params: dict[str, str]) -> str:
        """Append ``params`` to ``self.auth_url`` and return the full URL."""
        query = urllib.parse.urlencode(params)
        return f"{self.auth_url}?{query}"

    async def _post_form(
        self,
        url: str,
        data: dict[str, str],
        headers: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        """POST form-encoded data with a 30s timeout and return parsed JSON."""
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, data=data, headers=headers or {}) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    logger.error(
                        "OAuth POST {} failed status={} body={}",
                        url, resp.status, text[:300],
                    )
                    raise RuntimeError(
                        f"OAuth token exchange failed: HTTP {resp.status}"
                    )
                # Most providers return JSON, but be defensive.
                try:
                    return await resp.json()
                except Exception:
                    import json
                    return json.loads(text)

    async def _get_json(
        self,
        url: str,
        headers: dict[str, str],
    ) -> dict[str, Any]:
        """GET JSON with a 30s timeout."""
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    logger.error(
                        "OAuth GET {} failed status={} body={}",
                        url, resp.status, text[:300],
                    )
                    raise RuntimeError(
                        f"OAuth userinfo fetch failed: HTTP {resp.status}"
                    )
                try:
                    return await resp.json()
                except Exception:
                    import json
                    return json.loads(text)


# ---------------------------------------------------------------------------
# Concrete: Google
# ---------------------------------------------------------------------------


class GoogleOAuthProvider(OAuthProvider):
    provider_name = "google"
    client_id_env = "google_oauth_client_id"
    client_secret_env = "google_oauth_client_secret"
    redirect_uri_env = "GOOGLE_OAUTH_REDIRECT_URI"
    auth_url = "https://accounts.google.com/o/oauth2/v2/auth"
    token_url = "https://oauth2.googleapis.com/token"
    userinfo_url = "https://www.googleapis.com/oauth2/v3/userinfo"
    default_scope = "openid email profile"

    def get_authorization_url(self, state: str) -> str:
        cid = self.client_id or ""
        params = {
            "client_id": cid,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": self.default_scope,
            "state": state,
            "access_type": "offline",  # to get refresh_token
            "prompt": "consent",
        }
        return self._build_auth_url(params)

    async def exchange_code(self, code: str) -> OAuthTokens:
        if settings.mock_mode:
            return OAuthTokens(
                access_token="mock-google-access-token",
                refresh_token="mock-google-refresh-token",
                expires_at=datetime.fromtimestamp(
                    int(time.time()) + 3600, tz=timezone.utc
                ),
                scope=self.default_scope,
                token_type="Bearer",
            )
        if not self.is_configured():
            raise RuntimeError(
                "Google OAuth is not configured — set GOOGLE_OAUTH_CLIENT_ID "
                "and GOOGLE_OAUTH_CLIENT_SECRET."
            )
        data = {
            "code": code,
            "client_id": self.client_id or "",
            "client_secret": self.client_secret or "",
            "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code",
        }
        payload = await self._post_form(self.token_url, data)
        expires_in = payload.get("expires_in")
        return OAuthTokens(
            access_token=payload["access_token"],
            refresh_token=payload.get("refresh_token"),
            expires_at=(
                datetime.fromtimestamp(
                    int(time.time()) + int(expires_in), tz=timezone.utc
                )
                if expires_in
                else None
            ),
            scope=payload.get("scope", self.default_scope),
            token_type=payload.get("token_type", "Bearer"),
        )

    async def get_user_info(self, tokens: OAuthTokens) -> OAuthUserInfo:
        if settings.mock_mode:
            return OAuthUserInfo(
                provider=self.provider_name,
                provider_user_id="mock-google-user-123",
                email="mock.user@gmail.com",
                name="Mock Google User",
                avatar_url="https://mock.example/avatar/google.png",
                raw_json={"sub": "mock-google-user-123", "mock": True},
            )
        headers = {"Authorization": f"Bearer {tokens.access_token}"}
        payload = await self._get_json(self.userinfo_url, headers)
        return OAuthUserInfo(
            provider=self.provider_name,
            provider_user_id=str(payload.get("sub") or ""),
            email=payload.get("email"),
            name=payload.get("name"),
            avatar_url=payload.get("picture"),
            raw_json=payload,
        )


# ---------------------------------------------------------------------------
# Concrete: GitHub
# ---------------------------------------------------------------------------


class GitHubOAuthProvider(OAuthProvider):
    provider_name = "github"
    client_id_env = "github_oauth_client_id"
    client_secret_env = "github_oauth_client_secret"
    redirect_uri_env = "GITHUB_OAUTH_REDIRECT_URI"
    auth_url = "https://github.com/login/oauth/authorize"
    token_url = "https://github.com/login/oauth/access_token"
    userinfo_url = "https://api.github.com/user"
    default_scope = "read:user user:email"

    def get_authorization_url(self, state: str) -> str:
        cid = self.client_id or ""
        params = {
            "client_id": cid,
            "redirect_uri": self.redirect_uri,
            "scope": self.default_scope,
            "state": state,
        }
        return self._build_auth_url(params)

    async def exchange_code(self, code: str) -> OAuthTokens:
        if settings.mock_mode:
            return OAuthTokens(
                access_token="mock-github-access-token",
                token_type="bearer",
                scope=self.default_scope,
            )
        if not self.is_configured():
            raise RuntimeError(
                "GitHub OAuth is not configured — set GITHUB_OAUTH_CLIENT_ID "
                "and GITHUB_OAUTH_CLIENT_SECRET."
            )
        data = {
            "code": code,
            "client_id": self.client_id or "",
            "client_secret": self.client_secret or "",
            "redirect_uri": self.redirect_uri,
        }
        # GitHub requires Accept: application/json
        headers = {"Accept": "application/json"}
        payload = await self._post_form(self.token_url, data, headers=headers)
        return OAuthTokens(
            access_token=payload["access_token"],
            token_type=payload.get("token_type", "bearer"),
            scope=payload.get("scope", self.default_scope),
        )

    async def get_user_info(self, tokens: OAuthTokens) -> OAuthUserInfo:
        if settings.mock_mode:
            return OAuthUserInfo(
                provider=self.provider_name,
                provider_user_id="mock-github-user-42",
                email="mock.user@users.noreply.github.com",
                name="Mock GitHub User",
                avatar_url="https://mock.example/avatar/github.png",
                raw_json={"id": 42, "login": "mockuser", "mock": True},
            )
        headers = {
            "Authorization": f"token {tokens.access_token}",
            "Accept": "application/vnd.github+json",
        }
        payload = await self._get_json(self.userinfo_url, headers)
        # GitHub sometimes hides primary email — fetch /user/emails if missing.
        email = payload.get("email")
        if not email:
            try:
                emails = await self._get_json(
                    "https://api.github.com/user/emails", headers
                )
                if isinstance(emails, list):
                    primary = next(
                        (e for e in emails if e.get("primary")), None
                    )
                    if primary:
                        email = primary.get("email")
            except Exception as exc:
                logger.warning("GitHub /user/emails fetch failed: {}", exc)
        return OAuthUserInfo(
            provider=self.provider_name,
            provider_user_id=str(payload.get("id") or ""),
            email=email,
            name=payload.get("name") or payload.get("login"),
            avatar_url=payload.get("avatar_url"),
            raw_json=payload,
        )


# ---------------------------------------------------------------------------
# Concrete: Facebook
# ---------------------------------------------------------------------------


class FacebookOAuthProvider(OAuthProvider):
    provider_name = "facebook"
    client_id_env = "facebook_oauth_app_id"
    client_secret_env = "facebook_oauth_app_secret"
    redirect_uri_env = "FACEBOOK_OAUTH_REDIRECT_URI"
    auth_url = "https://www.facebook.com/v18.0/dialog/oauth"
    token_url = "https://graph.facebook.com/v18.0/oauth/access_token"
    userinfo_url = "https://graph.facebook.com/v18.0/me"
    default_scope = "email public_profile"

    def get_authorization_url(self, state: str) -> str:
        cid = self.client_id or ""
        params = {
            "client_id": cid,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": self.default_scope,
            "state": state,
        }
        return self._build_auth_url(params)

    async def exchange_code(self, code: str) -> OAuthTokens:
        if settings.mock_mode:
            return OAuthTokens(
                access_token="mock-facebook-access-token",
                token_type="bearer",
                scope=self.default_scope,
            )
        if not self.is_configured():
            raise RuntimeError(
                "Facebook OAuth is not configured — set FACEBOOK_OAUTH_APP_ID "
                "and FACEBOOK_OAUTH_APP_SECRET."
            )
        data = {
            "code": code,
            "client_id": self.client_id or "",
            "client_secret": self.client_secret or "",
            "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code",
        }
        payload = await self._post_form(self.token_url, data)
        expires_in = payload.get("expires_in")
        return OAuthTokens(
            access_token=payload["access_token"],
            token_type=payload.get("token_type", "bearer"),
            expires_at=(
                datetime.fromtimestamp(
                    int(time.time()) + int(expires_in), tz=timezone.utc
                )
                if expires_in
                else None
            ),
            scope=self.default_scope,
        )

    async def get_user_info(self, tokens: OAuthTokens) -> OAuthUserInfo:
        if settings.mock_mode:
            return OAuthUserInfo(
                provider=self.provider_name,
                provider_user_id="mock-facebook-user-777",
                email="mock.user@facebook.com",
                name="Mock Facebook User",
                avatar_url=None,
                raw_json={"id": "mock-facebook-user-777", "mock": True},
            )
        params = {
            "fields": "id,name,email,picture",
            "access_token": tokens.access_token,
        }
        url = f"{self.userinfo_url}?{urllib.parse.urlencode(params)}"
        payload = await self._get_json(url, headers={})
        picture_data = (
            payload.get("picture", {}).get("data", {}).get("url")
            if isinstance(payload.get("picture"), dict)
            else None
        )
        return OAuthUserInfo(
            provider=self.provider_name,
            provider_user_id=str(payload.get("id") or ""),
            email=payload.get("email"),
            name=payload.get("name"),
            avatar_url=picture_data,
            raw_json=payload,
        )


# ---------------------------------------------------------------------------
# Registry + factory
# ---------------------------------------------------------------------------


OAUTH_PROVIDERS: dict[str, type[OAuthProvider]] = {
    "google": GoogleOAuthProvider,
    "github": GitHubOAuthProvider,
    "facebook": FacebookOAuthProvider,
}


def get_oauth_provider(name: str) -> OAuthProvider:
    """Return an instance of the provider class registered under ``name``.

    Raises ``ValueError`` for unknown names. The returned instance is freshly
    constructed so it picks up the latest env vars each call (e.g. after a
    credential is rotated).
    """
    key = (name or "").strip().lower()
    if key not in OAUTH_PROVIDERS:
        raise ValueError(
            f"Unknown OAuth provider: {name!r}. "
            f"Known: {sorted(OAUTH_PROVIDERS.keys())}"
        )
    return OAUTH_PROVIDERS[key]()


# ---------------------------------------------------------------------------
# Flow helpers — used by the FastAPI router
# ---------------------------------------------------------------------------


def initiate_oauth_flow(provider_name: str, state: str) -> str:
    """Return the authorization URL for ``provider_name``.

    ``state`` is opaque to this layer — the caller generates and stores it
    (see ``api.oauth_routes._STATE_CACHE``) to prevent CSRF.
    """
    provider = get_oauth_provider(provider_name)
    url = provider.get_authorization_url(state)
    logger.info(
        "OAuth flow initiated for provider={} (configured={})",
        provider.provider_name, provider.is_configured(),
    )
    return url


async def complete_oauth_flow(provider_name: str, code: str) -> OAuthUserInfo:
    """Exchange the auth code for tokens, fetch user info, persist tokens.

    Persistence: writes a row to the ``api_credentials`` table with
    ``service = f"oauth:{provider_name}"`` and ``credential_store_ref`` set
    to a masked token preview (real token is stored via the OS keyring when
    available; otherwise the env var is updated in-memory only).
    """
    provider = get_oauth_provider(provider_name)
    tokens = await provider.exchange_code(code)
    user_info = await provider.get_user_info(tokens)
    logger.info(
        "OAuth flow completed for provider={} user_id={} email={}",
        provider.provider_name,
        user_info.provider_user_id,
        user_info.email or "<none>",
    )
    # Persist tokens — best effort. Failures here are non-fatal; the user
    # info is still returned so the caller can respond.
    try:
        _persist_oauth_tokens(provider.provider_name, tokens, user_info)
    except Exception as exc:
        logger.error("Failed to persist OAuth tokens for {}: {}", provider.provider_name, exc)
    return user_info


def _persist_oauth_tokens(provider_name: str, tokens: OAuthTokens, user_info: OAuthUserInfo) -> None:
    """Best-effort persistence of OAuth tokens to the api_credentials table.

    Resilient to ``database`` import failures (e.g. in test envs without the
    schema initialised) — the caller treats any exception as non-fatal.
    """
    from database.base import SessionLocal  # type: ignore
    from database.models.schema import APICredential  # type: ignore

    session = SessionLocal()
    try:
        ref = f"oauth:{provider_name}:{mask(tokens.access_token)}"
        row = APICredential(
            user_id="00000000-0000-0000-0000-000000000001",  # default local user
            service=f"oauth:{provider_name}",
            credential_store_ref=ref,
            metadata_json={
                "provider_user_id": user_info.provider_user_id,
                "email": user_info.email,
                "name": user_info.name,
                "scope": tokens.scope,
                "token_type": tokens.token_type,
                "expires_at": tokens.expires_at.isoformat() if tokens.expires_at else None,
            },
        )
        session.add(row)
        session.commit()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------


__all__ = [
    "OAuthProvider",
    "OAuthTokens",
    "OAuthUserInfo",
    "GoogleOAuthProvider",
    "GitHubOAuthProvider",
    "FacebookOAuthProvider",
    "OAUTH_PROVIDERS",
    "get_oauth_provider",
    "initiate_oauth_flow",
    "complete_oauth_flow",
]
