"""Tests for AI Memory (master prompt section 84) + Multi-Profile support (section 49).

Covers:
- MemoryManager: remember / recall / forget / forget_all / temporary expiry /
  detect_sensitive_data / get_context_for_planner / inspect_user_data /
  clear_all_user_data
- /memory API: remember / recall / detect-sensitive / inspect / clear-user
- /profiles API: create / list / activate / get-active / delete

All tests run in mock mode (settings.mock_mode=True) so the in-memory stores
are used — no real DB I/O is performed.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from automation_service.memory.manager import (
    MemoryManager,
    MemoryType,
    memory_manager,
)


# ---------------------------------------------------------------------------
# Fixtures — reset the in-memory stores between tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_memory_store():
    """Wipe the in-memory memory store + profile store between tests."""
    memory_manager._in_memory_store._rows.clear()
    # Profiles store is module-level on a different module.
    from automation_service.profiles.api import _store as _profile_store

    _profile_store._by_user.clear()
    _profile_store._active.clear()
    yield
    memory_manager._in_memory_store._rows.clear()
    _profile_store._by_user.clear()
    _profile_store._active.clear()


# ---------------------------------------------------------------------------
# Memory — unit tests
# ---------------------------------------------------------------------------


async def test_memory_remember_user_preference() -> None:
    mem_id = await memory_manager.remember(
        MemoryType.USER_PREFERENCES,
        "downloads_folder",
        "/home/z/Downloads",
        source="unit-test",
        user_id="user-a",
    )
    assert isinstance(mem_id, str) and len(mem_id) > 0


async def test_memory_recall_by_key() -> None:
    await memory_manager.remember(
        MemoryType.USER_PREFERENCES,
        "downloads_folder",
        "/home/z/Downloads",
        user_id="user-a",
    )
    hits = await memory_manager.recall(
        MemoryType.USER_PREFERENCES, key="downloads_folder", user_id="user-a"
    )
    assert len(hits) == 1
    assert hits[0].key == "downloads_folder"
    assert hits[0].value == "/home/z/Downloads"
    assert hits[0].user_id == "user-a"


async def test_memory_recall_all_of_type() -> None:
    await memory_manager.remember(
        MemoryType.USER_PREFERENCES, "k1", "v1", user_id="user-b"
    )
    await memory_manager.remember(
        MemoryType.USER_PREFERENCES, "k2", "v2", user_id="user-b"
    )
    await memory_manager.remember(
        MemoryType.USER_PREFERENCES, "k3", "v3", user_id="user-b"
    )
    hits = await memory_manager.recall(MemoryType.USER_PREFERENCES, user_id="user-b")
    assert len(hits) == 3
    keys = {h.key for h in hits}
    assert keys == {"k1", "k2", "k3"}


async def test_memory_forget() -> None:
    mem_id = await memory_manager.remember(
        MemoryType.USER_PREFERENCES, "tmp", "v", user_id="user-c"
    )
    ok = await memory_manager.forget(mem_id)
    assert ok is True
    remaining = await memory_manager.recall(
        MemoryType.USER_PREFERENCES, key="tmp", user_id="user-c"
    )
    assert len(remaining) == 0


async def test_memory_forget_all() -> None:
    await memory_manager.remember(
        MemoryType.USER_PREFERENCES, "k1", "v1", user_id="user-d"
    )
    await memory_manager.remember(
        MemoryType.USER_PREFERENCES, "k2", "v2", user_id="user-d"
    )
    await memory_manager.remember(
        MemoryType.WORKFLOW, "k3", "v3", user_id="user-d"
    )
    count = await memory_manager.forget_all(
        MemoryType.USER_PREFERENCES, user_id="user-d"
    )
    assert count == 2
    prefs = await memory_manager.recall(MemoryType.USER_PREFERENCES, user_id="user-d")
    assert len(prefs) == 0
    # Other types are untouched.
    wfs = await memory_manager.recall(MemoryType.WORKFLOW, user_id="user-d")
    assert len(wfs) == 1


async def test_memory_temporary_expires() -> None:
    """TemporaryMemory with ttl_seconds=0 is expired on recall."""
    mem_id = await memory_manager.remember(
        MemoryType.TEMPORARY,
        "short-lived",
        "boom",
        ttl_seconds=0,
        user_id="user-e",
    )
    assert mem_id
    # Sleep briefly so datetime.now() advances past expires_at.
    await asyncio.sleep(0.01)
    hits = await memory_manager.recall(
        MemoryType.TEMPORARY, key="short-lived", user_id="user-e"
    )
    assert len(hits) == 0, "temporary memory should have expired"


async def test_memory_detect_sensitive_password() -> None:
    sensitive = await memory_manager.detect_sensitive_data("password123")
    assert sensitive is True


async def test_memory_detect_sensitive_api_key() -> None:
    sensitive = await memory_manager.detect_sensitive_data("sk-1234567890abcdef")
    assert sensitive is True


async def test_memory_detect_sensitive_non_secret() -> None:
    sensitive = await memory_manager.detect_sensitive_data("hello world")
    assert sensitive is False


async def test_memory_get_context_for_planner() -> None:
    await memory_manager.remember(
        MemoryType.USER_PREFERENCES,
        "default_provider",
        "openai",
        user_id="user-f",
    )
    await memory_manager.remember(
        MemoryType.WORKFLOW,
        "last-run",
        {"name": "daily-report"},
        user_id="user-f",
        workflow_id="wf-1",
    )
    await memory_manager.remember(
        MemoryType.TASK_CONTEXT,
        "active-task",
        {"goal": "take screenshot"},
        user_id="user-f",
        task_id="task-1",
    )
    ctx = await memory_manager.get_context_for_planner(user_id="user-f")
    assert "user_preferences" in ctx
    assert "recent_workflow_memory" in ctx
    assert "active_task_context" in ctx
    assert len(ctx["user_preferences"]) == 1
    assert ctx["user_preferences"][0]["key"] == "default_provider"
    assert ctx["user_preferences"][0]["value"] == "openai"


async def test_memory_inspect_user_data() -> None:
    await memory_manager.remember(
        MemoryType.USER_PREFERENCES, "k1", "v1", user_id="user-g"
    )
    await memory_manager.remember(
        MemoryType.APPLICATION, "vscode", {"theme": "dark"}, user_id="user-g"
    )
    result = await memory_manager.inspect_user_data("user-g")
    assert result["user_id"] == "user-g"
    assert result["count"] == 2
    assert "user_preferences" in result["memories"]
    assert "application" in result["memories"]
    assert len(result["memories"]["user_preferences"]) == 1


async def test_memory_clear_all_user_data() -> None:
    await memory_manager.remember(
        MemoryType.USER_PREFERENCES, "k1", "v1", user_id="user-h"
    )
    await memory_manager.remember(
        MemoryType.WORKFLOW, "k2", "v2", user_id="user-h"
    )
    await memory_manager.remember(
        MemoryType.TASK_CONTEXT, "k3", "v3", user_id="user-h"
    )
    count = await memory_manager.clear_all_user_data("user-h")
    assert count == 3
    result = await memory_manager.inspect_user_data("user-h")
    assert result["count"] == 0


async def test_memory_remember_refuses_sensitive_value() -> None:
    """Section 57: secrets must not auto-persist."""
    with pytest.raises(ValueError):
        await memory_manager.remember(
            MemoryType.USER_PREFERENCES,
            "my_password",
            "password123",
            user_id="user-i",
        )


# ---------------------------------------------------------------------------
# /memory API tests
# ---------------------------------------------------------------------------


def test_api_memory_remember(client) -> None:
    r = client.post(
        "/memory/remember",
        json={
            "type": "user_preferences",
            "key": "downloads_folder",
            "value": "/home/z/Downloads",
            "user_id": "api-user-a",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert "memory_id" in body
    assert body["stored"] is True


def test_api_memory_recall(client) -> None:
    client.post(
        "/memory/remember",
        json={
            "type": "user_preferences",
            "key": "theme",
            "value": "dark",
            "user_id": "api-user-b",
        },
    )
    r = client.get(
        "/memory/recall",
        params={"type": "user_preferences", "user_id": "api-user-b"},
    )
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list)
    assert len(rows) == 1
    assert rows[0]["key"] == "theme"
    assert rows[0]["value"] == "dark"


def test_api_memory_detect_sensitive(client) -> None:
    r = client.post(
        "/memory/detect-sensitive",
        json={"value": "sk-1234567890abcdef"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["sensitive"] is True


def test_api_memory_detect_sensitive_non_secret(client) -> None:
    r = client.post(
        "/memory/detect-sensitive",
        json={"value": "the quick brown fox"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["sensitive"] is False


def test_api_memory_inspect_user(client) -> None:
    client.post(
        "/memory/remember",
        json={
            "type": "user_preferences",
            "key": "lang",
            "value": "en-US",
            "user_id": "api-user-c",
        },
    )
    client.post(
        "/memory/remember",
        json={
            "type": "application",
            "key": "vscode",
            "value": {"theme": "dark"},
            "user_id": "api-user-c",
        },
    )
    r = client.get("/memory/inspect/api-user-c")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
    assert "user_preferences" in body["memories"]
    assert "application" in body["memories"]


def test_api_memory_clear_user(client) -> None:
    client.post(
        "/memory/remember",
        json={
            "type": "user_preferences",
            "key": "tmp",
            "value": "x",
            "user_id": "api-user-d",
        },
    )
    r = client.delete("/memory/user/api-user-d")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 1
    # Confirm gone.
    r2 = client.get("/memory/inspect/api-user-d")
    assert r2.json()["count"] == 0


# ---------------------------------------------------------------------------
# /profiles API tests
# ---------------------------------------------------------------------------


def test_profile_create(client) -> None:
    r = client.post(
        "/profiles",
        json={"name": "Work", "type": "work", "user_id": "user-1"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Work"
    assert body["profile_type"] == "work"
    assert body["user_id"] == "user-1"
    assert isinstance(body["id"], str) and len(body["id"]) > 0


def test_profile_list(client) -> None:
    client.post("/profiles", json={"name": "Personal", "type": "personal", "user_id": "user-2"})
    r = client.get("/profiles", params={"user_id": "user-2"})
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list)
    assert len(rows) >= 1
    assert rows[0]["name"] == "Personal"


def test_profile_activate(client) -> None:
    create = client.post(
        "/profiles", json={"name": "Dev", "type": "dev", "user_id": "user-3"}
    ).json()
    profile_id = create["id"]
    r = client.post(
        f"/profiles/{profile_id}/activate", params={"user_id": "user-3"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["profile_id"] == profile_id
    assert body["activated"] is True


def test_profile_get_active(client) -> None:
    create = client.post(
        "/profiles", json={"name": "Test", "type": "test", "user_id": "user-4"}
    ).json()
    profile_id = create["id"]
    client.post(f"/profiles/{profile_id}/activate", params={"user_id": "user-4"})
    r = client.get("/profiles/active", params={"user_id": "user-4"})
    assert r.status_code == 200
    body = r.json()
    assert body is not None
    assert body["id"] == profile_id
    assert body["is_active"] is True


def test_profile_delete(client) -> None:
    create = client.post(
        "/profiles", json={"name": "Tmp", "type": "personal", "user_id": "user-5"}
    ).json()
    profile_id = create["id"]
    r = client.delete(f"/profiles/{profile_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["deleted"] is True
    # Confirm gone.
    r2 = client.get(f"/profiles/{profile_id}")
    assert r2.status_code == 404
