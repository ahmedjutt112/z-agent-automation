"""Permissions FastAPI router — master prompt §9 (risk levels), §10 (human
confirmation), §55 (security architecture), §88 (rate limits).

Mounted under ``/permissions`` in main.py. Endpoints:

* ``GET    /permissions``                — list all grants (optional ?profile_id=)
* ``POST   /permissions``                — grant a new permission
* ``DELETE /permissions/{grant_id}``      — revoke a permission
* ``GET    /permissions/risk-levels``     — list the 4 risk levels with examples
* ``GET    /permissions/policy``          — get rate limits + risk overrides
* ``PUT    /permissions/policy``          — update rate limits + risk overrides

All routes require the IPC bearer token.

The grant storage uses the existing
:class:`automation_service.security.permission_engine.PermissionEngine`
singleton, which keeps grants in an in-process dict keyed by
``(profile_id, tool_name, risk_level)``. For a multi-process deployment we'd
back this with the SQLAlchemy ``permissions`` table; for this iteration the
in-memory store matches the rest of the permission engine's contract.

Risk policy + rate limits — master prompt §88:
    The policy endpoint exposes ``max_actions_per_minute``,
    ``max_ai_calls_per_task``, ``max_loops``, ``max_file_operations``,
    ``max_browser_tabs`` (read from settings) plus a per-tool risk override
    map. PUT persists overrides to a JSON file at
    ``settings.config_dir / risk_overrides.json`` so they survive restarts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from ..config import settings
from ..models import RiskLevel, PermissionLevel
from ..security.permission_engine import permission_engine


router = APIRouter()


# ---------------------------------------------------------------------------
# Auth dependency — lazy import avoids circular dep with main.
# ---------------------------------------------------------------------------


async def _verify_ipc_token(authorization: str | None = None) -> None:
    from ..main import verify_ipc_token

    await verify_ipc_token(authorization)


# ---------------------------------------------------------------------------
# Risk-level + decision enums
# ---------------------------------------------------------------------------


_RISK_LEVEL_INFO: dict[str, dict[str, Any]] = {
    RiskLevel.LOW.value: {
        "label": "Low",
        "color": "green",
        "description": "Read-only / side-effect-free actions.",
        "examples": [
            "file.read",
            "file.list",
            "screen.capture",
            "screen.ocr",
            "browser.extract",
        ],
    },
    RiskLevel.MEDIUM.value: {
        "label": "Medium",
        "color": "yellow",
        "description": "Reversible state changes — require user awareness.",
        "examples": [
            "file.write",
            "file.move",
            "file.rename",
            "browser.click",
            "browser.type",
            "mouse.click",
            "keyboard.type",
        ],
    },
    RiskLevel.HIGH.value: {
        "label": "High",
        "color": "orange",
        "description": "Significant side effects — require explicit user approval.",
        "examples": [
            "app.launch",
            "app.kill",
            "app.install",
            "browser.navigate (to file:// URLs)",
            "notifications.send (with action buttons)",
        ],
    },
    RiskLevel.CRITICAL.value: {
        "label": "Critical",
        "color": "red",
        "description": (
            "Destructive or irreversible actions — require explicit user "
            "approval even in autonomous mode."
        ),
        "examples": [
            "file.delete",
            "file.copy (overwriting system files)",
            "mouse.click (on payment confirmation buttons)",
            "keyboard.type (entering passwords / 2FA codes)",
            "app.uninstall",
        ],
    },
}


# ---------------------------------------------------------------------------
# Risk overrides storage (JSON file under config dir)
# ---------------------------------------------------------------------------


def _overrides_path() -> Path:
    """Path to the persisted risk-override JSON file.

    Falls back to ``settings.automation_root / risk_overrides.json`` when
    the config dir doesn't exist (which is the case in mock mode).
    """
    p = settings.project_root / "config" / "risk_overrides.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_overrides() -> dict[str, str]:
    p = _overrides_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_overrides(overrides: dict[str, str]) -> None:
    p = _overrides_path()
    p.write_text(json.dumps(overrides, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class GrantRequest(BaseModel):
    """Body of ``POST /permissions``."""

    tool_name: str
    risk_level: RiskLevel
    decision: PermissionLevel = PermissionLevel.ALLOW_FOR_WORKFLOW
    profile_id: Optional[str] = None


class PolicyBody(BaseModel):
    """Body of ``GET /permissions/policy`` and ``PUT /permissions/policy``."""

    max_actions_per_minute: int = Field(default=120, ge=1, le=10_000)
    max_ai_calls_per_task: int = Field(default=25, ge=1, le=10_000)
    max_loops: int = Field(default=1000, ge=1, le=1_000_000)
    max_file_operations: int = Field(default=500, ge=1, le=10_000)
    max_browser_tabs: int = Field(default=8, ge=1, le=64)
    risk_overrides: dict[str, str] = Field(
        default_factory=dict,
        description="Per-tool risk level overrides, e.g. {'file.delete': 'critical'}.",
    )


# ---------------------------------------------------------------------------
# Routes — risk levels (declared BEFORE /{grant_id} so FastAPI doesn't
# capture "risk-levels" or "policy" as the grant_id path param).
# ---------------------------------------------------------------------------


@router.get(
    "/risk-levels",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["permissions"],
)
async def permissions_risk_levels() -> dict[str, Any]:
    """Return the 4 risk levels with examples (master prompt §9)."""
    return {
        "levels": [
            {"value": value, **info}
            for value, info in _RISK_LEVEL_INFO.items()
        ],
        "count": len(_RISK_LEVEL_INFO),
    }


@router.get(
    "/policy",
    response_model=PolicyBody,
    dependencies=[Depends(_verify_ipc_token)],
    tags=["permissions"],
)
async def permissions_get_policy() -> dict[str, Any]:
    """Return current rate limits + risk overrides."""
    return {
        "max_actions_per_minute": settings.max_actions_per_minute,
        "max_ai_calls_per_task": settings.max_ai_calls_per_task,
        "max_loops": settings.max_loops,
        "max_file_operations": settings.max_file_operations,
        "max_browser_tabs": settings.max_browser_tabs,
        "risk_overrides": _load_overrides(),
    }


@router.put(
    "/policy",
    response_model=PolicyBody,
    dependencies=[Depends(_verify_ipc_token)],
    tags=["permissions"],
)
async def permissions_update_policy(req: PolicyBody) -> dict[str, Any]:
    """Update rate limits + risk overrides.

    Rate limits are persisted back to the in-memory ``settings`` object so
    the running service picks them up immediately; risk overrides are
    persisted to ``config/risk_overrides.json`` so they survive restarts.
    """
    settings.max_actions_per_minute = req.max_actions_per_minute
    settings.max_ai_calls_per_task = req.max_ai_calls_per_task
    settings.max_loops = req.max_loops
    settings.max_file_operations = req.max_file_operations
    settings.max_browser_tabs = req.max_browser_tabs
    _save_overrides(req.risk_overrides)
    return {
        "max_actions_per_minute": settings.max_actions_per_minute,
        "max_ai_calls_per_task": settings.max_ai_calls_per_task,
        "max_loops": settings.max_loops,
        "max_file_operations": settings.max_file_operations,
        "max_browser_tabs": settings.max_browser_tabs,
        "risk_overrides": _load_overrides(),
    }


# ---------------------------------------------------------------------------
# Routes — grants
# ---------------------------------------------------------------------------


@router.get(
    "",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["permissions"],
)
async def permissions_list(
    profile_id: Optional[str] = Query(None),
) -> dict[str, Any]:
    """List all grants (optionally filtered by profile_id)."""
    grants = permission_engine.list_grants(profile_id=profile_id)
    # Decorate each grant with a synthetic grant_id so the UI can pass it
    # back on DELETE. The engine stores grants keyed by
    # (profile_key, tool_name, risk_level) — we synthesise the id from that.
    decorated: list[dict[str, Any]] = []
    for g in grants:
        profile = g.get("profile_id") or "_global"
        grant_id = f"{profile}:{g['tool']}:{g['risk']}"
        decorated.append({"grant_id": grant_id, **g})
    return {"grants": decorated, "count": len(decorated)}


@router.post(
    "",
    dependencies=[Depends(_verify_ipc_token)],
    status_code=status.HTTP_201_CREATED,
    tags=["permissions"],
)
async def permissions_grant(req: GrantRequest) -> dict[str, Any]:
    """Grant a new permission."""
    permission_engine.grant(
        tool_name=req.tool_name,
        risk=req.risk_level,
        decision=req.decision,
        profile_id=req.profile_id,
    )
    profile = req.profile_id or "_global"
    grant_id = f"{profile}:{req.tool_name}:{req.risk_level.value}"
    return {
        "grant_id": grant_id,
        "tool_name": req.tool_name,
        "risk_level": req.risk_level.value,
        "decision": req.decision.value,
        "profile_id": req.profile_id,
        "granted": True,
    }


@router.delete(
    "/{grant_id}",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["permissions"],
)
async def permissions_revoke(grant_id: str) -> dict[str, Any]:
    """Revoke a permission by grant_id.

    ``grant_id`` has the format ``{profile_key}:{tool_name}:{risk_level}``.
    """
    parts = grant_id.split(":")
    if len(parts) != 3:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"invalid grant_id '{grant_id}' — expected 'profile:tool:risk'",
        )
    profile_str, tool_name, risk_str = parts
    profile_id = None if profile_str == "_global" else profile_str
    try:
        risk = RiskLevel(risk_str)
    except ValueError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"invalid risk_level '{risk_str}' — expected one of {[r.value for r in RiskLevel]}",
        )
    permission_engine.revoke(
        tool_name=tool_name,
        risk=risk,
        profile_id=profile_id,
    )
    return {
        "grant_id": grant_id,
        "revoked": True,
    }
