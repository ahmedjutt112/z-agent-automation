"""Marketplace + workflow import/export mock-mode tests — master prompt §51 + §52.

These tests exercise the marketplace endpoints AND the workflow import /
export / validate / permissions endpoints added in Task 7-c. They are NOT
marked ``@pytest.mark.integration`` — they run in mock mode with no network
and no real credentials required.

CRITICAL assertions enforced here (master prompt §51 + §52):

- Imported workflows ALWAYS have ``enabled=False`` (never auto-execute).
- Import / install responses include a ``permissions_required`` list.
- The permission scan recognises browser.* node types and surfaces them.
"""

from __future__ import annotations

import json

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sample_workflow_json(
    *,
    wf_id: str = "mp-test-wf",
    name: str = "MP Test Workflow",
    node_types: list[tuple[str, str]] | None = None,
) -> str:
    """Return a JSON-encoded workflow string for use with /workflow/import."""
    if node_types is None:
        node_types = [("browser.navigate", "https://example.com")]
    nodes: list[dict] = [{"id": "start", "type": "start", "args": {}, "next": "n1"}]
    prev = "start"
    for i, (ntype, args_val) in enumerate(node_types):
        nid = f"n{i + 1}"
        if isinstance(args_val, str) and ntype.startswith("browser.navigate"):
            args = {"url": args_val}
        elif isinstance(args_val, str) and ntype.startswith("browser.click"):
            args = {"selector": args_val}
        elif isinstance(args_val, str) and ntype.startswith("browser.type"):
            args = {"selector": "#input", "text": args_val}
        elif isinstance(args_val, str) and ntype.startswith("file."):
            args = {"path": args_val}
        else:
            args = args_val if isinstance(args_val, dict) else {}
        nodes.append({"id": nid, "type": ntype, "args": args, "next": "end"})
        # Update previous node's next pointer.
        if prev == "start":
            nodes[0]["next"] = nid
        prev = nid
    nodes.append({"id": "end", "type": "end", "args": {}})
    wf = {
        "id": wf_id,
        "name": name,
        "version": 1,
        "description": "Created by test_marketplace.py",
        "trigger": {"type": "manual", "timezone": "UTC"},
        "nodes": nodes,
        "variables": {},
        "enabled": True,  # the import endpoint will force this to False
    }
    return json.dumps(wf)


# ---------------------------------------------------------------------------
# Marketplace — list / get / search
# ---------------------------------------------------------------------------


def test_marketplace_list_templates(client) -> None:
    """GET /marketplace/templates returns >= 12 entries (the built-ins)."""
    r = client.get("/marketplace/templates")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert len(body) >= 12, f"expected >= 12 templates, got {len(body)}"
    # Spot-check the required fields are present on every listing.
    for tpl in body:
        assert "id" in tpl
        assert "name" in tpl
        assert "category" in tpl
        assert "permissions_required" in tpl
        assert "risk_level" in tpl
        assert "workflow" in tpl
        assert isinstance(tpl["tags"], list)


def test_marketplace_get_template(client) -> None:
    """GET /marketplace/templates/{id} returns template details."""
    r = client.get("/marketplace/templates/mp_daily_report_generator")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "mp_daily_report_generator"
    assert body["name"] == "Daily Report Generator"
    assert body["category"] == "reporting"
    assert isinstance(body["workflow"], dict)
    assert isinstance(body["workflow"]["nodes"], list)
    assert len(body["workflow"]["nodes"]) > 0


def test_marketplace_get_template_404(client) -> None:
    """GET /marketplace/templates/nonexistent returns 404."""
    r = client.get("/marketplace/templates/nonexistent-template-id")
    assert r.status_code == 404


def test_marketplace_search(client) -> None:
    """GET /marketplace/search?q=report returns matching templates."""
    r = client.get("/marketplace/search?q=report")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    # "report" should match the daily_report_generator template by name.
    assert any(t["id"] == "mp_daily_report_generator" for t in body)


def test_marketplace_categories(client) -> None:
    """GET /marketplace/categories returns 10 categories with template counts."""
    r = client.get("/marketplace/categories")
    assert r.status_code == 200
    body = r.json()
    cats = body["categories"]
    assert isinstance(cats, list)
    assert len(cats) == 10
    cat_slugs = {c["category"] for c in cats}
    expected = {
        "productivity", "developer", "marketing", "data_entry", "reporting",
        "file_management", "browser_automation", "email_automation",
        "excel_automation", "pdf_automation",
    }
    assert cat_slugs == expected
    # Each category has a count >= 0 and the total across categories is >= 12.
    total = sum(c["count"] for c in cats)
    assert total >= 12, f"expected >= 12 total templates, got {total}"


def test_marketplace_featured(client) -> None:
    """GET /marketplace/featured returns 6 templates (the featured ones)."""
    r = client.get("/marketplace/featured")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert len(body) == 6, f"expected 6 featured templates, got {len(body)}"


# ---------------------------------------------------------------------------
# Marketplace — install / uninstall
# ---------------------------------------------------------------------------


def test_marketplace_install(client, tmp_workflows_dir) -> None:
    """POST /marketplace/install/{id} returns installed Workflow with enabled=False."""
    r = client.post("/marketplace/install/mp_daily_report_generator")
    assert r.status_code == 200
    body = r.json()
    assert body["installed"] is True
    assert body["template_id"] == "mp_daily_report_generator"
    wf = body["workflow"]
    assert wf["enabled"] is False, "§51: imported workflows must NEVER auto-execute"
    assert wf["id"].startswith("mp_daily_report_generator-"), \
        "installed workflow id should be prefixed with the template id"
    # The installed workflow should be persisted to disk.
    installed_path = tmp_workflows_dir / f"{wf['id']}.json"
    assert installed_path.exists(), f"expected workflow file at {installed_path}"


def test_marketplace_install_returns_permissions(client) -> None:
    """POST /marketplace/install/{id} response includes permissions_required list."""
    r = client.post("/marketplace/install/mp_browser_login_helper")
    assert r.status_code == 200
    body = r.json()
    assert "permissions_required" in body
    assert isinstance(body["permissions_required"], list)
    # Browser workflow should surface browser.* permissions.
    perms = set(body["permissions_required"])
    assert "browser.navigate" in perms
    assert "browser.click" in perms
    assert "browser.type" in perms


def test_marketplace_uninstall(client, tmp_workflows_dir) -> None:
    """DELETE /marketplace/install/{id} returns {uninstalled: true}."""
    # Install first.
    r = client.post("/marketplace/install/mp_organize_downloads")
    assert r.status_code == 200
    wf_id = r.json()["workflow"]["id"]
    assert (tmp_workflows_dir / f"{wf_id}.json").exists()

    # Uninstall.
    r = client.delete("/marketplace/install/mp_organize_downloads")
    assert r.status_code == 200
    body = r.json()
    assert body["uninstalled"] is True
    assert body["template_id"] == "mp_organize_downloads"
    assert not (tmp_workflows_dir / f"{wf_id}.json").exists()


def test_marketplace_uninstall_404(client) -> None:
    """DELETE /marketplace/install/{id} with no install recorded returns 404."""
    r = client.delete("/marketplace/install/mp_organize_downloads")
    assert r.status_code == 404


def test_marketplace_install_404(client) -> None:
    """POST /marketplace/install/nonexistent returns 404."""
    r = client.post("/marketplace/install/nonexistent-template-id")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Marketplace — rate / submit
# ---------------------------------------------------------------------------


def test_marketplace_rate(client) -> None:
    """POST /marketplace/rate/{id} with rating=5 returns updated rating."""
    r = client.post(
        "/marketplace/rate/mp_daily_report_generator",
        json={"rating": 5},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["template_id"] == "mp_daily_report_generator"
    assert body["rating"] >= 4.0  # the baseline + new 5-star should be high
    assert body["rating_count"] >= 1


def test_marketplace_rate_invalid(client) -> None:
    """POST /marketplace/rate/{id} with rating=10 returns 422 (out of range)."""
    r = client.post(
        "/marketplace/rate/mp_daily_report_generator",
        json={"rating": 10},
    )
    assert r.status_code == 422


def test_marketplace_submit(client) -> None:
    """POST /marketplace/submit creates a new template."""
    workflow = {
        "id": "user-submitted-test-wf",
        "name": "User Submitted Workflow",
        "version": 1,
        "description": "A workflow submitted via the marketplace.",
        "trigger": {"type": "manual", "timezone": "UTC"},
        "nodes": [
            {"id": "start", "type": "start", "args": {}, "next": "n1"},
            {"id": "n1", "type": "browser.navigate", "args": {"url": "https://example.com"}, "next": "end"},
            {"id": "end", "type": "end", "args": {}},
        ],
        "variables": {},
        "enabled": True,
    }
    r = client.post(
        "/marketplace/submit",
        json={
            "workflow": workflow,
            "author": "test-user",
            "category": "browser_automation",
            "tags": ["test", "browser"],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["submitted"] is True
    new_id = body["template_id"]
    assert new_id.startswith("mp_user_")

    # The new template should appear in the listing.
    r = client.get("/marketplace/templates")
    assert new_id in {t["id"] for t in r.json()}

    # And its permissions_required should be populated by the scan.
    r = client.get(f"/marketplace/templates/{new_id}")
    tpl = r.json()
    assert "browser.navigate" in tpl["permissions_required"]


def test_marketplace_submit_invalid_category(client) -> None:
    """POST /marketplace/submit with an unknown category returns 400."""
    workflow = {
        "id": "bad-category-wf",
        "name": "Bad Category",
        "nodes": [{"id": "start", "type": "start", "args": {}}],
        "trigger": {"type": "manual", "timezone": "UTC"},
    }
    r = client.post(
        "/marketplace/submit",
        json={
            "workflow": workflow,
            "author": "test-user",
            "category": "this_is_not_a_real_category",
            "tags": [],
        },
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Workflow import / export / validate / permissions — master prompt §51
# ---------------------------------------------------------------------------


def test_workflow_import_validates_json(client, tmp_workflows_dir) -> None:
    """POST /workflow/import with valid JSON returns {valid: true, permissions_required: [...]}."""
    wf_json = _sample_workflow_json(wf_id="imported-valid-wf")
    r = client.post("/workflow/import", json={"workflow_json": wf_json})
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is True
    assert body["imported"] is True
    assert isinstance(body["permissions_required"], list)
    assert "risk_level" in body
    assert "workflow" in body
    # The workflow should be persisted to disk.
    assert (tmp_workflows_dir / "imported-valid-wf.json").exists()


def test_workflow_import_rejects_invalid_json(client) -> None:
    """POST /workflow/import with malformed JSON returns 422."""
    r = client.post(
        "/workflow/import",
        json={"workflow_json": "{not valid json"},
    )
    assert r.status_code == 422


def test_workflow_import_rejects_schema_violation(client) -> None:
    """POST /workflow/import with JSON that violates the Workflow schema returns 422."""
    # Missing required 'nodes' field.
    bad_wf = json.dumps({"id": "bad", "name": "Bad"})
    r = client.post("/workflow/import", json={"workflow_json": bad_wf})
    assert r.status_code == 422


def test_workflow_import_disables_by_default(client, tmp_workflows_dir) -> None:
    """Imported workflow has enabled=False — master prompt §51."""
    # The sample workflow sets enabled=True in the JSON, but the import
    # endpoint MUST force it to False.
    wf_json = _sample_workflow_json(wf_id="import-disabled-wf")
    r = client.post("/workflow/import", json={"workflow_json": wf_json})
    assert r.status_code == 200
    body = r.json()
    assert body["workflow"]["enabled"] is False, \
        "§51: imported workflows must NEVER auto-execute (enabled must be False)"

    # Verify the persisted file also has enabled=False.
    saved = json.loads((tmp_workflows_dir / "import-disabled-wf.json").read_text())
    assert saved["enabled"] is False


def test_workflow_export(client, tmp_workflows_dir) -> None:
    """GET /workflow/{id}/export returns JSON file with the right headers."""
    wf_json = _sample_workflow_json(wf_id="export-test-wf", name="Export Test")
    client.post("/workflow/import", json={"workflow_json": wf_json})

    r = client.get("/workflow/export-test-wf/export")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/json"
    assert 'attachment; filename="Export_Test.json"' in r.headers["content-disposition"]
    # The body should be valid JSON matching the workflow.
    body = r.json()
    assert body["id"] == "export-test-wf"
    assert body["name"] == "Export Test"


def test_workflow_export_404(client) -> None:
    """GET /workflow/nonexistent/export returns 404."""
    r = client.get("/workflow/nonexistent-id/export")
    assert r.status_code == 404


def test_workflow_validate(client) -> None:
    """POST /workflow/validate returns {valid, errors, permissions_required, risk_level}."""
    wf_json = _sample_workflow_json(wf_id="validate-test-wf")
    r = client.post("/workflow/validate", json={"workflow_json": wf_json})
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is True
    assert body["errors"] == []
    assert "permissions_required" in body
    assert "risk_level" in body


def test_workflow_validate_invalid(client) -> None:
    """POST /workflow/validate with malformed JSON returns {valid: false}."""
    r = client.post(
        "/workflow/validate",
        json={"workflow_json": "not even json"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is False
    assert len(body["errors"]) > 0


def test_workflow_permissions(client, tmp_workflows_dir) -> None:
    """GET /workflow/{id}/permissions returns list of required permissions."""
    wf_json = _sample_workflow_json(
        wf_id="perms-test-wf",
        node_types=[
            ("browser.navigate", "https://example.com"),
            ("browser.click", "button[type=submit]"),
        ],
    )
    client.post("/workflow/import", json={"workflow_json": wf_json})

    r = client.get("/workflow/perms-test-wf/permissions")
    assert r.status_code == 200
    body = r.json()
    assert body["workflow_id"] == "perms-test-wf"
    assert isinstance(body["permissions_required"], list)
    perms = set(body["permissions_required"])
    assert "browser.navigate" in perms
    assert "browser.click" in perms
    assert body["risk_level"] in {"low", "medium", "high", "critical"}


def test_workflow_permissions_404(client) -> None:
    """GET /workflow/nonexistent/permissions returns 404."""
    r = client.get("/workflow/nonexistent-id/permissions")
    assert r.status_code == 404


def test_scan_permissions_for_browser_workflow(client) -> None:
    """A workflow with browser.click nodes returns ["browser.navigate", "browser.click"]
    in permissions_required.

    Master prompt §52 — the scanner must recognise browser.* tool names and
    surface the corresponding permissions.
    """
    wf_json = _sample_workflow_json(
        wf_id="browser-scan-wf",
        node_types=[
            ("browser.navigate", "https://example.com"),
            ("browser.click", "button[type=submit]"),
        ],
    )
    r = client.post("/workflow/validate", json={"workflow_json": wf_json})
    body = r.json()
    perms = set(body["permissions_required"])
    assert "browser.navigate" in perms, \
        f"browser.navigate should be in permissions_required, got {perms}"
    assert "browser.click" in perms, \
        f"browser.click should be in permissions_required, got {perms}"


def test_scan_permissions_for_file_workflow(client) -> None:
    """A workflow with file.* nodes surfaces filesystem.read / filesystem.write."""
    wf_json = _sample_workflow_json(
        wf_id="file-scan-wf",
        node_types=[
            ("file.read", "~/input.txt"),
            ("file.write", "~/output.txt"),
        ],
    )
    r = client.post("/workflow/validate", json={"workflow_json": wf_json})
    body = r.json()
    perms = set(body["permissions_required"])
    assert "filesystem.read" in perms
    assert "filesystem.write" in perms


def test_import_then_export_roundtrip(client, tmp_workflows_dir) -> None:
    """An imported workflow should round-trip through export without losing
    its permissions_required / risk_level annotations."""
    wf_json = _sample_workflow_json(
        wf_id="roundtrip-wf",
        node_types=[("browser.navigate", "https://example.com")],
    )
    client.post("/workflow/import", json={"workflow_json": wf_json})

    r = client.get("/workflow/roundtrip-wf/export")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "roundtrip-wf"
    assert body["enabled"] is False  # §51 — still disabled after export
    # The exported JSON should carry the permissions_required + risk_level
    # that the import endpoint computed.
    assert "permissions_required" in body
    assert "risk_level" in body
