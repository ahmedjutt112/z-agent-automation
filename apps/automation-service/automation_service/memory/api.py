"""FastAPI router for AI Memory — mounted under /memory in main.py.

Endpoints (master prompt section 84):

- POST   /memory/remember              body: {type, key, value, source?, ttl_seconds?, user_id?, workflow_id?, task_id?}
- GET    /memory/recall                query: type, key?, user_id?
- DELETE /memory/{memory_id}           forgets a single memory
- DELETE /memory/type/{memory_type}    forgets all of a type (query: key?, user_id?)
- GET    /memory/context/{user_id}     planner context
- GET    /memory/inspect/{user_id}     GDPR-style inspection
- DELETE /memory/user/{user_id}        GDPR right-to-be-forgotten
- POST   /memory/detect-sensitive      body: {value, key?} → {sensitive: bool}

All routes require the IPC bearer token (resolved lazily from main).
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from ..memory.manager import Memory, MemoryManager, MemoryType, memory_manager


router = APIRouter()


# ---------------------------------------------------------------------------
# Auth — lazy import to avoid the circular dep with main.
# ---------------------------------------------------------------------------


async def _verify_ipc_token(authorization: str | None = None) -> None:
    from ..main import verify_ipc_token

    await verify_ipc_token(authorization)


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class RememberRequest(BaseModel):
    type: MemoryType
    key: str
    value: Any
    source: str = "system"
    ttl_seconds: Optional[int] = None
    user_id: str = "default"
    workflow_id: Optional[str] = None
    task_id: Optional[str] = None


class RememberResponse(BaseModel):
    memory_id: str
    stored: bool = True


class DetectSensitiveRequest(BaseModel):
    value: Any
    key: Optional[str] = None


class DetectSensitiveResponse(BaseModel):
    sensitive: bool
    reason: Optional[str] = None


class ForgetResponse(BaseModel):
    forgotten: bool


class ForgetAllResponse(BaseModel):
    count: int


class ClearUserResponse(BaseModel):
    user_id: str
    count: int


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/remember",
    response_model=RememberResponse,
    dependencies=[Depends(_verify_ipc_token)],
    tags=["memory"],
)
async def remember_memory(req: RememberRequest) -> RememberResponse:
    """Store a memory entry. Raises 400 if the value looks sensitive."""
    try:
        memory_id = await memory_manager.remember(
            memory_type=req.type,
            key=req.key,
            value=req.value,
            source=req.source,
            ttl_seconds=req.ttl_seconds,
            user_id=req.user_id,
            workflow_id=req.workflow_id,
            task_id=req.task_id,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return RememberResponse(memory_id=memory_id)


@router.get(
    "/recall",
    response_model=list[Memory],
    dependencies=[Depends(_verify_ipc_token)],
    tags=["memory"],
)
async def recall_memory(
    type: MemoryType = Query(...),
    key: Optional[str] = Query(None),
    user_id: str = Query("default"),
) -> list[Memory]:
    return await memory_manager.recall(type, key=key, user_id=user_id)


@router.delete(
    "/{memory_id}",
    response_model=ForgetResponse,
    dependencies=[Depends(_verify_ipc_token)],
    tags=["memory"],
)
async def forget_memory(memory_id: str) -> ForgetResponse:
    ok = await memory_manager.forget(memory_id)
    return ForgetResponse(forgotten=ok)


@router.delete(
    "/type/{memory_type}",
    response_model=ForgetAllResponse,
    dependencies=[Depends(_verify_ipc_token)],
    tags=["memory"],
)
async def forget_all_of_type(
    memory_type: MemoryType,
    key: Optional[str] = Query(None),
    user_id: str = Query("default"),
) -> ForgetAllResponse:
    count = await memory_manager.forget_all(memory_type, key=key, user_id=user_id)
    return ForgetAllResponse(count=count)


@router.get(
    "/context/{user_id}",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["memory"],
)
async def get_planner_context(user_id: str) -> dict:
    return await memory_manager.get_context_for_planner(user_id=user_id)


@router.get(
    "/inspect/{user_id}",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["memory"],
)
async def inspect_user_data(user_id: str) -> dict:
    return await memory_manager.inspect_user_data(user_id)


@router.delete(
    "/user/{user_id}",
    response_model=ClearUserResponse,
    dependencies=[Depends(_verify_ipc_token)],
    tags=["memory"],
)
async def clear_user_data(user_id: str) -> ClearUserResponse:
    count = await memory_manager.clear_all_user_data(user_id)
    return ClearUserResponse(user_id=user_id, count=count)


@router.post(
    "/detect-sensitive",
    response_model=DetectSensitiveResponse,
    dependencies=[Depends(_verify_ipc_token)],
    tags=["memory"],
)
async def detect_sensitive(req: DetectSensitiveRequest) -> DetectSensitiveResponse:
    sensitive = await memory_manager.detect_sensitive_data(req.value, key=req.key)
    reason = (
        "value or key matches a known secret pattern (password / API key / "
        "token / credit card)"
        if sensitive
        else None
    )
    return DetectSensitiveResponse(sensitive=sensitive, reason=reason)
