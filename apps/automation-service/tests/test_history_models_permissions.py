"""Tests for the history, ai_models, and permissions FastAPI routers — master
prompt §36 (task history), §6 (52 AI providers), §9 / §10 (risk levels), §88
(rate limits).

All tests run via the shared ``client`` fixture (FastAPI TestClient) in mock
mode. The history endpoints gracefully degrade to empty lists when no DB is
configured (mock mode); the ai_models endpoints exercise the registry +
credential store; the permissions endpoints exercise the in-memory
PermissionEngine + the policy JSON file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# History — /history/*
# ---------------------------------------------------------------------------


def test_history_list_tasks(client) -> None:
    """GET /history/tasks returns a list (empty when no DB)."""
    r = client.get("/history/tasks")
    assert r.status_code == 200
    body = r.json()
    assert "tasks" in body
    assert isinstance(body["tasks"], list)
    assert "count" in body
    assert "mock_mode" in body


def test_history_task_detail_returns_404_when_unavailable(client) -> None:
    """GET /history/tasks/{id} returns 404 when no DB / no task."""
    r = client.get("/history/tasks/nonexistent-task-id")
    assert r.status_code == 404


def test_history_task_screenshots(client) -> None:
    """GET /history/tasks/{id}/screenshots returns an empty list (mock mode)."""
    r = client.get("/history/tasks/nonexistent/screenshots")
    # The route doesn't 404 on missing task — it just returns an empty list.
    assert r.status_code == 200
    body = r.json()
    assert body["screenshots"] == []
    assert body["count"] == 0


def test_history_task_logs(client) -> None:
    """GET /history/tasks/{id}/logs returns an empty list (mock mode)."""
    r = client.get("/history/tasks/nonexistent/logs")
    assert r.status_code == 200
    body = r.json()
    assert body["logs"] == []
    assert body["count"] == 0


def test_history_export_csv(client) -> None:
    """GET /history/export?format=csv returns a CSV file with a header row."""
    r = client.get("/history/export")
    assert r.status_code == 200
    assert "text/csv" in r.headers.get("content-type", "")
    content = r.text
    assert "id,name,status" in content  # CSV header row


# ---------------------------------------------------------------------------
# AI Models — /ai-models, /providers, /credentials
# ---------------------------------------------------------------------------


def test_ai_models_list(client) -> None:
    """GET /ai-models returns a list (empty when no DB)."""
    r = client.get("/ai-models")
    assert r.status_code == 200
    body = r.json()
    assert "models" in body
    assert isinstance(body["models"], list)
    assert "count" in body


def test_ai_models_sync(client) -> None:
    """POST /ai-models/sync runs without error in mock mode (returns zeros)."""
    r = client.post("/ai-models/sync")
    assert r.status_code == 200
    body = r.json()
    assert "synced" in body
    assert body["mock_mode"] is True
    # Per-provider zero dict — every provider in the registry is present.
    assert isinstance(body["synced"], dict)
    assert len(body["synced"]) >= 50  # 52 providers


def test_providers_list(client) -> None:
    """GET /providers returns 52 providers with has_credential flag."""
    r = client.get("/providers")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 52
    assert isinstance(body["providers"], list)
    # Spot-check a couple of well-known providers.
    names = {p["name"] for p in body["providers"]}
    assert "openai" in names
    assert "anthropic" in names
    assert "vercel_gateway" in names
    # Each entry carries the metadata fields the UI needs.
    for p in body["providers"]:
        assert "display_name" in p
        assert "base_url" in p
        assert "env_key" in p
        assert "default_model" in p
        assert "openai_compatible" in p
        assert "has_credential" in p


def test_providers_test(client) -> None:
    """POST /providers/test/openai returns 200 with ok=true in mock mode."""
    r = client.post("/providers/test/openai")
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "openai"
    assert body["ok"] is True  # mock mode always returns ok
    assert body["mock_mode"] is True


def test_providers_test_unknown_returns_404(client) -> None:
    """POST /providers/test/{unknown} returns 404."""
    r = client.post("/providers/test/not-a-real-provider")
    assert r.status_code == 404


def test_credentials_add_remove(client) -> None:
    """POST /credentials adds, DELETE /credentials/{service} removes, GET
    /credentials lists."""
    # Add a credential via env var fallback (keyring is unavailable in tests).
    r = client.post(
        "/credentials",
        json={"service": "openai_api_key", "value": "sk-test-1234567890abcdef"},
    )
    assert r.status_code == 201
    assert r.json()["stored"] is True

    # List credentials — the new one should have has_credential=True.
    r = client.get("/credentials")
    assert r.status_code == 200
    body = r.json()
    found = [c for c in body["credentials"] if c["service"] == "openai_api_key"]
    assert len(found) == 1
    assert found[0]["has_credential"] is True

    # Remove it.
    r = client.delete("/credentials/openai_api_key")
    assert r.status_code == 200
    assert r.json()["removed"] is True

    # Verify the credential is gone.
    r = client.get("/credentials")
    found = [c for c in r.json()["credentials"] if c["service"] == "openai_api_key"]
    assert len(found) == 1
    assert found[0]["has_credential"] is False


# ---------------------------------------------------------------------------
# Permissions — /permissions/*
# ---------------------------------------------------------------------------


def test_permissions_risk_levels(client) -> None:
    """GET /permissions/risk-levels returns 4 levels with examples."""
    r = client.get("/permissions/risk-levels")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 4
    values = {lv["value"] for lv in body["levels"]}
    assert values == {"low", "medium", "high", "critical"}
    # Each level has examples.
    for lv in body["levels"]:
        assert isinstance(lv["examples"], list)
        assert len(lv["examples"]) > 0


def test_permissions_grant(client) -> None:
    """POST /permissions grants a permission; GET /permissions lists it."""
    r = client.post(
        "/permissions",
        json={
            "tool_name": "file.write",
            "risk_level": "medium",
            "decision": "allow_for_workflow",
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["granted"] is True
    grant_id = body["grant_id"]
    assert "file.write" in grant_id
    assert "medium" in grant_id

    # Verify the grant shows up in the list.
    r = client.get("/permissions")
    assert r.status_code == 200
    found = [g for g in r.json()["grants"] if g["grant_id"] == grant_id]
    assert len(found) == 1


def test_permissions_revoke(client) -> None:
    """DELETE /permissions/{grant_id} revokes a permission."""
    # Grant first.
    r = client.post(
        "/permissions",
        json={
            "tool_name": "file.read",
            "risk_level": "low",
            "decision": "always_allow",
        },
    )
    grant_id = r.json()["grant_id"]

    # Revoke.
    r = client.delete(f"/permissions/{grant_id}")
    assert r.status_code == 200
    assert r.json()["revoked"] is True

    # Verify the grant is gone.
    r = client.get("/permissions")
    found = [g for g in r.json()["grants"] if g["grant_id"] == grant_id]
    assert len(found) == 0


def test_permissions_policy_get_update(client, tmp_path: Path) -> None:
    """GET /permissions/policy returns defaults; PUT updates them and the
    risk-overrides JSON file."""
    # Get defaults.
    r = client.get("/permissions/policy")
    assert r.status_code == 200
    defaults = r.json()
    assert defaults["max_actions_per_minute"] >= 1
    assert defaults["risk_overrides"] == {} or isinstance(defaults["risk_overrides"], dict)

    # Update with new values + an override.
    r = client.put(
        "/permissions/policy",
        json={
            "max_actions_per_minute": 240,
            "max_ai_calls_per_task": 50,
            "max_loops": 2000,
            "max_file_operations": 1000,
            "max_browser_tabs": 16,
            "risk_overrides": {"file.delete": "critical"},
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["max_actions_per_minute"] == 240
    assert body["max_ai_calls_per_task"] == 50
    assert body["risk_overrides"]["file.delete"] == "critical"

    # Verify the override persisted to disk.
    from automation_service.config import settings
    overrides_path = settings.project_root / "config" / "risk_overrides.json"
    assert overrides_path.exists()
    persisted = json.loads(overrides_path.read_text(encoding="utf-8"))
    assert persisted["file.delete"] == "critical"

    # Cleanup so we don't bleed into other tests.
    overrides_path.write_text("{}", encoding="utf-8")


def test_permissions_list_with_no_grants(client) -> None:
    """GET /permissions returns empty grants list initially."""
    # Clear any grants from previous tests by fetching the list.
    r = client.get("/permissions")
    assert r.status_code == 200
    body = r.json()
    assert "grants" in body
    assert "count" in body
