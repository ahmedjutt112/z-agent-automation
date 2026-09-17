"""Workflow CRUD + run + templates FastAPI router — master prompt sections
20 (node types), 21 (workflow JSON), 34 (workflow editor UI), 52 (templates).

Endpoints (mounted under ``/workflow`` in main.py):

- ``GET /workflow/templates`` — lists built-in workflow templates.
- ``GET /workflow/{workflow_id}`` — returns the full Workflow object.
- ``PUT /workflow/{workflow_id}`` — updates an existing workflow.
- ``DELETE /workflow/{workflow_id}`` — deletes a workflow.
- ``POST /workflow/{workflow_id}/duplicate`` — creates a copy with a new ID.
- ``GET /workflow/{workflow_id}/versions`` — lists all versions of a workflow.
- ``POST /workflow/{workflow_id}/run`` — executes a saved workflow via
  :class:`WorkflowExecutor.execute_workflow`.

The existing ``POST /workflow`` (save) and ``GET /workflow`` (list) endpoints
defined directly on the ``app`` instance in ``main.py`` are left intact for
backward compatibility with the existing test suite.

Saved workflows live at ``settings.workflows_dir / f"{id}.json"``. Before
every successful ``PUT``, the previous version is copied to
``settings.workflows_dir / "versions" / {id} / v{n}.json`` so the version
history is preserved.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger
from pydantic import BaseModel, Field

from ..config import settings
from ..engine.workflow_executor import WorkflowExecutor
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
async def get_workflow(workflow_id: str) -> Workflow:
    """Return the full Workflow object (master prompt §21)."""
    return _load_workflow_or_404(workflow_id)


@router.put(
    "/{workflow_id}",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["workflow"],
)
async def update_workflow(
    workflow_id: str,
    update: WorkflowUpdate,
) -> dict:
    """Update an existing workflow.

    The previous version is archived under ``versions/{id}/v{n}.json`` and
    the top-level ``updated_at`` and (when nodes change) ``version`` are
    bumped.
    """
    wf = _load_workflow_or_404(workflow_id)

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

    wf.updated_at = datetime.now(timezone.utc)
    _write_workflow(wf)

    return {
        "id": wf.id,
        "updated": True,
        "version": wf.version,
        "updated_at": wf.updated_at.isoformat(),
    }


@router.delete(
    "/{workflow_id}",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["workflow"],
)
async def delete_workflow(workflow_id: str) -> dict:
    """Delete a workflow file. Returns 404 if it does not exist."""
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
async def duplicate_workflow(workflow_id: str) -> DuplicateResponse:
    """Create a copy of ``workflow_id`` under a fresh UUID."""
    src = _load_workflow_or_404(workflow_id)
    new_id = f"{workflow_id}-{uuid4().hex[:8]}"
    clone = src.model_copy(deep=True)
    clone.id = new_id
    clone.name = f"{src.name} (Copy)"
    clone.version = 1
    clone.created_at = datetime.now(timezone.utc)
    clone.updated_at = clone.created_at
    _write_workflow(clone)
    return DuplicateResponse(id=new_id, source_id=workflow_id)


@router.get(
    "/{workflow_id}/versions",
    dependencies=[Depends(_verify_ipc_token)],
    response_model=list[VersionEntry],
    tags=["workflow"],
)
async def list_workflow_versions(workflow_id: str) -> list[VersionEntry]:
    """List all archived versions of a workflow.

    Returns 200 with an empty list if the workflow exists but has no
    archived versions yet. Returns 404 if the workflow itself does not
    exist.
    """
    # Confirm the workflow exists at all.
    _load_workflow_or_404(workflow_id)

    vdir = settings.workflows_dir / "versions" / workflow_id
    if not vdir.exists():
        return []
    out: list[VersionEntry] = []
    for p in sorted(vdir.glob("v*.json")):
        stat = p.stat()
        # Parse the version number from "v{n}.json".
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
async def run_workflow(workflow_id: str) -> RunResponse:
    """Execute a saved workflow.

    In mock mode (``settings.mock_mode=True``) we still invoke the executor
    so the node graph is walked end-to-end; the registered tools themselves
    short-circuit and return mock results without performing real I/O.
    """
    wf = _load_workflow_or_404(workflow_id)
    executor = WorkflowExecutor()
    run_id = await executor.execute_workflow(wf)
    return RunResponse(
        run_id=run_id,
        workflow_id=workflow_id,
        status="running",
        mock_mode=settings.mock_mode,
    )
