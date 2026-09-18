"""AI Models + Providers FastAPI router — master prompt §6 (52 AI providers).

Mounted under both ``/ai-models`` and ``/providers`` and ``/credentials``
in main.py (see main.py for the include_router calls). Endpoints:

AI models:
* ``GET  /ai-models``                — list synced models (optional ?provider=)
* ``POST /ai-models/sync``            — sync models from providers (?provider= for one)

Providers:
* ``GET  /providers``                 — list all 52 providers with has_credential flag
* ``POST /providers/test/{name}``     — test connection to a provider

Credentials (master prompt §28 / §57 — secrets NEVER logged or returned):
* ``GET    /credentials``             — list services that have a credential
* ``POST   /credentials``             — store a credential in OS keyring
* ``DELETE /credentials/{service}``   — remove a credential

All routes require the IPC bearer token.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError

from ..config import settings


router = APIRouter()


# ---------------------------------------------------------------------------
# Auth dependency — lazy import avoids circular dep with main.
# ---------------------------------------------------------------------------


async def _verify_ipc_token(authorization: str | None = None) -> None:
    from ..main import verify_ipc_token

    await verify_ipc_token(authorization)


# ---------------------------------------------------------------------------
# Registry import — ``ai_providers`` lives OUTSIDE the automation_service
# package (so it's importable from the zai CLI). The model_sync helper
# already shims sys.path, but we replicate it here so direct imports work.
# ---------------------------------------------------------------------------


def _ensure_registry_on_path() -> None:
    """Make the top-level ``ai_providers`` package importable."""
    automation_root = str(Path(__file__).resolve().parents[3])
    if automation_root not in sys.path:
        sys.path.insert(0, automation_root)


_ensure_registry_on_path()

from ai_providers import registry as provider_registry  # type: ignore  # noqa: E402

from ..security.credentials import (  # noqa: E402
    get_credential,
    list_known_services,
    mask,
    set_credential,
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CredentialWrite(BaseModel):
    """Body of ``POST /credentials``."""

    service: str = Field(..., description="Credential service name, e.g. 'openai_api_key'")
    value: str = Field(..., description="The secret value to store in the OS keyring.")


class SyncResponse(BaseModel):
    """Body of ``POST /ai-models/sync`` response."""

    synced: dict[str, int]
    mock_mode: bool


class TestResponse(BaseModel):
    """Body of ``POST /providers/test/{name}`` response."""

    provider: str
    ok: bool
    message: str
    mock_mode: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _open_session():
    try:
        from database.base import SessionLocal
        from database.models import schema  # noqa: F401
    except Exception:
        return None
    try:
        return SessionLocal()
    except Exception:
        return None


def _provider_has_credential(name: str) -> bool:
    info = provider_registry.PROVIDERS.get(name) or {}
    env_key = info.get("env_key")
    if not env_key:
        # Local providers (ollama, lm_studio) don't need a credential.
        return True
    val = get_credential(env_key)
    return bool(val)


# ---------------------------------------------------------------------------
# Routes — AI models
# ---------------------------------------------------------------------------


@router.get(
    "/ai-models",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["ai-models"],
)
async def ai_models_list(provider: Optional[str] = Query(None)) -> dict[str, Any]:
    """List synced AI models from the database.

    Returns an empty list when the DB is unavailable (mock mode) so the
    UI can render an empty state without crashing.
    """
    session = _open_session()
    if session is None:
        return {
            "models": [],
            "count": 0,
            "provider": provider,
            "mock_mode": True,
        }
    try:
        from database.models.schema import AIModel, AIProvider

        q = session.query(AIModel)
        if provider:
            q = q.join(AIProvider).filter(AIProvider.name == provider)
        rows = q.order_by(AIModel.display_name.asc()).limit(1000).all()
        out = [
            {
                "id": r.id,
                "model_id": r.model_id,
                "display_name": r.display_name,
                "provider_id": r.provider_id,
                "supports_vision": r.supports_vision,
                "supports_reasoning": r.supports_reasoning,
                "max_tokens": r.max_tokens,
                "enabled": r.enabled,
            }
            for r in rows
        ]
        return {
            "models": out,
            "count": len(out),
            "provider": provider,
            "mock_mode": bool(settings.mock_mode),
        }
    except SQLAlchemyError:
        # Tables missing — return empty list rather than crash.
        return {
            "models": [],
            "count": 0,
            "provider": provider,
            "mock_mode": True,
        }
    finally:
        session.close()


@router.post(
    "/ai-models/sync",
    response_model=SyncResponse,
    dependencies=[Depends(_verify_ipc_token)],
    tags=["ai-models"],
)
async def ai_models_sync(provider: Optional[str] = Query(None)) -> dict[str, Any]:
    """Sync models from providers.

    Pass ``?provider=openai`` to sync just one provider. Without it, every
    provider in the registry is queried. Providers without a credential
    return count=0 (and are skipped silently).

    In mock mode, the sync still attempts to call providers, but local
    providers are skipped so the result is a dict of zeros.
    """
    try:
        from ..ai_providers.model_sync import sync_models

        session = _open_session()
        if session is None:
            # No DB — return a per-provider zero dict so the UI shows
            # something useful.
            results = {name: 0 for name in provider_registry.PROVIDERS}
            return {"synced": results, "mock_mode": True}
        try:
            results = await sync_models(session, include_vercel_gateway=True)
        finally:
            session.close()

        if provider is not None:
            results = {provider: results.get(provider, 0)}
        return {"synced": results, "mock_mode": bool(settings.mock_mode)}
    except Exception as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"sync failed: {exc}",
        )


# ---------------------------------------------------------------------------
# Routes — providers
# ---------------------------------------------------------------------------


@router.get(
    "/providers",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["ai-models"],
)
async def providers_list() -> dict[str, Any]:
    """List all 52 providers with metadata + has_credential flag."""
    out: list[dict[str, Any]] = []
    for name, info in sorted(provider_registry.PROVIDERS.items()):
        out.append(
            {
                "name": name,
                "display_name": info.get("display_name", name),
                "base_url": info.get("base_url"),
                "env_key": info.get("env_key"),
                "default_model": info.get("default_model"),
                "openai_compatible": bool(info.get("openai_compatible", False)),
                "supports_model_list": bool(info.get("supports_model_list", False)),
                "docs_url": info.get("docs_url"),
                "notes": info.get("notes"),
                "has_credential": _provider_has_credential(name),
            }
        )
    return {
        "providers": out,
        "count": len(out),
        "default_provider": settings.default_ai_provider,
        "default_model": settings.default_ai_model,
        "mock_mode": bool(settings.mock_mode),
    }


@router.post(
    "/providers/test/{name}",
    response_model=TestResponse,
    dependencies=[Depends(_verify_ipc_token)],
    tags=["ai-models"],
)
async def providers_test(name: str) -> dict[str, Any]:
    """Test a connection to a provider by listing its models.

    In mock mode the route always returns ``ok=True`` (the underlying
    provider is never called) so the UI can show a friendly message.
    """
    info = provider_registry.PROVIDERS.get(name)
    if info is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"provider '{name}' not in registry (52 supported)",
        )
    if settings.mock_mode:
        return {
            "provider": name,
            "ok": True,
            "message": "mock mode — connection test skipped",
            "mock_mode": True,
        }

    # Real mode — try the model-sync path.
    try:
        from ..ai_providers.model_sync import sync_models

        session = _open_session()
        if session is None:
            return {
                "provider": name,
                "ok": False,
                "message": "database unavailable — cannot sync models",
                "mock_mode": False,
            }
        try:
            results = await sync_models(session, include_vercel_gateway=False)
            count = results.get(name, 0)
            return {
                "provider": name,
                "ok": count > 0,
                "message": f"synced {count} models from {name}",
                "mock_mode": False,
            }
        finally:
            session.close()
    except Exception as exc:
        return {
            "provider": name,
            "ok": False,
            "message": f"test failed: {exc}",
            "mock_mode": False,
        }


# ---------------------------------------------------------------------------
# Routes — credentials
# ---------------------------------------------------------------------------


@router.get(
    "/credentials",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["ai-models"],
)
async def credentials_list() -> dict[str, Any]:
    """List services that have a credential (without revealing values).

    Master prompt §57 — secrets are NEVER returned. We only reveal which
    services have a credential set so the UI can render a green badge.
    """
    services_with_creds: list[dict[str, Any]] = []
    for service in list_known_services():
        has = get_credential(service) is not None
        services_with_creds.append(
            {
                "service": service,
                "has_credential": has,
                # Mask preview — never the raw value.
                "preview": mask(get_credential(service)) if has else None,
            }
        )
    return {
        "credentials": services_with_creds,
        "count": len(services_with_creds),
        "mock_mode": bool(settings.mock_mode),
    }


@router.post(
    "/credentials",
    dependencies=[Depends(_verify_ipc_token)],
    status_code=status.HTTP_201_CREATED,
    tags=["ai-models"],
)
async def credentials_add(req: CredentialWrite) -> dict[str, Any]:
    """Store a credential in the OS keyring.

    Master prompt §28 — secrets never touch disk in plaintext. The OS
    keyring (or environment variable fallback when keyring is unavailable)
    is the only storage layer.
    """
    try:
        set_credential(req.service, req.value)
    except RuntimeError as exc:
        # Keyring not installed — fall back to env var so the test suite
        # can exercise this route without a real OS keyring.
        env_key = req.service.upper().replace("-", "_").replace(".", "_")
        os.environ[env_key] = req.value
    return {
        "service": req.service,
        "stored": True,
        "mock_mode": bool(settings.mock_mode),
    }


@router.delete(
    "/credentials/{service}",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["ai-models"],
)
async def credentials_remove(service: str) -> dict[str, Any]:
    """Remove a credential from the OS keyring (or env var fallback)."""
    env_key = service.upper().replace("-", "_").replace(".", "_")
    # Try keyring first.
    try:
        import keyring  # type: ignore

        try:
            keyring.delete_password("z-agent", service)
        except Exception:
            pass
    except ImportError:
        pass
    # Always also clear the env var fallback.
    os.environ.pop(env_key, None)
    return {
        "service": service,
        "removed": True,
        "mock_mode": bool(settings.mock_mode),
    }
