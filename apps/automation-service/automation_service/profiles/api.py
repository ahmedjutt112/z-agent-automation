"""FastAPI router for Multi-Profile support — mounted under /profiles.

Endpoints (master prompt section 49):

- GET    /profiles                 list all profiles for a user
- POST   /profiles                 create a new profile
- GET    /profiles/active          get the currently active profile
- GET    /profiles/{profile_id}    get a profile by id
- PUT    /profiles/{profile_id}    update name / type / config
- DELETE /profiles/{profile_id}    delete a profile
- POST   /profiles/{profile_id}/activate  set as active

All routes require the IPC bearer token. Profile-scoped resources
(workflows / permissions / browser sessions) are filtered by ``profile_id``;
callers pass ``?profile_id=...`` to those endpoints to scope the result.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from ..config import settings
from ..memory.manager import memory_manager, MemoryType
from database.models.schema import DeviceProfile


router = APIRouter()


# ---------------------------------------------------------------------------
# Auth — lazy import to avoid the circular dep with main.
# ---------------------------------------------------------------------------


async def _verify_ipc_token(authorization: str | None = None) -> None:
    from ..main import verify_ipc_token

    await verify_ipc_token(authorization)


# ---------------------------------------------------------------------------
# In-memory store (mock mode + active-profile state)
# ---------------------------------------------------------------------------


class _ProfileStore:
    """Simple in-memory profile store used in mock mode + to track the
    currently-active profile across both mock and DB modes."""

    def __init__(self) -> None:
        # user_id -> {profile_id -> DeviceProfile-as-dict}
        self._by_user: dict[str, dict[str, dict]] = {}
        # user_id -> active profile_id
        self._active: dict[str, str] = {}

    def all_for_user(self, user_id: str) -> list[dict]:
        return list(self._by_user.get(user_id, {}).values())

    def get(self, profile_id: str) -> Optional[dict]:
        for bucket in self._by_user.values():
            if profile_id in bucket:
                return bucket[profile_id]
        return None

    def add(self, profile: dict) -> None:
        bucket = self._by_user.setdefault(profile["user_id"], {})
        bucket[profile["id"]] = profile

    def delete(self, profile_id: str) -> bool:
        for bucket in self._by_user.values():
            if profile_id in bucket:
                del bucket[profile_id]
                # If it was the active profile, clear active.
                for uid, pid in list(self._active.items()):
                    if pid == profile_id:
                        self._active[uid] = ""
                return True
        return False

    def set_active(self, user_id: str, profile_id: str) -> None:
        self._active[user_id] = profile_id

    def get_active(self, user_id: str) -> Optional[dict]:
        pid = self._active.get(user_id)
        if not pid:
            return None
        return self.get(pid)


_store = _ProfileStore()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ProfileType(str):
    """Allowed profile types (master prompt section 49)."""
    ALLOWED = {"personal", "work", "dev", "test"}


class CreateProfileRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    type: str = Field("personal", description="personal | work | dev | test")
    config: Optional[dict[str, Any]] = None
    user_id: str = "default"


class UpdateProfileRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=64)
    type: Optional[str] = None
    config: Optional[dict[str, Any]] = None
    is_default: Optional[bool] = None


class ProfileResponse(BaseModel):
    id: str
    user_id: str
    name: str
    profile_type: str
    is_default: bool
    config_json: dict[str, Any]
    is_active: bool = False
    created_at: datetime
    updated_at: datetime


class ActivateResponse(BaseModel):
    profile_id: str
    activated: bool


class DeleteResponse(BaseModel):
    profile_id: str
    deleted: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_ALLOWED_TYPES = {"personal", "work", "dev", "test"}


def _profile_to_response(row: DeviceProfile | dict, active_id: Optional[str]) -> ProfileResponse:
    if isinstance(row, dict):
        return ProfileResponse(
            id=row["id"],
            user_id=row["user_id"],
            name=row["name"],
            profile_type=row["profile_type"],
            is_default=row.get("is_default", False),
            config_json=row.get("config_json", {}),
            is_active=(active_id == row["id"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
    return ProfileResponse(
        id=row.id,
        user_id=row.user_id,
        name=row.name,
        profile_type=row.profile_type,
        is_default=row.is_default,
        config_json=row.config_json or {},
        is_active=(active_id == row.id),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _row_to_dict(row: DeviceProfile) -> dict:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "name": row.name,
        "profile_type": row.profile_type,
        "is_default": row.is_default,
        "config_json": row.config_json or {},
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=list[ProfileResponse],
    dependencies=[Depends(_verify_ipc_token)],
    tags=["profiles"],
)
async def list_profiles(user_id: str = Query("default")) -> list[ProfileResponse]:
    if settings.mock_mode:
        rows = _store.all_for_user(user_id)
        active = _store.get_active(user_id)
        active_id = active["id"] if active else None
        return [_profile_to_response(r, active_id) for r in rows]

    from database.base import SessionLocal

    with SessionLocal() as session:
        rows = (
            session.query(DeviceProfile)
            .filter(DeviceProfile.user_id == user_id)
            .order_by(DeviceProfile.created_at)
            .all()
        )
        active = _store.get_active(user_id)
        active_id = active["id"] if active else None
        return [_profile_to_response(r, active_id) for r in rows]


@router.post(
    "",
    response_model=ProfileResponse,
    dependencies=[Depends(_verify_ipc_token)],
    tags=["profiles"],
)
async def create_profile(req: CreateProfileRequest) -> ProfileResponse:
    if req.type not in _ALLOWED_TYPES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"invalid profile type '{req.type}'. Allowed: {sorted(_ALLOWED_TYPES)}",
        )

    profile_id = str(uuid.uuid4())
    now = _now()
    row_dict = {
        "id": profile_id,
        "user_id": req.user_id,
        "name": req.name,
        "profile_type": req.type,
        "is_default": False,
        "config_json": req.config or {},
        "created_at": now,
        "updated_at": now,
    }

    if settings.mock_mode:
        _store.add(row_dict)
        # First profile becomes active automatically.
        if _store.get_active(req.user_id) is None:
            _store.set_active(req.user_id, profile_id)
        return _profile_to_response(row_dict, profile_id)

    from database.base import SessionLocal

    with SessionLocal() as session:
        row = DeviceProfile(
            id=profile_id,
            user_id=req.user_id,
            name=req.name,
            profile_type=req.type,
            is_default=False,
            config_json=req.config or {},
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        # First profile becomes active automatically.
        if _store.get_active(req.user_id) is None:
            _store.set_active(req.user_id, profile_id)
        return _profile_to_response(row, profile_id)


@router.get(
    "/active",
    response_model=Optional[ProfileResponse],
    dependencies=[Depends(_verify_ipc_token)],
    tags=["profiles"],
)
async def get_active_profile(user_id: str = Query("default")) -> Optional[ProfileResponse]:
    active = _store.get_active(user_id)
    if active is None:
        return None
    return _profile_to_response(active, active["id"])


@router.get(
    "/{profile_id}",
    response_model=ProfileResponse,
    dependencies=[Depends(_verify_ipc_token)],
    tags=["profiles"],
)
async def get_profile(profile_id: str) -> ProfileResponse:
    if settings.mock_mode:
        row = _store.get(profile_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"profile '{profile_id}' not found")
        # Need to find the active profile for this user to set is_active correctly.
        active = _store.get_active(row["user_id"])
        active_id = active["id"] if active else None
        return _profile_to_response(row, active_id)

    from database.base import SessionLocal

    with SessionLocal() as session:
        row = session.query(DeviceProfile).filter(DeviceProfile.id == profile_id).first()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"profile '{profile_id}' not found")
        active = _store.get_active(row.user_id)
        active_id = active["id"] if active else None
        return _profile_to_response(row, active_id)


@router.put(
    "/{profile_id}",
    response_model=ProfileResponse,
    dependencies=[Depends(_verify_ipc_token)],
    tags=["profiles"],
)
async def update_profile(profile_id: str, req: UpdateProfileRequest) -> ProfileResponse:
    if req.type is not None and req.type not in _ALLOWED_TYPES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"invalid profile type '{req.type}'. Allowed: {sorted(_ALLOWED_TYPES)}",
        )

    if settings.mock_mode:
        row = _store.get(profile_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"profile '{profile_id}' not found")
        if req.name is not None:
            row["name"] = req.name
        if req.type is not None:
            row["profile_type"] = req.type
        if req.config is not None:
            row["config_json"] = req.config
        if req.is_default is not None:
            row["is_default"] = req.is_default
        row["updated_at"] = _now()
        active = _store.get_active(row["user_id"])
        return _profile_to_response(row, active["id"] if active else None)

    from database.base import SessionLocal

    with SessionLocal() as session:
        row = session.query(DeviceProfile).filter(DeviceProfile.id == profile_id).first()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"profile '{profile_id}' not found")
        if req.name is not None:
            row.name = req.name
        if req.type is not None:
            row.profile_type = req.type
        if req.config is not None:
            row.config_json = req.config
        if req.is_default is not None:
            row.is_default = req.is_default
        row.updated_at = _now()
        session.commit()
        session.refresh(row)
        active = _store.get_active(row.user_id)
        return _profile_to_response(row, active["id"] if active else None)


@router.delete(
    "/{profile_id}",
    response_model=DeleteResponse,
    dependencies=[Depends(_verify_ipc_token)],
    tags=["profiles"],
)
async def delete_profile(profile_id: str) -> DeleteResponse:
    if settings.mock_mode:
        ok = _store.delete(profile_id)
        if not ok:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"profile '{profile_id}' not found")
        return DeleteResponse(profile_id=profile_id, deleted=True)

    from database.base import SessionLocal

    with SessionLocal() as session:
        row = session.query(DeviceProfile).filter(DeviceProfile.id == profile_id).first()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"profile '{profile_id}' not found")
        session.delete(row)
        session.commit()
        # Clear active if it was the active profile.
        for uid, pid in list(_store._active.items()):  # type: ignore[attr-defined]
            if pid == profile_id:
                _store._active[uid] = ""  # type: ignore[attr-defined]
        return DeleteResponse(profile_id=profile_id, deleted=True)


@router.post(
    "/{profile_id}/activate",
    response_model=ActivateResponse,
    dependencies=[Depends(_verify_ipc_token)],
    tags=["profiles"],
)
async def activate_profile(
    profile_id: str,
    user_id: str = Query("default"),
) -> ActivateResponse:
    # Verify the profile exists in either store.
    if settings.mock_mode:
        row = _store.get(profile_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"profile '{profile_id}' not found")
        _store.set_active(row["user_id"], profile_id)
        # Remember the active profile id in user preferences memory (section 84).
        try:
            await memory_manager.forget_all(MemoryType.USER_PREFERENCES, key="active_profile_id", user_id=row["user_id"])
            await memory_manager.remember(
                MemoryType.USER_PREFERENCES,
                "active_profile_id",
                profile_id,
                source="profiles.api",
                user_id=row["user_id"],
            )
        except Exception:
            pass
        return ActivateResponse(profile_id=profile_id, activated=True)

    from database.base import SessionLocal

    with SessionLocal() as session:
        row = session.query(DeviceProfile).filter(DeviceProfile.id == profile_id).first()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"profile '{profile_id}' not found")
        _store.set_active(row.user_id, profile_id)
        try:
            await memory_manager.forget_all(
                MemoryType.USER_PREFERENCES, key="active_profile_id", user_id=row.user_id
            )
            await memory_manager.remember(
                MemoryType.USER_PREFERENCES,
                "active_profile_id",
                profile_id,
                source="profiles.api",
                user_id=row.user_id,
            )
        except Exception:
            pass
        return ActivateResponse(profile_id=profile_id, activated=True)
