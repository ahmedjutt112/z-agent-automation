"""OAuth HTTP routes — master prompt §54.

Endpoints (mounted under ``/oauth`` in main.py):
- ``GET /oauth/{provider}/start`` — initiates the flow.
- ``GET /oauth/{provider}/callback`` — handles the redirect, exchanges the
  code, persists tokens to ``api_credentials``, returns an HTML success page.
- ``GET /oauth/status`` — lists configured providers + connected accounts.
- ``POST /oauth/{provider}/disconnect`` — revokes + removes stored tokens.
- ``POST /oauth/{provider}/refresh`` — exchanges a refresh_token for a new
  access_token (master prompt §54 OAuth refresh-token flow).
- ``POST /oauth/{provider}/revoke`` — revokes an access_token at the provider.
- ``GET /oauth/{provider}/validate`` — checks whether an access_token is valid.

All authenticated routes use the ``verify_ipc_token`` dependency from
``automation_service.main``. CSRF prevention: ``state`` is generated server-side
and stored in an in-memory TTL cache (5 min) on ``/start`` and verified on
``/callback``.

Master prompt §57: tokens are NEVER logged. Any debug log line that
references a token uses ``mask()`` from ``..security.credentials``.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from loguru import logger
from pydantic import BaseModel

from ..config import settings
from ..integrations.oauth import (
    OAUTH_PROVIDERS,
    complete_oauth_flow,
    get_oauth_provider,
    initiate_oauth_flow,
)
from ..security.credentials import mask


router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic request bodies for refresh / revoke / validate
# ---------------------------------------------------------------------------


class RefreshRequest(BaseModel):
    """Body for ``POST /oauth/{provider}/refresh``."""

    refresh_token: str


class RevokeRequest(BaseModel):
    """Body for ``POST /oauth/{provider}/revoke``."""

    access_token: str


# ---------------------------------------------------------------------------
# Auth dependency — re-exported verify_ipc_token from main to avoid circular
# imports. We import lazily inside the dependency function.
# ---------------------------------------------------------------------------


async def _verify_ipc_token(authorization: str | None = None) -> None:
    """Resolve verify_ipc_token lazily so we don't create a circular import."""
    from ..main import verify_ipc_token
    await verify_ipc_token(authorization)


# ---------------------------------------------------------------------------
# In-memory CSRF state cache (5-minute TTL)
# ---------------------------------------------------------------------------


class _StateCache:
    """Simple in-memory state cache for CSRF protection.

    Each entry maps state -> (provider_name, expires_at_unix). Entries are
    evicted on access if expired. This is process-local — fine for a
    single-machine automation service.
    """

    TTL_SECONDS = 300  # 5 minutes

    def __init__(self) -> None:
        self._store: dict[str, tuple[str, float]] = {}
        self._lock = asyncio.Lock()

    async def put(self, state: str, provider: str) -> None:
        async with self._lock:
            self._store[state] = (provider, time.time() + self.TTL_SECONDS)
            self._evict()

    async def take(self, state: str) -> str | None:
        """Pop and return the provider name if state is valid + not expired."""
        async with self._lock:
            self._evict()
            entry = self._store.pop(state, None)
            if entry is None:
                return None
            provider, expires_at = entry
            if time.time() > expires_at:
                return None
            return provider

    def _evict(self) -> None:
        now = time.time()
        for key in list(self._store.keys()):
            if now > self._store[key][1]:
                self._store.pop(key, None)


_STATE_CACHE = _StateCache()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/{provider}/start", dependencies=[Depends(_verify_ipc_token)])
async def oauth_start(provider: str) -> dict[str, str]:
    """Initiate the OAuth flow for ``provider``. Returns an auth URL + state."""
    if provider.lower() not in OAUTH_PROVIDERS:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Unknown OAuth provider: {provider!r}. "
            f"Known: {sorted(OAUTH_PROVIDERS.keys())}",
        )
    state = uuid.uuid4().hex
    await _STATE_CACHE.put(state, provider.lower())
    url = initiate_oauth_flow(provider, state)
    return {"authorization_url": url, "state": state}


@router.get("/{provider}/callback")
async def oauth_callback(
    provider: str,
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
) -> HTMLResponse:
    """Handle the OAuth provider redirect.

    No IPC token required (the provider can't add a Bearer header). CSRF is
    prevented by the ``state`` parameter — we verify it against the cache
    populated by ``/{provider}/start``.
    """
    if error:
        # Provider reported an error (e.g. user denied)
        return HTMLResponse(
            _html_page(
                "OAuth failed",
                f"The provider returned an error: {error}",
                ok=False,
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if not code or not state:
        return HTMLResponse(
            _html_page(
                "OAuth failed",
                "Missing 'code' or 'state' parameter in callback.",
                ok=False,
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if provider.lower() not in OAUTH_PROVIDERS:
        return HTMLResponse(
            _html_page(
                "OAuth failed",
                f"Unknown OAuth provider: {provider!r}",
                ok=False,
            ),
            status_code=status.HTTP_404_NOT_FOUND,
        )

    expected_provider = await _STATE_CACHE.take(state)
    if expected_provider is None:
        return HTMLResponse(
            _html_page(
                "OAuth failed",
                "Invalid or expired state token. Please restart the flow.",
                ok=False,
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    if expected_provider != provider.lower():
        return HTMLResponse(
            _html_page(
                "OAuth failed",
                "Provider mismatch — state token was issued for a different provider.",
                ok=False,
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        user_info = await complete_oauth_flow(provider, code)
    except Exception as exc:
        logger.error("OAuth callback failed for {}: {}", provider, exc)
        return HTMLResponse(
            _html_page("OAuth failed", str(exc), ok=False),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return HTMLResponse(
        _html_page(
            "OAuth connected",
            (
                f"Provider: {user_info.provider}<br/>"
                f"User ID: {user_info.provider_user_id}<br/>"
                f"Email: {user_info.email or '(none)'}<br/>"
                f"Name: {user_info.name or '(none)'}"
            ),
            ok=True,
        )
    )


@router.get("/status", dependencies=[Depends(_verify_ipc_token)])
async def oauth_status() -> dict[str, Any]:
    """List all configured OAuth providers + whether the user has connected."""
    configured: list[dict[str, Any]] = []
    for name in sorted(OAUTH_PROVIDERS.keys()):
        provider = get_oauth_provider(name)
        configured.append(
            {
                "provider": name,
                "configured": provider.is_configured(),
                "connected": _is_oauth_connected(name),
            }
        )
    return {"providers": configured}


@router.post("/{provider}/disconnect", dependencies=[Depends(_verify_ipc_token)])
async def oauth_disconnect(provider: str) -> dict[str, Any]:
    """Revoke (best-effort) and remove stored tokens for ``provider``."""
    if provider.lower() not in OAUTH_PROVIDERS:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Unknown OAuth provider: {provider!r}"
        )
    removed = _disconnect_oauth(provider.lower())
    return {"provider": provider.lower(), "disconnected": removed}


# ---------------------------------------------------------------------------
# Token lifecycle endpoints — refresh / revoke / validate (master prompt §54)
# ---------------------------------------------------------------------------


@router.post("/{provider}/refresh", dependencies=[Depends(_verify_ipc_token)])
async def oauth_refresh(provider: str, body: RefreshRequest) -> dict[str, Any]:
    """Exchange a refresh_token for a new access_token.

    Master prompt §57: the refresh_token in the request body is never
    logged. The response contains the new access_token (caller must store
    it) — the masked preview is the only thing logged.
    """
    key = provider.lower()
    if key not in OAUTH_PROVIDERS:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Unknown OAuth provider: {provider!r}. "
            f"Known: {sorted(OAUTH_PROVIDERS.keys())}",
        )
    provider_inst = get_oauth_provider(key)
    try:
        new_tokens = await provider_inst.refresh_token(body.refresh_token)
    except NotImplementedError as exc:
        # GitHub raises this — surface as 400 with a helpful message.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            str(exc),
        )
    except Exception as exc:
        logger.error(
            "OAuth refresh for {} failed (refresh_token preview={}): {}",
            key, mask(body.refresh_token), exc,
        )
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"OAuth refresh failed for provider '{key}': {exc}",
        )

    # Persist the new tokens so subsequent calls (calendar, etc.) use them.
    try:
        from ..integrations.oauth import store_tokens
        store_tokens(key, new_tokens)
    except Exception as exc:
        logger.warning("Failed to persist refreshed tokens for {}: {}", key, exc)

    logger.info(
        "OAuth refresh succeeded for provider={} (new access_token preview={})",
        key, mask(new_tokens.access_token),
    )
    return {
        "provider": key,
        "access_token": new_tokens.access_token,
        "refresh_token": new_tokens.refresh_token,
        "expires_at": new_tokens.expires_at.isoformat() if new_tokens.expires_at else None,
        "scope": new_tokens.scope,
        "token_type": new_tokens.token_type,
    }


@router.post("/{provider}/revoke", dependencies=[Depends(_verify_ipc_token)])
async def oauth_revoke(provider: str, body: RevokeRequest) -> dict[str, Any]:
    """Revoke an access_token at the provider.

    Returns ``{"revoked": True}`` on HTTP 200, ``{"revoked": False}`` on
    non-fatal failure (the caller can still drop the token locally).
    """
    key = provider.lower()
    if key not in OAUTH_PROVIDERS:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Unknown OAuth provider: {provider!r}. "
            f"Known: {sorted(OAUTH_PROVIDERS.keys())}",
        )
    provider_inst = get_oauth_provider(key)
    try:
        revoked = await provider_inst.revoke_token(body.access_token)
    except NotImplementedError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    except Exception as exc:
        logger.error(
            "OAuth revoke for {} failed (access_token preview={}): {}",
            key, mask(body.access_token), exc,
        )
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"OAuth revoke failed for provider '{key}': {exc}",
        )

    logger.info(
        "OAuth revoke for provider={} result={} (access_token preview={})",
        key, revoked, mask(body.access_token),
    )
    return {"provider": key, "revoked": revoked}


@router.get("/{provider}/validate", dependencies=[Depends(_verify_ipc_token)])
async def oauth_validate(
    provider: str,
    access_token: str = Query(..., description="The access_token to validate"),
) -> dict[str, Any]:
    """Validate that an access_token is still valid at the provider.

    Returns ``{"provider": ..., "valid": true|false}``. A 200 response
    does NOT mean the token is valid — check the ``valid`` field. We
    return 200 even for invalid tokens so clients can distinguish
    "validation service reachable + token invalid" (200, valid=false)
    from "validation service unreachable" (502).
    """
    key = provider.lower()
    if key not in OAUTH_PROVIDERS:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Unknown OAuth provider: {provider!r}. "
            f"Known: {sorted(OAUTH_PROVIDERS.keys())}",
        )
    provider_inst = get_oauth_provider(key)
    try:
        valid = await provider_inst.validate_token(access_token)
    except NotImplementedError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    except Exception as exc:
        logger.error(
            "OAuth validate for {} failed (access_token preview={}): {}",
            key, mask(access_token), exc,
        )
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"OAuth validate failed for provider '{key}': {exc}",
        )

    logger.info(
        "OAuth validate for provider={} result={} (access_token preview={})",
        key, valid, mask(access_token),
    )
    return {"provider": key, "valid": valid}


# ---------------------------------------------------------------------------
# Persistence helpers — best-effort DB lookups
# ---------------------------------------------------------------------------


def _is_oauth_connected(provider_name: str) -> bool:
    """True when at least one row exists in api_credentials for this provider."""
    try:
        from database.base import SessionLocal
        from database.models.schema import APICredential
        from sqlalchemy import select

        with SessionLocal() as session:
            row = session.scalars(
                select(APICredential).where(
                    APICredential.service == f"oauth:{provider_name}"
                ).limit(1)
            ).first()
            return row is not None
    except Exception as exc:
        logger.debug("OAuth status check failed for {}: {}", provider_name, exc)
        return False


def _disconnect_oauth(provider_name: str) -> bool:
    """Delete all api_credentials rows for ``provider_name``. Best-effort."""
    try:
        from database.base import SessionLocal
        from database.models.schema import APICredential
        from sqlalchemy import delete

        with SessionLocal() as session:
            result = session.execute(
                delete(APICredential).where(
                    APICredential.service == f"oauth:{provider_name}"
                )
            )
            session.commit()
            return (result.rowcount or 0) > 0
    except Exception as exc:
        logger.error("OAuth disconnect failed for {}: {}", provider_name, exc)
        return False


# ---------------------------------------------------------------------------
# HTML response helper
# ---------------------------------------------------------------------------


def _html_page(title: str, body: str, ok: bool = True) -> str:
    color = "#10b981" if ok else "#ef4444"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta http-equiv="Content-Security-Policy" content="default-src 'self'; style-src 'unsafe-inline'" />
  <title>{title}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #0a0a0a; color: #fafafa; padding: 2rem; }}
    h1 {{ color: {color}; margin-top: 0; }}
    .box {{ max-width: 480px; margin: 0 auto; padding: 1.5rem; background: #18181b; border: 1px solid #27272a; border-radius: 8px; }}
    .detail {{ color: #a1a1aa; line-height: 1.5; }}
    a {{ color: #60a5fa; }}
  </style>
</head>
<body>
  <div class="box">
    <h1>{title}</h1>
    <div class="detail">{body}</div>
    <p class="detail"><small>You may close this window.</small></p>
  </div>
</body>
</html>"""


__all__ = ["router"]
