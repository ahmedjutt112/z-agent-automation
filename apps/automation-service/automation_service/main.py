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
from .scheduler.manager import scheduler_manager
from .scheduler.api import router as schedules_router


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    ensure_runtime_dirs()
    tool_registry.discover()
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
        {"name": "automation", "description": "Mouse/keyboard/screen/file/app/browser primitives."},
        {"name": "kill-switch", "description": "Emergency stop / reset."},
        {"name": "oauth", "description": "OAuth provider integrations (Google, GitHub, Facebook)."},
        {"name": "integrations", "description": "Messaging integrations (Email, WhatsApp, Telegram, Discord)."},
        {"name": "scheduler", "description": "Schedule workflows via cron, file events, hotkeys, webhooks, system events."},
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
    return {"id": workflow.id, "saved": True}


@app.get("/workflow", dependencies=[Depends(verify_ipc_token)])
async def list_workflows() -> list[dict]:
    out = []
    for p in settings.workflows_dir.glob("*.json"):
        try:
            wf = Workflow.model_validate_json(p.read_text(encoding="utf-8"))
            out.append({"id": wf.id, "name": wf.name, "version": wf.version, "enabled": wf.enabled})
        except Exception:
            continue
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
