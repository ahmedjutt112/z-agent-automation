"""Tests for the workflow CRUD router — master prompt §20, §21, §34.

All tests run via the shared ``client`` fixture (FastAPI TestClient) in mock
mode. The ``tmp_workflows_dir`` fixture (autouse via conftest) redirects
``settings.workflows_dir`` to a per-test tmp_path so saved files don't leak
into the real workspace.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sample_workflow(
    *,
    wf_id: str = "test-wf-routes",
    name: str = "Routes Test Workflow",
    node_type: str = "screen.capture",
    args: dict | None = None,
) -> dict:
    return {
        "id": wf_id,
        "name": name,
        "version": 1,
        "description": "Created by test_workflow_routes.py",
        "trigger": {"type": "manual", "timezone": "UTC"},
        "nodes": [
            {"id": "start", "type": "start", "args": {}, "next": "n1"},
            {
                "id": "n1",
                "type": node_type,
                "args": args or {},
                "next": "end",
                "timeout_ms": 5000,
            },
            {"id": "end", "type": "end", "args": {}},
        ],
        "variables": {},
        "enabled": True,
    }


# ---------------------------------------------------------------------------
# create / get / list
# ---------------------------------------------------------------------------


def test_create_workflow(client, tmp_workflows_dir: Path) -> None:
    """POST /workflow saves a workflow JSON file under workflows_dir."""
    wf = _sample_workflow()
    r = client.post("/workflow", json=wf)
    assert r.status_code == 200
    body = r.json()
    assert body["saved"] is True
    assert body["id"] == "test-wf-routes"
    assert (tmp_workflows_dir / "test-wf-routes.json").exists()


def test_get_workflow(client, tmp_workflows_dir: Path) -> None:
    """GET /workflow/{id} returns the saved workflow with all fields."""
    wf = _sample_workflow(wf_id="get-wf-1", name="Gettable Workflow")
    client.post("/workflow", json=wf)

    r = client.get("/workflow/get-wf-1")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "get-wf-1"
    assert body["name"] == "Gettable Workflow"
    assert body["version"] == 1
    assert body["enabled"] is True
    assert isinstance(body["nodes"], list)
    assert len(body["nodes"]) == 3
    # Nodes round-trip with their type field
    node_ids = {n["id"] for n in body["nodes"]}
    assert {"start", "n1", "end"} == node_ids


# ---------------------------------------------------------------------------
# update / delete
# ---------------------------------------------------------------------------


def test_update_workflow(client, tmp_workflows_dir: Path) -> None:
    """PUT /workflow/{id} updates name and nodes, bumps version, archives v1."""
    wf = _sample_workflow(wf_id="upd-wf-1", name="Original Name")
    client.post("/workflow", json=wf)

    r = client.put(
        "/workflow/upd-wf-1",
        json={
            "name": "Renamed Workflow",
            "nodes": [
                {"id": "start", "type": "start", "args": {}},
                {"id": "new_step", "type": "keyboard.type", "args": {"text": "hi"}},
                {"id": "end", "type": "end", "args": {}},
            ],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["updated"] is True
    assert body["version"] == 2  # nodes changed -> version bumped

    # Verify the file reflects the new name + nodes.
    fetched = client.get("/workflow/upd-wf-1").json()
    assert fetched["name"] == "Renamed Workflow"
    assert len(fetched["nodes"]) == 3
    assert {n["id"] for n in fetched["nodes"]} == {"start", "new_step", "end"}

    # Verify an archived version was written under versions/{id}/v1.json.
    v1 = tmp_workflows_dir / "versions" / "upd-wf-1" / "v1.json"
    assert v1.exists(), f"expected archived v1 at {v1}"
    archived = json.loads(v1.read_text(encoding="utf-8"))
    assert archived["name"] == "Original Name", "archived v1 must keep original name"


def test_delete_workflow(client, tmp_workflows_dir: Path) -> None:
    """DELETE /workflow/{id} removes the JSON file."""
    wf = _sample_workflow(wf_id="del-wf-1", name="To Delete")
    client.post("/workflow", json=wf)
    assert (tmp_workflows_dir / "del-wf-1.json").exists()

    r = client.delete("/workflow/del-wf-1")
    assert r.status_code == 200
    body = r.json()
    assert body["deleted"] is True
    assert body["id"] == "del-wf-1"
    assert not (tmp_workflows_dir / "del-wf-1.json").exists()


# ---------------------------------------------------------------------------
# duplicate
# ---------------------------------------------------------------------------


def test_duplicate_workflow(client, tmp_workflows_dir: Path) -> None:
    """POST /workflow/{id}/duplicate creates a copy with a new ID."""
    wf = _sample_workflow(wf_id="dup-wf-1", name="Source Workflow")
    client.post("/workflow", json=wf)

    r = client.post("/workflow/dup-wf-1/duplicate")
    assert r.status_code == 200
    body = r.json()
    assert body["source_id"] == "dup-wf-1"
    new_id = body["id"]
    assert new_id != "dup-wf-1"
    # The new id should be prefixed with the source id.
    assert new_id.startswith("dup-wf-1-")
    assert body["duplicated"] is True

    # The duplicated workflow file must exist.
    assert (tmp_workflows_dir / f"{new_id}.json").exists()

    # And the new workflow must load with the same node count + name suffix.
    fetched = client.get(f"/workflow/{new_id}").json()
    assert fetched["name"] == "Source Workflow (Copy)"
    assert len(fetched["nodes"]) == 3
    assert fetched["version"] == 1


# ---------------------------------------------------------------------------
# versions
# ---------------------------------------------------------------------------


def test_list_workflow_versions(client, tmp_workflows_dir: Path) -> None:
    """GET /workflow/{id}/versions returns the version history."""
    wf = _sample_workflow(wf_id="ver-wf-1", name="Versioned Workflow")
    client.post("/workflow", json=wf)

    # No versions yet — empty list.
    r = client.get("/workflow/ver-wf-1/versions")
    assert r.status_code == 200
    assert r.json() == []

    # Update the workflow twice to archive two versions.
    client.put("/workflow/ver-wf-1", json={"name": "v2"})
    client.put("/workflow/ver-wf-1", json={"name": "v3"})

    r = client.get("/workflow/ver-wf-1/versions")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert len(body) == 2
    # Versions should be sorted ascending.
    assert body[0]["version"] == 1
    assert body[1]["version"] == 2
    # Each entry has filename + saved_at + size_bytes.
    for entry in body:
        assert entry["filename"].startswith("v")
        assert entry["filename"].endswith(".json")
        assert entry["size_bytes"] > 0
        assert isinstance(entry["saved_at"], str)


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


def test_run_workflow(client, tmp_workflows_dir: Path) -> None:
    """POST /workflow/{id}/run returns a run_id and running status.

    Mock mode (autouse via conftest) means the WorkflowExecutor walks the
    nodes but every registered tool returns a mock ActionResult — so the run
    never blocks on real I/O.
    """
    wf = _sample_workflow(
        wf_id="run-wf-1",
        name="Runnable Workflow",
        node_type="screen.capture",
        args={"filename": "run_wf_1.png"},
    )
    client.post("/workflow", json=wf)

    r = client.post("/workflow/run-wf-1/run")
    assert r.status_code == 200
    body = r.json()
    assert "run_id" in body
    assert body["run_id"]  # non-empty
    assert body["workflow_id"] == "run-wf-1"
    assert body["status"] == "running"
    assert body["mock_mode"] is True


# ---------------------------------------------------------------------------
# templates
# ---------------------------------------------------------------------------


def test_list_templates(client, tmp_workflows_dir: Path) -> None:
    """GET /workflow/templates returns at least 3 starter templates."""
    r = client.get("/workflow/templates")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert len(body) >= 3
    ids = {t["id"] for t in body}
    # Spot-check the three required starter templates.
    assert "daily_report" in ids
    assert "organize_downloads" in ids
    assert "browser_login" in ids

    for t in body:
        assert "name" in t
        assert "trigger" in t
        assert isinstance(t["node_count"], int) and t["node_count"] > 0
        # The full workflow template is embedded under `template`.
        assert "template" in t
        assert isinstance(t["template"]["nodes"], list)


# ---------------------------------------------------------------------------
# 404 cases
# ---------------------------------------------------------------------------


def test_get_nonexistent_workflow(client, tmp_workflows_dir: Path) -> None:
    """GET /workflow/nonexistent-id returns 404."""
    r = client.get("/workflow/nonexistent-id")
    assert r.status_code == 404


def test_delete_nonexistent_workflow(client, tmp_workflows_dir: Path) -> None:
    """DELETE /workflow/nonexistent-id returns 404."""
    r = client.delete("/workflow/nonexistent-id")
    assert r.status_code == 404
