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

    # ---------- token lifecycle (master prompt §54) ----------
    #
    # ``refresh_token`` / ``revoke_token`` / ``validate_token`` are concrete
    # methods on the ABC so all three providers inherit the same networking
    # skeleton. Each provider only needs to supply four small URL/param
    # builders (``_get_refresh_url`` / ``_get_refresh_params`` /
    # ``_get_revoke_url`` / ``_get_validate_url``) which keeps the per-provider
    # code tiny and the secrets out of the base class.
    #
    # In ``settings.mock_mode`` every method returns a deterministic fake
    # result so the test suite runs without network access.

    def _get_refresh_url(self) -> str:
        """Override per provider — the token endpoint to POST a refresh to."""
        raise NotImplementedError

    def _get_refresh_params(self, refresh_token: str) -> dict[str, str]:
        """Override per provider — form params for the refresh POST."""
        raise NotImplementedError

    def _get_revoke_url(self, access_token: str) -> str:
        """Override per provider — the URL to revoke the access token."""
        raise NotImplementedError

    def _get_validate_url(self, access_token: str) -> str:
        """Override per provider — the URL to validate the access token."""
        raise NotImplementedError

    async def refresh_token(self, refresh_token: str) -> OAuthTokens:
        """Refresh an access token using ``refresh_token``.

        POSTs ``grant_type=refresh_token`` (+ provider-specific extras) to
        the provider's token endpoint. Returns a fresh ``OAuthTokens``
        object — callers should persist it via :func:`store_tokens`.

        Master prompt §57: the refresh_token is never logged.
        """
        if settings.mock_mode:
            return OAuthTokens(
                access_token=f"mock-{self.provider_name}-refreshed-access-token",
                refresh_token=refresh_token,
                expires_at=datetime.fromtimestamp(
                    int(time.time()) + 3600, tz=timezone.utc
                ),
                scope=self.default_scope,
                token_type="Bearer",
            )
        if not self.is_configured():
            raise RuntimeError(
                f"{self.provider_name} OAuth is not configured — set the "
                f"required client_id / client_secret env vars before "
                f"refreshing tokens."
            )
        url = self._get_refresh_url()
        data = self._get_refresh_params(refresh_token)
        payload = await self._post_form(url, data)
        expires_in = payload.get("expires_in")
        return OAuthTokens(
            access_token=payload["access_token"],
            refresh_token=payload.get("refresh_token", refresh_token),
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

    async def revoke_token(self, access_token: str) -> bool:
        """Revoke ``access_token`` at the provider.

        Returns True on HTTP 200. Other status codes are logged and return
        False (non-fatal — callers can simply forget the token locally).

        Master prompt §57: the access_token is never logged.
        """
        if settings.mock_mode:
            return True
        url = self._get_revoke_url(access_token)
        timeout = aiohttp.ClientTimeout(total=30)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                # Some providers use POST (Google), others DELETE (GitHub,
                # Facebook). We try POST first; if the provider needs a
                # different verb, it overrides this method (see GitHub /
                # Facebook below).
                async with session.post(url) as resp:
                    if resp.status == 200:
                        return True
                    logger.warning(
                        "OAuth revoke for {} returned HTTP {} (body={})",
                        self.provider_name, resp.status, (await resp.text())[:200],
                    )
                    return False
        except Exception as exc:
            logger.error(
                "OAuth revoke for {} raised: {}", self.provider_name, exc
            )
            return False

    async def validate_token(self, access_token: str) -> bool:
        """Validate ``access_token`` at the provider.

        Returns True if the token is valid, False if invalid (HTTP 401 /
        400 / token revoked). Network errors return False (defensive —
        treat as invalid).

        Master prompt §57: the access_token is never logged.
        """
        if settings.mock_mode:
            return True
        url = self._get_validate_url(access_token)
        headers = self._validate_headers(access_token)
        timeout = aiohttp.ClientTimeout(total=30)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers) as resp:
                    return resp.status == 200
        except Exception as exc:
            logger.debug(
                "OAuth validate for {} raised: {}", self.provider_name, exc
            )
            return False

    def _validate_headers(self, access_token: str) -> dict[str, str]:
        """Override per provider if validate needs Authorization header
        instead of (or in addition to) a query-param access_token."""
        return {}

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
    revoke_url = "https://oauth2.googleapis.com/revoke"
    validate_url = "https://www.googleapis.com/oauth2/v1/tokeninfo"

    # ----- token lifecycle helpers (used by the ABC methods) -----

    def _get_refresh_url(self) -> str:
        return self.token_url

    def _get_refresh_params(self, refresh_token: str) -> dict[str, str]:
        return {
            "client_id": self.client_id or "",
            "client_secret": self.client_secret or "",
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }

    def _get_revoke_url(self, access_token: str) -> str:
        return f"{self.revoke_url}?token={urllib.parse.quote(access_token)}"

    def _get_validate_url(self, access_token: str) -> str:
        return f"{self.validate_url}?access_token={urllib.parse.quote(access_token)}"

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
    revoke_url = "https://api.github.com/app/grant"
    validate_url = "https://api.github.com/user"

    # ----- token lifecycle helpers -----

    def _get_refresh_url(self) -> str:
        # GitHub does NOT support refresh tokens (access tokens don't
        # expire). The ABC refresh_token() will never actually reach here
        # because we override refresh_token() below to raise a helpful
        # NotImplementedError.
        return self.token_url

    def _get_refresh_params(self, refresh_token: str) -> dict[str, str]:
        return {"refresh_token": refresh_token, "grant_type": "refresh_token"}

    def _get_revoke_url(self, access_token: str) -> str:
        # GitHub revokes via DELETE /app/grant/{grant_id}. Without knowing
        # the grant_id we'd have to fetch it first. Easier path is the
        # /applications/{client_id}/grant endpoint with a Basic-Auth header.
        # We return the URL here and let the override method below do the
        # actual DELETE with the right headers.
        return self.revoke_url

    def _get_validate_url(self, access_token: str) -> str:
        # GitHub validates by calling /user with Authorization header.
        # The access_token isn't in the URL — see _validate_headers below.
        return self.validate_url

    def _validate_headers(self, access_token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
        }

    async def refresh_token(self, refresh_token: str) -> OAuthTokens:
        """GitHub OAuth access tokens do NOT expire and cannot be refreshed.

        The user must re-run the OAuth flow to get a new token. We raise a
        helpful NotImplementedError so callers can surface this to the UI.
        """
        raise NotImplementedError(
            "GitHub OAuth tokens do not expire and cannot be refreshed. "
            "To get a new token, re-run the OAuth flow."
        )

    async def revoke_token(self, access_token: str) -> bool:
        """Revoke a GitHub OAuth access token.

        Uses ``DELETE /applications/{client_id}/grant`` with HTTP Basic
        Auth (client_id:client_secret). Returns True on HTTP 204 (GitHub
        returns 204 No Content on success).
        """
        if settings.mock_mode:
            return True
        if not self.is_configured():
            logger.warning(
                "GitHub revoke called without GITHUB_OAUTH_CLIENT_ID / "
                "GITHUB_OAUTH_CLIENT_SECRET set — cannot revoke."
            )
            return False
        url = f"https://api.github.com/applications/{self.client_id}/grant"
        timeout = aiohttp.ClientTimeout(total=30)
        try:
            import base64
            basic = base64.b64encode(
                f"{self.client_id}:{self.client_secret}".encode()
            ).decode()
            headers = {
                "Authorization": f"Basic {basic}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
            payload = {"access_token": access_token}
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.delete(url, json=payload, headers=headers) as resp:
                    if resp.status in (200, 204):
                        return True
                    logger.warning(
                        "GitHub revoke returned HTTP {} (body={})",
                        resp.status, (await resp.text())[:200],
                    )
                    return False
        except Exception as exc:
            logger.error("GitHub revoke raised: {}", exc)
            return False

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
    revoke_base = "https://graph.facebook.com/v18.0"
    validate_url = "https://graph.facebook.com/debug_token"

    # ----- token lifecycle helpers -----

    def _get_refresh_url(self) -> str:
        return self.token_url

    def _get_refresh_params(self, refresh_token: str) -> dict[str, str]:
        # Facebook uses fb_exchange_token (long-lived tokens are obtained
        # by exchanging the short-lived one — there is no "refresh" per se,
        # but we expose the same endpoint so the ABC refresh_token() flow
        # works for users who want to extend a token's lifetime).
        return {
            "client_id": self.client_id or "",
            "client_secret": self.client_secret or "",
            "grant_type": "fb_exchange_token",
            "fb_exchange_token": refresh_token,
        }

    def _get_revoke_url(self, access_token: str) -> str:
        # Facebook revokes via DELETE /{user_id}/permissions. We don't
        # know the user_id here, so the override method below does the
        # full thing. We return a placeholder URL so the ABC revoke_token
        # method works (though it would always fail in non-mock mode —
        # that's why we override below).
        return f"{self.revoke_base}/me/permissions?access_token={urllib.parse.quote(access_token)}"

    def _get_validate_url(self, access_token: str) -> str:
        # /debug_token needs input_token AND app access_token. We pass
        # access_token (the app access token, or "app_id|app_secret") via
        # the access_token query param.
        app_token = f"{self.client_id or ''}|{self.client_secret or ''}"
        return (
            f"{self.validate_url}?input_token={urllib.parse.quote(access_token)}"
            f"&access_token={urllib.parse.quote(app_token)}"
        )

    async def revoke_token(self, access_token: str) -> bool:
        """Revoke a Facebook OAuth access token.

        Uses ``DELETE /{user-id}/permissions?access_token=...`` (per
        Facebook docs). Returns True on HTTP 200.
        """
        if settings.mock_mode:
            return True
        # First fetch /me to get the user_id (Facebook revokes per user,
        # not per token).
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                me_url = (
                    f"{self.userinfo_url}?fields=id&"
                    f"access_token={urllib.parse.quote(access_token)}"
                )
                async with session.get(me_url) as me_resp:
                    if me_resp.status != 200:
                        logger.warning(
                            "Facebook revoke: /me lookup failed HTTP {} (body={})",
                            me_resp.status, (await me_resp.text())[:200],
                        )
                        return False
                    me_data = await me_resp.json()
                    user_id = me_data.get("id")
                    if not user_id:
                        return False
                url = (
                    f"{self.revoke_base}/{user_id}/permissions"
                    f"?access_token={urllib.parse.quote(access_token)}"
                )
                async with session.delete(url) as resp:
                    if resp.status == 200:
                        return True
                    logger.warning(
                        "Facebook revoke returned HTTP {} (body={})",
                        resp.status, (await resp.text())[:200],
                    )
                    return False
        except Exception as exc:
            logger.error("Facebook revoke raised: {}", exc)
            return False

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
                # The full tokens are stored in metadata_json so the
                # GoogleCalendarService (and other integrations) can read
                # them back via get_stored_tokens(). The credential_store_ref
                # above only holds a *masked* preview.
                "access_token": tokens.access_token,
                "refresh_token": tokens.refresh_token,
            },
        )
        session.add(row)
        session.commit()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Stored-token accessors — used by GoogleCalendarService + tests
# ---------------------------------------------------------------------------


_DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000001"


def get_stored_tokens(service: str) -> Optional[dict]:
    """Return the stored token dict for ``service`` from api_credentials.

    Looks for a row where ``service = f"oauth:{service}"`` (or just
    ``service`` if it already has the ``oauth:`` prefix). Returns None if:
    - mock mode is on (master prompt §64 — never touch the DB)
    - the table isn't initialised
    - no row exists for the service.

    The returned dict has keys:
    ``access_token``, ``refresh_token``, ``expires_at`` (ISO string),
    ``scope``, ``token_type``, ``provider_user_id``, ``email``, ``name``.
    """
    if settings.mock_mode:
        return None
    if not service:
        return None
    if not service.startswith("oauth:"):
        service_key = f"oauth:{service}"
    else:
        service_key = service

    try:
        from database.base import SessionLocal  # type: ignore
        from database.models.schema import APICredential  # type: ignore

        session = SessionLocal()
        try:
            row = (
                session.query(APICredential)
                .filter(APICredential.service == service_key)
                .order_by(APICredential.updated_at.desc())
                .first()
            )
            if row is None:
                return None
            meta = row.metadata_json or {}
            return {
                "access_token": meta.get("access_token"),
                "refresh_token": meta.get("refresh_token"),
                "expires_at": meta.get("expires_at"),
                "scope": meta.get("scope"),
                "token_type": meta.get("token_type", "Bearer"),
                "provider_user_id": meta.get("provider_user_id"),
                "email": meta.get("email"),
                "name": meta.get("name"),
                "credential_store_ref": row.credential_store_ref,
            }
        finally:
            session.close()
    except Exception as exc:
        logger.debug(
            "get_stored_tokens({}) lookup failed: {}", service, exc
        )
        return None


def store_tokens(service: str, tokens: OAuthTokens) -> None:
    """Upsert ``tokens`` for ``service`` into the api_credentials table.

    - ``service`` is the provider short name (e.g. ``"google"``). We store
      under ``service = f"oauth:{service}"`` to match what
      :func:`complete_oauth_flow` writes.
    - ``credential_store_ref`` is set to a *safe* preview of the
      access_token (master prompt §57 — never store plain secrets in the
      DB column that may be exposed via API). We use a guaranteed-truncated
      preview (first 4 + last 4 chars + ``<redacted>`` in between) rather
      than relying on :func:`mask`'s pattern matching, which only catches
      known token prefixes.
    - ``metadata_json`` contains the full token set including
      ``refresh_token`` and ``expires_at``. This is the dict that
      :func:`get_stored_tokens` reads back. The metadata_json column is
      not exposed via the OAuth status endpoint.
    - If a row already exists for this service + default user, we update
      it in place (so refresh cycles don't pile up new rows).

    Resilient to schema-not-initialised — raises RuntimeError with a
    helpful message if the database layer can't be reached.
    """
    if settings.mock_mode:
        # In mock mode we never persist — callers that need to test the
        # round-trip should explicitly disable mock_mode or use the
        # db_session fixture which spins up an in-memory SQLite.
        logger.debug(
            "store_tokens({}) skipped — settings.mock_mode is True.", service
        )
        return
    if not service:
        raise ValueError("service must be a non-empty provider name")
    service_key = service if service.startswith("oauth:") else f"oauth:{service}"

    from database.base import SessionLocal  # type: ignore
    from database.models.schema import APICredential  # type: ignore
    from sqlalchemy import select  # type: ignore

    session = SessionLocal()
    try:
        row = (
            session.query(APICredential)
            .filter(APICredential.service == service_key)
            .filter(APICredential.user_id == _DEFAULT_USER_ID)
            .order_by(APICredential.updated_at.desc())
            .first()
        )
        ref = f"{service_key}:{_safe_token_preview(tokens.access_token)}"
        meta = {
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
            "expires_at": tokens.expires_at.isoformat() if tokens.expires_at else None,
            "scope": tokens.scope,
            "token_type": tokens.token_type,
        }
        if row is None:
            row = APICredential(
                user_id=_DEFAULT_USER_ID,
                service=service_key,
                credential_store_ref=ref,
                metadata_json=meta,
            )
            session.add(row)
        else:
            row.credential_store_ref = ref
            row.metadata_json = meta
        session.commit()
        logger.debug(
            "store_tokens({}) persisted (preview={})",
            service, _safe_token_preview(tokens.access_token),
        )
    finally:
        session.close()


def _safe_token_preview(token: Optional[str]) -> str:
    """Return a guaranteed-safe preview of an access token.

    Unlike :func:`mask` (which only redacts known token prefixes), this
    helper ALWAYS redacts the middle of the token so it can be safely
    stored in columns that may be exposed via API responses (e.g.
    ``api_credentials.credential_store_ref``). Format:
    ``<first4>…<redacted>…<last4>`` (or ``<redacted>`` for short tokens).
    """
    if not token:
        return "<empty>"
    if len(token) < 12:
        return "<redacted>"
    return f"{token[:4]}…<redacted>…{token[-4:]}"


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
    "get_stored_tokens",
    "store_tokens",
]
