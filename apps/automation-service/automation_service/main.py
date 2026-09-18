"""FastAPI application for the Automation Service.

Binds to localhost ONLY (per master prompt §5). All endpoints validate input
with Pydantic. WebSocket endpoint streams live events to the Electron renderer.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .config import settings, ensure_runtime_dirs
from .models import (
    ActionRequest,
    ActionResult,
    Plan,
    ApprovalRequest,
    ApprovalResponse,
    Workflow,
)
from .engine.event_bus import event_bus
from .engine.workflow_executor import WorkflowExecutor
from .engine.tool_registry import tool_registry
from .security.permission_engine import permission_engine
from .security.kill_switch import kill_switch
from .api.oauth_routes import router as oauth_router
from .api.integration_routes import router as integration_router
from .api.workflow_routes import router as workflow_router
from .api.marketplace_routes import router as marketplace_router
from .api.system_routes import router as system_router
from .api.logs_routes import router as logs_router
from .api.screenshots_routes import router as screenshots_router
from .api.assistant_routes import router as assistant_router
from .api.recorder_routes import router as recorder_router
from .api.browser_routes import router as browser_router
from .api.files_routes import router as files_router
from .api.history_routes import router as history_router
from .api.ai_models_routes import router as ai_models_router
from .api.permissions_routes import router as permissions_router
from .api.agent_routes import router as agent_router
from .api.team_routes import router as team_router
from .api.analytics_routes import router as analytics_router
from .scheduler.manager import scheduler_manager
from .scheduler.api import router as schedules_router
from .voice.api import router as voice_router
from .memory.api import router as memory_router
from .profiles.api import router as profiles_router
from .plugins.manager import plugin_manager


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    ensure_runtime_dirs()
    tool_registry.discover()
    # Auto-load all installed plugins (master prompt §53)
    try:
        plugin_manager.discover()
        for spec in plugin_manager.list_available():
            try:
                plugin_manager.load(spec.name)
            except Exception as exc:  # noqa: BLE001
                # Plugin load failure must NOT crash the service
                from loguru import logger
                logger.warning("Failed to load plugin '{}': {}", spec.name, exc)
    except Exception as exc:  # noqa: BLE001
        from loguru import logger
        logger.warning("Plugin discovery failed: {}", exc)
    event_bus.publish("SERVICE_STARTED", {"version": settings.service_version})
    await scheduler_manager.start()
    try:
        yield
    finally:
        await scheduler_manager.shutdown()
        event_bus.publish("SERVICE_STOPPED", {})
        await asyncio.sleep(0.1)  # let pending events flush


app = FastAPI(
    title="AI PC/Laptop Automation Service",
    version=settings.service_version,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None,
    openapi_tags=[
        {"name": "health", "description": "Service health & status."},
        {"name": "tools", "description": "List available automation tools."},
        {"name": "planning", "description": "AI planning & plan execution."},
        {"name": "workflow", "description": "Workflow CRUD."},
        {"name": "marketplace", "description": "Template marketplace (section 52) — browse, install, rate, and submit workflow templates. Imported workflows are sandboxed and permission-scanned (section 51)."},
        {"name": "automation", "description": "Mouse/keyboard/screen/file/app/browser primitives."},
        {"name": "kill-switch", "description": "Emergency stop / reset."},
        {"name": "oauth", "description": "OAuth provider integrations (Google, GitHub, Facebook)."},
        {"name": "integrations", "description": "Messaging integrations (Email, WhatsApp, Telegram, Discord)."},
        {"name": "scheduler", "description": "Schedule workflows via cron, file events, hotkeys, webhooks, system events."},
        {"name": "voice", "description": "Voice control pipeline — STT, TTS, wake word, listen-and-plan (never bypasses security confirmation)."},
        {"name": "system", "description": "System tray state, auto-update (section 90), backup/restore (section 91)."},
        {"name": "memory", "description": "Long-term AI memory (section 84) — preferences, workflow, application, task context, temporary."},
        {"name": "profiles", "description": "Multi-profile support (section 49) — personal/work/dev/test sandboxes."},
        {"name": "logs", "description": "Debug log streaming + recent/export (master prompt §38, §57, §73)."},
        {"name": "screenshots", "description": "Screenshot listing, retrieval, deletion, and OCR (master prompt §15, §73)."},
        {"name": "assistant", "description": "Phase 5 Advanced AI OS Assistant (master prompt section 83) - contextual multi-step automation: prepare-meeting, morning routine, end-of-day summary, research, file organisation. Plans never auto-execute (section 66)."},
        {"name": "agent", "description": "Phase 3 AI Computer Agent (master prompt section 81) - vision-based screen analysis, autonomous execution, recovery, and AI workflow generation. All routes honor mock mode + section 86 minimum confidence threshold."},
        {"name": "teams", "description": "Phase 4 Professional RPA (master prompt section 82) - multi-user teams, workspaces, RBAC, enterprise policies. All administrative endpoints are gated by role-based permissions."},
        {"name": "analytics", "description": "Phase 4 execution analytics (master prompt section 82) - workflow run counts, success rates, top tools, top workflows, leaderboard, CSV/JSON export."},
    ],
)

# Lock CORS to localhost — Electron loads renderer from app:// or http://localhost
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "app://."],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------


async def verify_ipc_token(authorization: str | None = None) -> None:
    if settings.ipc_token is None:
        return  # no token configured
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    if token != settings.ipc_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "service": settings.service_name,
        "version": settings.service_version,
        "mock_mode": settings.mock_mode,
        "kill_switch": kill_switch.engaged,
    }


@app.get("/scheduler/health", tags=["scheduler"])
async def scheduler_health() -> dict:
    """Return scheduler runtime status — running flag, jobs_count, next_run.

    Master prompt section 24 — scheduler health endpoint. The endpoint
    is intentionally unauthenticated so the Electron shell can poll it
    for status display.
    """
    return scheduler_manager.health()


# ---------------------------------------------------------------------------
# Tool Registry
# ---------------------------------------------------------------------------


@app.get("/tools", dependencies=[Depends(verify_ipc_token)])
async def list_tools() -> list[dict]:
    return [t.spec().model_dump() for t in tool_registry.all()]


# ---------------------------------------------------------------------------
# Planning / Approval
# ---------------------------------------------------------------------------


@app.post("/task/plan", dependencies=[Depends(verify_ipc_token)])
async def create_plan(goal: str) -> Plan:
    """Generate a plan from a natural-language goal via the Planner agent."""
    if kill_switch.engaged:
        raise HTTPException(status.HTTP_409_CONFLICT, "kill switch engaged")
    from .agents.planner import PlannerAgent

    planner = PlannerAgent()
    plan = await planner.plan(goal)
    event_bus.publish("TASK_CREATED", {"plan_id": str(plan.id), "goal": goal})
    return plan


@app.post("/task/run", dependencies=[Depends(verify_ipc_token)])
async def run_plan(plan: Plan, mode: str = "guided") -> dict:
    """Execute a previously approved plan."""
    if kill_switch.engaged:
        raise HTTPException(status.HTTP_409_CONFLICT, "kill switch engaged")

    # Permission check — every plan goes through the permission engine
    decision = await permission_engine.evaluate_plan(plan)
    if decision == ApprovalResponse and decision.decision.value == "deny":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "plan denied by permission engine")

    executor = WorkflowExecutor()
    run_id = await executor.execute_plan(plan)
    return {"run_id": run_id, "plan_id": str(plan.id), "status": "running"}


@app.post("/task/cancel/{run_id}", dependencies=[Depends(verify_ipc_token)])
async def cancel_run(run_id: str) -> dict:
    executor = WorkflowExecutor()
    await executor.cancel(run_id)
    return {"run_id": run_id, "status": "cancelled"}


# ---------------------------------------------------------------------------
# Workflow CRUD
# ---------------------------------------------------------------------------


@app.post("/workflow", dependencies=[Depends(verify_ipc_token)])
async def save_workflow(workflow: Workflow) -> dict:
    wf_path = settings.workflows_dir / f"{workflow.id}.json"
    wf_path.write_text(workflow.model_dump_json(indent=2), encoding="utf-8")
    return {"id": workflow.id, "saved": True, "profile_id": workflow.profile_id}


@app.get("/workflow", dependencies=[Depends(verify_ipc_token)])
async def list_workflows(
    profile_id: str | None = None,
) -> list[dict]:
    """List saved workflows.

    If ``profile_id`` is supplied, only workflows whose ``profile_id`` is
    either ``None`` (global) or equal to the requested profile are returned
    — master prompt §49 (profile isolation).
    """
    out = []
    for p in settings.workflows_dir.glob("*.json"):
        try:
            wf = Workflow.model_validate_json(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        # Profile filtering — global workflows (profile_id=None) are always
        # visible; profile-scoped workflows are visible only to that profile.
        if profile_id is not None:
            if wf.profile_id is not None and wf.profile_id != profile_id:
                continue
        out.append(
            {
                "id": wf.id,
                "name": wf.name,
                "version": wf.version,
                "enabled": wf.enabled,
                "profile_id": wf.profile_id,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Automation primitives (per master prompt §75)
# ---------------------------------------------------------------------------


@app.post("/automation/click", dependencies=[Depends(verify_ipc_token)])
async def automation_click(x: int, y: int, button: str = "left") -> ActionResult:
    req = ActionRequest(tool="mouse.click", args={"x": x, "y": y, "button": button})
    return await _run_action(req)


@app.post("/automation/type", dependencies=[Depends(verify_ipc_token)])
async def automation_type(text: str) -> ActionResult:
    req = ActionRequest(tool="keyboard.type", args={"text": text})
    return await _run_action(req)


@app.post("/automation/screenshot", dependencies=[Depends(verify_ipc_token)])
async def automation_screenshot() -> ActionResult:
    req = ActionRequest(tool="screen.capture", args={})
    return await _run_action(req)


async def _run_action(req: ActionRequest) -> ActionResult:
    if kill_switch.engaged:
        raise HTTPException(status.HTTP_409_CONFLICT, "kill switch engaged")

    tool = tool_registry.get(req.tool)
    if tool is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"tool '{req.tool}' not found")

    # Permission check
    decision = await permission_engine.evaluate_action(req, tool.spec())
    if decision.decision.value in {"deny", "cancel"}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"action denied: {decision.decision.value}")

    try:
        result = await tool.execute(req.args)
        return result
    except Exception as exc:
        return ActionResult(tool=req.tool, status="failed", error=str(exc))


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------


@app.post("/emergency-stop", dependencies=[Depends(verify_ipc_token)])
async def emergency_stop() -> dict:
    kill_switch.engage()
    return {"engaged": True}


@app.post("/emergency-reset", dependencies=[Depends(verify_ipc_token)])
async def emergency_reset() -> dict:
    kill_switch.reset()
    return {"engaged": False}


# ---------------------------------------------------------------------------
# WebSocket — live event stream (master prompt §77)
# ---------------------------------------------------------------------------


class ConnectionManager:
    def __init__(self) -> None:
        self._conns: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._conns.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self._conns:
            self._conns.remove(ws)

    async def broadcast(self, event: dict) -> None:
        dead: list[WebSocket] = []
        for ws in self._conns:
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()


@app.websocket("/events")
async def ws_events(ws: WebSocket) -> None:
    await manager.connect(ws)
    queue = event_bus.subscribe()

    async def _pusher() -> None:
        try:
            while True:
                event_type, payload = await queue.get()
                await ws.send_json({"type": event_type, "payload": payload})
        except WebSocketDisconnect:
            return

    try:
        await _pusher()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(ws)


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------


@app.exception_handler(Exception)
async def unhandled_exc(request, exc: Exception) -> JSONResponse:
    event_bus.publish("UNHANDLED_ERROR", {"error": str(exc), "type": type(exc).__name__})
    return JSONResponse(
        status_code=500,
        content={"error": str(exc), "type": type(exc).__name__},
    )


# ---------------------------------------------------------------------------
# OAuth + Integrations routers (master prompt §54)
# ---------------------------------------------------------------------------

app.include_router(oauth_router, prefix="/oauth", tags=["oauth"])
app.include_router(integration_router, prefix="/integrations", tags=["integrations"])
app.include_router(schedules_router, prefix="/schedules", tags=["scheduler"])
app.include_router(workflow_router, prefix="/workflow", tags=["workflow"])
app.include_router(marketplace_router, prefix="/marketplace", tags=["marketplace"])
app.include_router(voice_router, prefix="/voice", tags=["voice"])
app.include_router(system_router, prefix="/system", tags=["system"])
app.include_router(memory_router, prefix="/memory", tags=["memory"])
app.include_router(profiles_router, prefix="/profiles", tags=["profiles"])
app.include_router(logs_router, prefix="/logs", tags=["logs"])
app.include_router(screenshots_router, prefix="/screenshots", tags=["screenshots"])
app.include_router(assistant_router, prefix="/assistant", tags=["assistant"])
# Task recorder — master prompt §22 (Task Recorder) + §35 (Recorder UI).
app.include_router(recorder_router, prefix="/recorder", tags=["recorder"])
# Browser sessions — master prompt §16 (Playwright) + §17 (browser agent).
app.include_router(browser_router, prefix="/browser", tags=["browser"])
# Files — master prompt §18 (file automation) + §55 (file security).
app.include_router(files_router, prefix="/files", tags=["files"])
# Task history — master prompt §36 (task history).
app.include_router(history_router, prefix="/history", tags=["history"])
# AI models / providers / credentials — master prompt §6 (52 AI providers)
# + §28 (credential security) + §57 (never log secrets).
# Mounted at the root (NOT under a prefix) because the routes themselves
# are /ai-models, /providers, /credentials.
app.include_router(ai_models_router, tags=["ai-models"])
# Permissions — master prompt §9 (risk levels) + §10 (human confirmation)
# + §55 (security architecture) + §88 (rate limits).
app.include_router(permissions_router, prefix="/permissions", tags=["permissions"])
# Phase 3 AI Computer Agent — master prompt §81 (multi-step autonomous
# execution), §14 (screen understanding), §86 (vision confidence
# threshold), §85 (Autonomous Mode — never bypasses security controls).
app.include_router(agent_router, prefix="/agent", tags=["agent"])
# Phase 4 Professional RPA — master prompt §82 (multi-user support,
# teams, workspaces, RBAC, enterprise policies, execution analytics).
# The team router carries its own RBAC dependencies (require_permission)
# in addition to the IPC bearer token; the analytics router carries
# the IPC bearer token + filters by team_id.
app.include_router(team_router, prefix="/teams", tags=["teams"])
app.include_router(analytics_router, prefix="/analytics", tags=["analytics"])
