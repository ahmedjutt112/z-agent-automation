"""Marketplace HTTP routes — master prompt §52 (template marketplace).

Endpoints (mounted under ``/marketplace`` in main.py):

- ``GET /marketplace/templates`` — query: ``category``, ``tag``, ``limit``.
- ``GET /marketplace/templates/{template_id}`` — get template details.
- ``GET /marketplace/search?q=...`` — search templates by name/desc/tag.
- ``POST /marketplace/install/{template_id}`` — body: ``{profile_id?}``.
- ``DELETE /marketplace/install/{template_id}`` — body: ``{profile_id?}``.
- ``POST /marketplace/rate/{template_id}`` — body: ``{rating: 1-5}``.
- ``POST /marketplace/submit`` — body: ``{workflow, author, category, tags}``.
- ``GET /marketplace/categories`` — list every category with template counts.
- ``GET /marketplace/featured`` — return 6 featured templates.

CRITICAL — master prompt §51 + §52:

1. ``POST /marketplace/install/{template_id}`` ALWAYS persists the installed
   workflow with ``enabled=False``. The user must manually enable it from
   the workflow editor before any node can run.
2. The install response includes ``permissions_required`` and ``risk_level``
   so the UI can render a permission-review modal BEFORE the user enables
   the workflow.
3. All endpoints require the IPC bearer token (master prompt §5).
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from loguru import logger
from pydantic import BaseModel, Field

from ..marketplace.manager import (
    MarketplaceCategory,
    MarketplaceTemplate,
    marketplace_manager,
)
from ..models import Workflow


router = APIRouter()


# ---------------------------------------------------------------------------
# Auth dependency — re-export verify_ipc_token from main lazily to avoid the
# circular import.
# ---------------------------------------------------------------------------


async def _verify_ipc_token(authorization: str | None = None) -> None:
    """Resolve ``verify_ipc_token`` from main lazily."""
    from ..main import verify_ipc_token

    await verify_ipc_token(authorization)


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class InstallRequest(BaseModel):
    """Body for ``POST /marketplace/install/{template_id}``."""

    profile_id: Optional[str] = None


class UninstallRequest(BaseModel):
    """Body for ``DELETE /marketplace/install/{template_id}``."""

    profile_id: Optional[str] = None


class RateRequest(BaseModel):
    """Body for ``POST /marketplace/rate/{template_id}``."""

    rating: int = Field(..., ge=1, le=5, description="Star rating 1-5")


class SubmitRequest(BaseModel):
    """Body for ``POST /marketplace/submit``.

    ``workflow`` is the full :class:`Workflow` payload (validated against
    the pydantic schema). ``category`` must be one of the
    :class:`MarketplaceCategory` values.
    """

    workflow: Workflow
    author: str
    category: str
    tags: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Listing / search
# ---------------------------------------------------------------------------


@router.get(
    "/templates",
    dependencies=[Depends(_verify_ipc_token)],
    response_model=list[MarketplaceTemplate],
    tags=["marketplace"],
)
async def list_templates(
    category: Optional[str] = Query(None, description="Filter by category slug"),
    tag: Optional[str] = Query(None, description="Filter by tag"),
    limit: int = Query(50, ge=1, le=200, description="Max results"),
) -> list[MarketplaceTemplate]:
    """List marketplace templates, optionally filtered by category/tag.

    Master prompt §52 — the response includes ``permissions_required`` and
    ``risk_level`` on every template so the UI can render a permission
    review modal before the user clicks Install.
    """
    try:
        return marketplace_manager.list_templates(category=category, tag=tag, limit=limit)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.get(
    "/templates/{template_id}",
    dependencies=[Depends(_verify_ipc_token)],
    response_model=MarketplaceTemplate,
    tags=["marketplace"],
)
async def get_template(template_id: str) -> MarketplaceTemplate:
    """Return the full template (including the embedded Workflow)."""
    try:
        return marketplace_manager.get_template(template_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))


@router.get(
    "/search",
    dependencies=[Depends(_verify_ipc_token)],
    response_model=list[MarketplaceTemplate],
    tags=["marketplace"],
)
async def search_templates(
    q: str = Query(..., description="Search query (matches name, description, or tag)"),
) -> list[MarketplaceTemplate]:
    """Search the marketplace by free-text query (case-insensitive)."""
    return marketplace_manager.search_templates(q)


@router.get(
    "/categories",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["marketplace"],
)
async def list_categories() -> dict[str, Any]:
    """Return every marketplace category with the count of templates in it."""
    return {"categories": marketplace_manager.list_categories()}


@router.get(
    "/featured",
    dependencies=[Depends(_verify_ipc_token)],
    response_model=list[MarketplaceTemplate],
    tags=["marketplace"],
)
async def list_featured() -> list[MarketplaceTemplate]:
    """Return the featured templates (max 6, sorted by downloads)."""
    return marketplace_manager.list_featured(limit=6)


# ---------------------------------------------------------------------------
# Install / uninstall — master prompt §51 + §52
# ---------------------------------------------------------------------------


@router.post(
    "/install/{template_id}",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["marketplace"],
)
async def install_template(
    template_id: str,
    body: Optional[InstallRequest] = None,
    profile_id: Optional[str] = Query(None, description="Profile scope for the installed workflow"),
) -> dict[str, Any]:
    """Install ``template_id`` as a user-owned workflow.

    Master prompt §51 + §52 — the response includes the installed workflow
    (with ``enabled=False``), the list of ``permissions_required``, the
    ``risk_level``, and any warnings from the permission engine. The
    workflow is saved to ``settings.workflows_dir`` so it shows up in the
    workflow editor; the user MUST manually enable it before any node
    can execute.
    """
    # Body is optional — fall back to the query param if it's missing.
    pid = (body.profile_id if body is not None else None) or profile_id
    try:
        result = marketplace_manager.install_template(template_id, profile_id=pid)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    return result


@router.delete(
    "/install/{template_id}",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["marketplace"],
)
async def uninstall_template(
    template_id: str,
    body: Optional[UninstallRequest] = None,
    profile_id: Optional[str] = Query(None, description="Profile scope to uninstall"),
) -> dict[str, Any]:
    """Remove the installed workflow for ``template_id`` from disk.

    Returns ``{uninstalled: true, template_id}`` on success, or
    ``{uninstalled: false}`` if no install was recorded (treat as 404).
    """
    pid = (body.profile_id if body is not None else None) or profile_id
    removed = marketplace_manager.uninstall_template(template_id, profile_id=pid)
    if not removed:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"no installed workflow found for template '{template_id}' "
            f"(profile={pid or '_global'})",
        )
    return {"uninstalled": True, "template_id": template_id}


# ---------------------------------------------------------------------------
# Rating / submission
# ---------------------------------------------------------------------------


@router.post(
    "/rate/{template_id}",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["marketplace"],
)
async def rate_template(
    template_id: str,
    body: RateRequest,
) -> dict[str, Any]:
    """Add a 1-5 star rating to ``template_id``.

    Returns the updated ``rating`` (average) and ``rating_count``.
    """
    try:
        return marketplace_manager.rate_template(template_id, body.rating)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.post(
    "/submit",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["marketplace"],
)
async def submit_template(body: SubmitRequest) -> dict[str, Any]:
    """Publish a user-submitted template to the marketplace.

    Master prompt §52 — the submitted workflow is permission-scanned
    BEFORE the listing is published so shoppers can review the
    ``permissions_required`` and ``risk_level`` fields. The workflow is
    not enabled or executed; it is just published as a marketplace listing.
    """
    try:
        new_id = marketplace_manager.submit_template(
            workflow=body.workflow,
            author=body.author,
            category=body.category,
            tags=body.tags,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return {"template_id": new_id, "submitted": True}


__all__ = ["router"]
