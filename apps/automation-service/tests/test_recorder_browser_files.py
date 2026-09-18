"""Tests for the recorder, browser, and files FastAPI routers — master prompt
§22 (Task Recorder), §16 (Playwright), §18 (file automation), §55 (file security).

All tests run via the shared ``client`` fixture (FastAPI TestClient) in mock
mode. No real mouse / keyboard / browser / filesystem events are fired; the
mock-mode paths in the underlying engines return simulated results.
"""

from __future__ import annotations

from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Recorder — /recorder/*
# ---------------------------------------------------------------------------


def test_recorder_start_stop(client) -> None:
    """POST /recorder/start flips state to recording; /recorder/stop returns
    the finished Recording."""
    # Start
    r = client.post("/recorder/start")
    assert r.status_code == 200
    body = r.json()
    assert body["recording"] is True
    assert body["paused"] is False
    assert body["started_at"] is not None
    assert body["mock_mode"] is True

    # Status
    r = client.get("/recorder/status")
    assert r.status_code == 200
    assert r.json()["recording"] is True

    # Stop
    r = client.post("/recorder/stop")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "stopped"
    assert "recording" in body
    # Mock-mode recorder emits 6 sample events (navigate + 3 key presses +
    # click + file.create).
    events = body["recording"]["events"]
    assert isinstance(events, list)
    assert len(events) >= 4


def test_recorder_pause_resume(client) -> None:
    """POST /recorder/pause flips paused=true; /recorder/resume flips back."""
    client.post("/recorder/start")

    r = client.post("/recorder/pause")
    assert r.status_code == 200
    body = r.json()
    assert body["recording"] is False
    assert body["paused"] is True

    r = client.post("/recorder/resume")
    assert r.status_code == 200
    body = r.json()
    assert body["recording"] is True
    assert body["paused"] is False

    # Cleanup
    client.post("/recorder/stop")


def test_recorder_to_workflow(client) -> None:
    """POST /recorder/to-workflow returns a Workflow built from the recording."""
    client.post("/recorder/start")
    client.post("/recorder/stop")

    r = client.post("/recorder/to-workflow", json={"name": "Test Workflow"})
    assert r.status_code == 200
    body = r.json()
    assert body["events_count"] >= 4
    assert body["mock_mode"] is True
    wf = body["workflow"]
    assert wf["name"] == "Test Workflow"
    assert isinstance(wf["nodes"], list)
    assert len(wf["nodes"]) >= 2  # navigate + type (merged keys) + click + file.write


def test_recorder_delete_event(client) -> None:
    """DELETE /recorder/events/{i} removes an event from the recording."""
    client.post("/recorder/start")
    client.post("/recorder/stop")

    # Fetch events to know the count.
    r = client.get("/recorder/events")
    initial_count = r.json()["count"]
    assert initial_count >= 4

    # Delete the first event.
    r = client.delete("/recorder/events/0")
    assert r.status_code == 200
    body = r.json()
    assert body["remaining"] == initial_count - 1
    assert "removed" in body

    # Verify the count dropped.
    r = client.get("/recorder/events")
    assert r.json()["count"] == initial_count - 1


# ---------------------------------------------------------------------------
# Browser — /browser/*
# ---------------------------------------------------------------------------


def test_browser_list_sessions(client) -> None:
    """GET /browser/sessions returns an empty list initially (mock mode)."""
    r = client.get("/browser/sessions")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["sessions"], list)
    assert body["count"] == 0
    assert body["mock_mode"] is True


def test_browser_create_session(client) -> None:
    """POST /browser/session creates a session record."""
    r = client.post(
        "/browser/session",
        json={"browser": "chromium", "headless": True, "session_id": "test-sess-1"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["session"]["session_id"] == "test-sess-1"
    assert body["mock_mode"] is True

    # Now /browser/sessions should return 1.
    r = client.get("/browser/sessions")
    assert r.json()["count"] == 1


def test_browser_close_session(client) -> None:
    """DELETE /browser/session/{id} closes a session."""
    client.post(
        "/browser/session",
        json={"browser": "firefox", "headless": False, "session_id": "test-sess-2"},
    )

    r = client.delete("/browser/session/test-sess-2")
    assert r.status_code == 200
    body = r.json()
    assert body["closed"] is True

    # And /browser/sessions no longer lists it.
    r = client.get("/browser/sessions")
    assert all(s["session_id"] != "test-sess-2" for s in r.json()["sessions"])


def test_browser_navigate_uses_tool_registry(client) -> None:
    """POST /browser/session/{id}/navigate delegates to browser.navigate tool."""
    client.post(
        "/browser/session",
        json={"session_id": "nav-sess", "browser": "chromium"},
    )

    r = client.post(
        "/browser/session/nav-sess/navigate",
        json={"url": "https://example.com"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["url"] == "https://example.com"
    # Mock mode — the tool returned simulated=True.
    assert body["mock_mode"] is True


# ---------------------------------------------------------------------------
# Files — /files/*
# ---------------------------------------------------------------------------


def _project_root() -> Path:
    """Return the project root used by the automation service."""
    from automation_service.config import settings
    return settings.project_root


def test_files_list(client) -> None:
    """GET /files/list?path=... returns entries from a directory."""
    # The project download dir is in the allowlist.
    p = _project_root() / "download"
    r = client.get("/files/list", params={"path": str(p)})
    assert r.status_code == 200
    body = r.json()
    assert body["path"] == str(p)
    assert isinstance(body["entries"], list)


def test_files_read(client, tmp_path: Path) -> None:
    """GET /files/read?path=... returns file contents."""
    # Use a tmp dir under the project download root so _validate_path passes.
    from automation_service.config import settings

    target_dir = settings.project_root / "download" / "test_files_read"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_file = target_dir / "sample.txt"
    target_file.write_text("hello world", encoding="utf-8")

    try:
        r = client.get("/files/read", params={"path": str(target_file)})
        assert r.status_code == 200
        body = r.json()
        assert body["text"] == "hello world"
        assert body["size"] == 11
    finally:
        target_file.unlink()
        target_dir.rmdir()


def test_files_write(client) -> None:
    """POST /files/write creates a file under an allowed root."""
    from automation_service.config import settings

    target = settings.project_root / "download" / "test_files_write.txt"
    payload = "hello from test"
    try:
        r = client.post(
            "/files/write",
            json={"path": str(target), "content": payload},
        )
        assert r.status_code == 201
        body = r.json()
        assert body["size"] == len(payload)
        assert target.read_text() == payload
    finally:
        if target.exists():
            target.unlink()


def test_files_move(client) -> None:
    """POST /files/move moves a file from source to destination."""
    from automation_service.config import settings

    src = settings.project_root / "download" / "test_files_move_src.txt"
    dst = settings.project_root / "download" / "test_files_move_dst.txt"
    src.write_text("payload", encoding="utf-8")
    try:
        r = client.post(
            "/files/move",
            json={"source": str(src), "destination": str(dst)},
        )
        assert r.status_code == 200
        assert not src.exists()
        assert dst.read_text() == "payload"
    finally:
        for p in (src, dst):
            if p.exists():
                p.unlink()


def test_files_copy(client) -> None:
    """POST /files/copy duplicates a file."""
    from automation_service.config import settings

    src = settings.project_root / "download" / "test_files_copy_src.txt"
    dst = settings.project_root / "download" / "test_files_copy_dst.txt"
    src.write_text("copy me", encoding="utf-8")
    try:
        r = client.post(
            "/files/copy",
            json={"source": str(src), "destination": str(dst)},
        )
        assert r.status_code == 201
        assert src.exists()  # source preserved
        assert dst.read_text() == "copy me"
    finally:
        for p in (src, dst):
            if p.exists():
                p.unlink()


def test_files_delete_requires_approval(client) -> None:
    """POST /files/delete is CRITICAL risk — refuses without approved=true."""
    from automation_service.config import settings

    target = settings.project_root / "download" / "test_files_delete.txt"
    target.write_text("doomed", encoding="utf-8")
    try:
        # First attempt without approval — should return 403.
        r = client.post("/files/delete", json={"path": str(target), "approved": False})
        assert r.status_code == 403
        assert target.exists()  # still there

        # Second attempt WITH approval — should succeed.
        r = client.post("/files/delete", json={"path": str(target), "approved": True})
        assert r.status_code == 200
        assert r.json()["deleted"] is True
        assert not target.exists()
    finally:
        if target.exists():
            target.unlink()


def test_files_blocked_path(client) -> None:
    """GET /files/list?path=/etc returns 403 (master prompt §55)."""
    r = client.get("/files/list", params={"path": "/etc"})
    assert r.status_code == 403


def test_files_download(client) -> None:
    """GET /files/download?path=... returns the file bytes."""
    from automation_service.config import settings

    target = settings.project_root / "download" / "test_files_download.txt"
    target.write_text("binary payload", encoding="utf-8")
    try:
        r = client.get("/files/download", params={"path": str(target)})
        assert r.status_code == 200
        assert r.content == b"binary payload"
        assert "attachment" in r.headers.get("content-disposition", "")
    finally:
        if target.exists():
            target.unlink()
