"""Workflow CRUD + run + templates FastAPI router — master prompt sections
20 (node types), 21 (workflow JSON), 34 (workflow editor UI), 51 (import /
export), 52 (templates).

Endpoints (mounted under ``/workflow`` in main.py):

- ``GET /workflow/templates`` — lists built-in workflow templates.
- ``GET /workflow/{workflow_id}`` — returns the full Workflow object.
- ``PUT /workflow/{workflow_id}`` — updates an existing workflow.
- ``DELETE /workflow/{workflow_id}`` — deletes a workflow.
- ``POST /workflow/{workflow_id}/duplicate`` — creates a copy with a new ID.
- ``GET /workflow/{workflow_id}/versions`` — lists all versions of a workflow.
- ``POST /workflow/{workflow_id}/run`` — executes a saved workflow via
  :class:`WorkflowExecutor.execute_workflow`.
- ``POST /workflow/import`` — validates + imports a workflow JSON
  (master prompt §51). Persisted with ``enabled=False``.
- ``GET /workflow/{workflow_id}/export`` — downloads the workflow JSON file.
- ``POST /workflow/validate`` — validates a workflow JSON without saving.
- ``GET /workflow/{workflow_id}/permissions`` — returns the permissions
  required by this workflow (master prompt §51).

The existing ``POST /workflow`` (save) and ``GET /workflow`` (list) endpoints
defined directly on the ``app`` instance in ``main.py`` are left intact for
backward compatibility with the existing test suite.

Saved workflows live at ``settings.workflows_dir / f"{id}.json"``. Before
every successful ``PUT``, the previous version is copied to
``settings.workflows_dir / "versions" / {id} / v{n}.json`` so the version
history is preserved.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from loguru import logger
from pydantic import BaseModel, Field, ValidationError

from ..config import settings
from ..engine.workflow_executor import WorkflowExecutor
from ..marketplace.manager import _PERMISSION_MAP, _risk_for_permissions, _scan_node_types
from ..models import (
    RiskLevel,
    TriggerType,
    Workflow,
    WorkflowNode,
    WorkflowTrigger,
)


router = APIRouter()


# ---------------------------------------------------------------------------
# Auth dependency — re-exported lazily to avoid the circular import with main.
# ---------------------------------------------------------------------------


async def _verify_ipc_token(authorization: str | None = None) -> None:
    """Resolve ``verify_ipc_token`` from main lazily."""
    from ..main import verify_ipc_token

    await verify_ipc_token(authorization)


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _wf_path(workflow_id: str) -> Path:
    return settings.workflows_dir / f"{workflow_id}.json"


def _versions_dir(workflow_id: str) -> Path:
    p = settings.workflows_dir / "versions" / workflow_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def _load_workflow_or_404(workflow_id: str) -> Workflow:
    path = _wf_path(workflow_id)
    if not path.exists():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"workflow '{workflow_id}' not found",
        )
    try:
        return Workflow.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("failed to parse workflow {}: {}", workflow_id, exc)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"workflow '{workflow_id}' is corrupted",
        )


def _write_workflow(workflow: Workflow) -> None:
    path = _wf_path(workflow.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(workflow.model_dump_json(indent=2), encoding="utf-8")


def _archive_current_version(workflow_id: str) -> None:
    """Copy the current ``{id}.json`` into the ``versions/{id}/v{n}.json``
    slot before it gets overwritten.

    Versions are numbered starting at 1. If the current file is the first
    save (no versions yet) we still create the directory — the first PUT
    will archive the original as v1.
    """
    current = _wf_path(workflow_id)
    if not current.exists():
        return
    vdir = _versions_dir(workflow_id)
    existing = sorted(vdir.glob("v*.json"))
    next_n = len(existing) + 1
    target = vdir / f"v{next_n}.json"
    target.write_bytes(current.read_bytes())


# ---------------------------------------------------------------------------
# Profile access helper — master prompt §49 (multi-profile support)
# ---------------------------------------------------------------------------


def _check_profile_access(workflow: Workflow, profile_id: Optional[str]) -> None:
    """Raise HTTP 403 if ``workflow.profile_id`` doesn't match the request's
    ``profile_id``.

    Backwards-compatible semantics:

    * If ``profile_id`` is ``None`` (the caller didn't ask for a specific
      profile), access is always granted — the request is unscoped.
    * If the workflow has no ``profile_id`` (legacy data, no profile bound),
      access is granted to any profile.
    * Otherwise both values must be equal.
    """
    if profile_id is None:
        return
    if workflow.profile_id is None:
        return
    if workflow.profile_id != profile_id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            (
                f"workflow '{workflow.id}' belongs to profile "
                f"'{workflow.profile_id}', not '{profile_id}'"
            ),
        )


# ---------------------------------------------------------------------------
# Built-in templates — master prompt §52 (template marketplace)
# ---------------------------------------------------------------------------

_TEMPLATES: list[Workflow] = [
    Workflow(
        id="daily_report",
        name="Daily Report Generator",
        description=(
            "Capture a screenshot of the dashboard, OCR the visible KPIs, "
            "and email the result. Triggered every weekday at 09:00."
        ),
        trigger=WorkflowTrigger(type=TriggerType.SCHEDULE, cron="0 9 * * 1-5"),
        nodes=[
            WorkflowNode(
                id="start",
                type="start",
                args={},
            ),
            WorkflowNode(
                id="capture",
                type="screen.capture",
                args={"filename": "daily_dashboard.png"},
                timeout_ms=15_000,
            ),
            WorkflowNode(
                id="ocr",
                type="screen.ocr",
                args={"region": "full"},
                next="email",
            ),
            WorkflowNode(
                id="email",
                type="notify.email",
                args={
                    "to": "team@example.com",
                    "subject": "Daily KPI Report",
                    "body": "{{ocr.text}}",
                },
                next="end",
            ),
            WorkflowNode(id="end", type="end", args={}),
        ],
        variables={"report_date": "{{now}}"},
    ),
    Workflow(
        id="organize_downloads",
        name="Organize Downloads Folder",
        description=(
            "List every file in the Downloads folder, then move images to "
            "Pictures/, PDFs to Documents/, and archives to Archives/. Runs "
            "on demand or after a download completes."
        ),
        trigger=WorkflowTrigger(type=TriggerType.FILE, file_pattern="*.pdf"),
        nodes=[
            WorkflowNode(id="start", type="start", args={}),
            WorkflowNode(
                id="list_files",
                type="file.list",
                args={"path": "~/Downloads"},
                next="filter_pdfs",
            ),
            WorkflowNode(
                id="filter_pdfs",
                type="for_each",
                args={
                    "loop": {"items_var": "files", "filter": "*.pdf"},
                    "action": "file.move",
                    "args": {
                        "src": "{{item.path}}",
                        "dst": "~/Documents/PDFs/{{item.name}}",
                    },
                },
                next="end",
            ),
            WorkflowNode(id="end", type="end", args={}),
        ],
    ),
    Workflow(
        id="browser_login",
        name="Browser Login Helper",
        description=(
            "Open the configured browser, navigate to the login page, fill "
            "in credentials from the secret store, and submit the form. "
            "Designed to be triggered manually from the UI."
        ),
        trigger=WorkflowTrigger(type=TriggerType.MANUAL),
        nodes=[
            WorkflowNode(id="start", type="start", args={}),
            WorkflowNode(
                id="open_browser",
                type="browser.open",
                args={"browser": "chrome"},
                next="navigate",
            ),
            WorkflowNode(
                id="navigate",
                type="browser.navigate",
                args={"url": "https://example.com/login"},
                next="type_email",
            ),
            WorkflowNode(
                id="type_email",
                type="browser.type",
                args={"selector": "#email", "text": "{{secrets.email}}"},
                next="type_password",
            ),
            WorkflowNode(
                id="type_password",
                type="browser.type",
                args={"selector": "#password", "text": "{{secrets.password}}"},
                next="submit",
            ),
            WorkflowNode(
                id="submit",
                type="browser.click",
                args={"selector": "button[type=submit]"},
                next="end",
            ),
            WorkflowNode(id="end", type="end", args={}),
        ],
        variables={"secrets.email": "user@example.com"},
    ),
]


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class WorkflowUpdate(BaseModel):
    """Body for ``PUT /workflow/{id}``.

    All fields are optional — only the supplied fields are overwritten.
    ``version`` is bumped automatically by the server when content changes.
    """

    name: Optional[str] = None
    description: Optional[str] = None
    trigger: Optional[WorkflowTrigger] = None
    nodes: Optional[list[WorkflowNode]] = None
    variables: Optional[dict[str, str]] = None
    enabled: Optional[bool] = None


class DuplicateResponse(BaseModel):
    id: str
    source_id: str
    duplicated: bool = True


class RunResponse(BaseModel):
    run_id: str
    workflow_id: str
    status: str
    mock_mode: bool


class TemplateSummary(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    trigger: WorkflowTrigger
    node_count: int
    template: Workflow


class VersionEntry(BaseModel):
    version: int
    filename: str
    saved_at: str
    size_bytes: int


# ---------------------------------------------------------------------------
# IMPORTANT: /templates is declared BEFORE /{workflow_id} so FastAPI's
# route-matcher does not capture "templates" as a workflow_id.
# ---------------------------------------------------------------------------


@router.get(
    "/templates",
    dependencies=[Depends(_verify_ipc_token)],
    response_model=list[TemplateSummary],
    tags=["workflow"],
)
async def list_workflow_templates() -> list[TemplateSummary]:
    """List built-in workflow templates (master prompt §52)."""
    return [
        TemplateSummary(
            id=t.id,
            name=t.name,
            description=t.description,
            trigger=t.trigger,
            node_count=len(t.nodes),
            template=t,
        )
        for t in _TEMPLATES
    ]


# ---------------------------------------------------------------------------
# Single-workflow CRUD
# ---------------------------------------------------------------------------


@router.get(
    "/{workflow_id}",
    dependencies=[Depends(_verify_ipc_token)],
    response_model=Workflow,
    tags=["workflow"],
)
async def get_workflow(
    workflow_id: str,
    profile_id: Optional[str] = Query(None, description="Filter by profile id"),
) -> Workflow:
    """Return the full Workflow object (master prompt §21).

    If the workflow has a ``profile_id`` set and the caller supplies a
    different ``profile_id`` query param, the request is rejected with
    HTTP 403 — see :func:`_check_profile_access`.
    """
    wf = _load_workflow_or_404(workflow_id)
    _check_profile_access(wf, profile_id)
    return wf


@router.put(
    "/{workflow_id}",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["workflow"],
)
async def update_workflow(
    workflow_id: str,
    update: WorkflowUpdate,
    profile_id: Optional[str] = Query(None, description="Profile scope for access check"),
) -> dict:
    """Update an existing workflow.

    The previous version is archived under ``versions/{id}/v{n}.json`` and
    the top-level ``updated_at`` and (when nodes change) ``version`` are
    bumped. The workflow's ``profile_id`` is preserved across updates —
    callers CANNOT change it via PUT (use ``POST /workflow`` to create a
    new profile-scoped workflow).
    """
    wf = _load_workflow_or_404(workflow_id)
    _check_profile_access(wf, profile_id)

    # Archive the current file before we overwrite it.
    _archive_current_version(workflow_id)

    if update.name is not None:
        wf.name = update.name
    if update.description is not None:
        wf.description = update.description
    if update.trigger is not None:
        wf.trigger = update.trigger
    if update.nodes is not None:
        wf.nodes = update.nodes
        wf.version += 1
    if update.variables is not None:
        wf.variables = update.variables
    if update.enabled is not None:
        wf.enabled = update.enabled

    # profile_id is intentionally NOT taken from `update` — preserve the
    # original value so a profile-scoped workflow cannot be silently moved
    # to another profile (or unscoped) via PUT.

    wf.updated_at = datetime.now(timezone.utc)
    _write_workflow(wf)

    return {
        "id": wf.id,
        "updated": True,
        "version": wf.version,
        "profile_id": wf.profile_id,
        "updated_at": wf.updated_at.isoformat(),
    }


@router.delete(
    "/{workflow_id}",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["workflow"],
)
async def delete_workflow(
    workflow_id: str,
    profile_id: Optional[str] = Query(None, description="Profile scope for access check"),
) -> dict:
    """Delete a workflow file. Returns 404 if it does not exist."""
    wf = _load_workflow_or_404(workflow_id)
    _check_profile_access(wf, profile_id)
    path = _wf_path(workflow_id)
    if not path.exists():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"workflow '{workflow_id}' not found",
        )
    path.unlink()
    # Also remove version history for cleanliness.
    vdir = settings.workflows_dir / "versions" / workflow_id
    if vdir.exists():
        for p in vdir.glob("*.json"):
            p.unlink()
        vdir.rmdir()
    return {"id": workflow_id, "deleted": True}


@router.post(
    "/{workflow_id}/duplicate",
    dependencies=[Depends(_verify_ipc_token)],
    response_model=DuplicateResponse,
    tags=["workflow"],
)
async def duplicate_workflow(
    workflow_id: str,
    profile_id: Optional[str] = Query(None, description="Profile scope for access check"),
) -> DuplicateResponse:
    """Create a copy of ``workflow_id`` under a fresh UUID.

    The new workflow inherits the source's ``profile_id`` so it stays in
    the same profile scope.
    """
    src = _load_workflow_or_404(workflow_id)
    _check_profile_access(src, profile_id)
    new_id = f"{workflow_id}-{uuid4().hex[:8]}"
    clone = src.model_copy(deep=True)
    clone.id = new_id
    clone.name = f"{src.name} (Copy)"
    clone.version = 1
    clone.created_at = datetime.now(timezone.utc)
    clone.updated_at = clone.created_at
    # profile_id is preserved via the deep copy.
    _write_workflow(clone)
    return DuplicateResponse(id=new_id, source_id=workflow_id)


@router.get(
    "/{workflow_id}/versions",
    dependencies=[Depends(_verify_ipc_token)],
    response_model=list[VersionEntry],
    tags=["workflow"],
)
async def list_workflow_versions(
    workflow_id: str,
    profile_id: Optional[str] = Query(None, description="Profile scope for access check"),
) -> list[VersionEntry]:
    """List all archived versions of a workflow.

    Returns 200 with an empty list if the workflow exists but has no
    archived versions yet. Returns 404 if the workflow itself does not
    exist. Returns 403 if ``profile_id`` doesn't match.
    """
    wf = _load_workflow_or_404(workflow_id)
    _check_profile_access(wf, profile_id)

    vdir = settings.workflows_dir / "versions" / workflow_id
    if not vdir.exists():
        return []
    out: list[VersionEntry] = []
    for p in sorted(vdir.glob("v*.json")):
        stat = p.stat()
        try:
            n = int(p.stem.removeprefix("v"))
        except ValueError:
            continue
        out.append(
            VersionEntry(
                version=n,
                filename=p.name,
                saved_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                size_bytes=stat.st_size,
            )
        )
    return out


@router.post(
    "/{workflow_id}/run",
    dependencies=[Depends(_verify_ipc_token)],
    response_model=RunResponse,
    tags=["workflow"],
)
async def run_workflow(
    workflow_id: str,
    profile_id: Optional[str] = Query(None, description="Profile scope to associate the run with"),
) -> RunResponse:
    """Execute a saved workflow.

    In mock mode (``settings.mock_mode=True``) we still invoke the executor
    so the node graph is walked end-to-end; the registered tools themselves
    short-circuit and return mock results without performing real I/O.

    When ``profile_id`` is provided, the resulting run is tagged with that
    profile so downstream queries (logs, screenshots, history) can be
    filtered to the same profile.
    """
    wf = _load_workflow_or_404(workflow_id)
    # If the workflow is profile-scoped, the request's profile_id must match
    # (or be omitted, in which case we inherit the workflow's profile_id).
    effective_profile_id = profile_id or wf.profile_id
    if profile_id is not None and wf.profile_id is not None and profile_id != wf.profile_id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            (
                f"workflow '{workflow_id}' belongs to profile "
                f"'{wf.profile_id}', not '{profile_id}'"
            ),
        )

    executor = WorkflowExecutor()
    run_id = await executor.execute_workflow(wf)

    # Record the run's profile_id on the in-memory run dict (best-effort —
    # the executor doesn't natively know about profiles, so we patch it in
    # here for downstream consumers to see).
    try:
        run_state = executor.get_status(run_id) or {}
        run_state["profile_id"] = effective_profile_id
        executor._runs[run_id] = run_state  # type: ignore[assignment]
    except Exception:  # pragma: no cover — defensive
        pass

    return RunResponse(
        run_id=run_id,
        workflow_id=workflow_id,
        status="running",
        mock_mode=settings.mock_mode,
    )


# ---------------------------------------------------------------------------
# Import / Export / Validate / Permissions — master prompt §51
# ---------------------------------------------------------------------------
#
# IMPORTANT: POST /workflow/import and POST /workflow/validate are declared
# BEFORE the existing GET /workflow/{workflow_id} route in declaration
# order? No — they're POSTs and the existing 1-segment route is a GET, so
# there is no conflict. They are appended at the END of the file but their
# method (POST) disambiguates them from the GET /{workflow_id} handler.
#
# GET /workflow/{workflow_id}/export and GET /workflow/{workflow_id}/permissions
# are 2-segment GETs — Starlette matches them by their literal suffix
# (/export, /permissions) before /{workflow_id}/versions, so no conflict
# with the existing /versions route either.
# ---------------------------------------------------------------------------


# Shared scanner — uses the same logic as MarketplaceManager._scan_permissions
# so the marketplace + workflow import paths report identical permissions
# for the same workflow JSON.
def _scan_workflow_permissions(workflow: Workflow) -> list[str]:
    perms: list[str] = []
    for node_type in _scan_node_types(workflow):
        perm = _PERMISSION_MAP.get(node_type)
        if perm and perm not in perms:
            perms.append(perm)
    return perms


class ImportRequest(BaseModel):
    """Body for ``POST /workflow/import`` and ``POST /workflow/validate``.

    ``workflow_json`` is a JSON-encoded Workflow object. We accept the raw
    string rather than a structured Workflow so we can return a clean
    422-style validation error when the payload is malformed.
    """

    workflow_json: str
    profile_id: Optional[str] = None


class ValidateRequest(BaseModel):
    """Body for ``POST /workflow/validate`` (no profile binding)."""

    workflow_json: str


@router.post(
    "/import",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["workflow"],
)
async def import_workflow(body: ImportRequest) -> dict:
    """Import a workflow from a JSON payload — master prompt §51.

    The JSON is validated against the :class:`Workflow` pydantic schema.
    On success the workflow is saved to disk with ``enabled=False``
    (master prompt §51: "Never execute imported workflows automatically").
    The response includes the workflow, the list of required permissions,
    the overall risk_level, and any warnings from the permission scan.

    On malformed JSON or schema violation the endpoint returns HTTP 422
    with a list of errors.
    """
    # 1. Parse the JSON string.
    try:
        parsed = json.loads(body.workflow_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"workflow_json is not valid JSON: {exc.msg} (line {exc.lineno}, col {exc.colno})",
        )

    # 2. Validate against the Workflow pydantic schema.
    try:
        workflow = Workflow.model_validate(parsed)
    except ValidationError as exc:
        errors = []
        for err in exc.errors():
            loc = ".".join(str(p) for p in err.get("loc", []))
            errors.append(f"{loc}: {err.get('msg', '')}")
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"workflow JSON failed schema validation: {errors}",
        )

    # 3. Permission-scan (master prompt §51: "Show permission requirements
    #    before execution").
    perms = _scan_workflow_permissions(workflow)
    risk = _risk_for_permissions(perms)

    # 4. Force enabled=False (master prompt §51: "Never execute imported
    #    workflows automatically").
    workflow.enabled = False
    workflow.profile_id = body.profile_id
    workflow.updated_at = datetime.now(timezone.utc)

    # 5. Persist to disk with the permissions_required + risk_level spliced
    #    into the JSON payload so the workflow editor can surface them.
    wf_data = workflow.model_dump(mode="json")
    wf_data["permissions_required"] = list(perms)
    wf_data["risk_level"] = risk.value
    path = _wf_path(workflow.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(wf_data, indent=2, default=str),
        encoding="utf-8",
    )

    warnings: list[str] = []
    if risk in {RiskLevel.HIGH, RiskLevel.CRITICAL}:
        warnings.append(
            f"This workflow has {risk.value} risk level — review the "
            f"required permissions before enabling."
        )
    if not perms:
        warnings.append(
            "This workflow has no recognisable tool nodes — it may not "
            "perform any actions when enabled."
        )

    logger.info(
        "workflow imported id={} name={} perms={} risk={} enabled=False",
        workflow.id, workflow.name, perms, risk.value,
    )

    return {
        "valid": True,
        "workflow": workflow.model_dump(mode="json"),
        "permissions_required": perms,
        "risk_level": risk.value,
        "warnings": warnings,
        "imported": True,
    }


@router.post(
    "/validate",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["workflow"],
)
async def validate_workflow(body: ValidateRequest) -> dict:
    """Validate a workflow JSON without saving it — master prompt §51.

    Returns ``{valid, errors, permissions_required, risk_level}`` so the
    UI can render a preview modal BEFORE the user decides to import.
    """
    try:
        parsed = json.loads(body.workflow_json)
    except json.JSONDecodeError as exc:
        return {
            "valid": False,
            "errors": [
                f"workflow_json is not valid JSON: {exc.msg} "
                f"(line {exc.lineno}, col {exc.colno})"
            ],
            "permissions_required": [],
            "risk_level": RiskLevel.LOW.value,
        }

    try:
        workflow = Workflow.model_validate(parsed)
    except ValidationError as exc:
        errors = []
        for err in exc.errors():
            loc = ".".join(str(p) for p in err.get("loc", []))
            errors.append(f"{loc}: {err.get('msg', '')}")
        return {
            "valid": False,
            "errors": errors,
            "permissions_required": [],
            "risk_level": RiskLevel.LOW.value,
        }

    perms = _scan_workflow_permissions(workflow)
    risk = _risk_for_permissions(perms)
    return {
        "valid": True,
        "errors": [],
        "permissions_required": perms,
        "risk_level": risk.value,
    }


@router.get(
    "/{workflow_id}/export",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["workflow"],
)
async def export_workflow(
    workflow_id: str,
    profile_id: Optional[str] = Query(None, description="Profile scope for access check"),
) -> Response:
    """Download the workflow JSON as a file attachment — master prompt §51.

    Content-Type: ``application/json``
    Content-Disposition: ``attachment; filename="{workflow_name}.json"``

    The exported payload preserves any extra fields (``permissions_required``,
    ``risk_level``) that were attached to the on-disk JSON by
    :func:`import_workflow` or :meth:`MarketplaceManager.install_template`,
    so an exported file can be re-imported without losing its permission
    annotations. If those fields are absent (legacy workflow file), they
    are computed on the fly so the export is always self-describing.
    """
    wf = _load_workflow_or_404(workflow_id)
    _check_profile_access(wf, profile_id)

    # Read the raw on-disk JSON so we preserve any extra fields the
    # Workflow pydantic model doesn't know about (permissions_required,
    # risk_level). Falls back to model_dump_json if the file is missing
    # for some reason (defensive — _load_workflow_or_404 above would
    # have raised 404 already).
    path = _wf_path(workflow_id)
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            # Ensure permissions_required + risk_level are present
            # (compute on the fly if the file predates this feature).
            if "permissions_required" not in raw:
                perms = _scan_workflow_permissions(wf)
                raw["permissions_required"] = perms
                raw["risk_level"] = _risk_for_permissions(perms).value
            payload = json.dumps(raw, indent=2, default=str)
        except Exception:
            payload = wf.model_dump_json(indent=2)
    else:
        payload = wf.model_dump_json(indent=2)

    # Filename: use the workflow name (sanitised) for a friendlier download.
    safe_name = "".join(
        c if c.isalnum() or c in ("-", "_") else "_" for c in wf.name
    ).strip("_") or workflow_id
    return Response(
        content=payload,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}.json"',
        },
    )


@router.get(
    "/{workflow_id}/permissions",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["workflow"],
)
async def workflow_permissions(
    workflow_id: str,
    profile_id: Optional[str] = Query(None, description="Profile scope for access check"),
) -> dict:
    """Return the permissions required by this workflow — master prompt §51.

    Surfaces ``permissions_required`` (list[str]) and ``risk_level``
    (low|medium|high|critical) so the UI can render a permission-review
    modal before the user enables an imported workflow.
    """
    wf = _load_workflow_or_404(workflow_id)
    _check_profile_access(wf, profile_id)
    perms = _scan_workflow_permissions(wf)
    risk = _risk_for_permissions(perms)
    return {
        "workflow_id": workflow_id,
        "permissions_required": perms,
        "risk_level": risk.value,
        "enabled": wf.enabled,
    }
