"""Tests for the system-level subsystems — master prompt sections
47 (tray), 90 (auto-update), 91 (backup).

Test plan
---------

UpdateManager unit tests:
1. ``test_update_manager_check_mock`` — check_for_updates() returns an
   UpdateInfo in mock mode.
2. ``test_update_manager_get_current_version`` — get_current_version()
   returns settings.service_version.
3. ``test_update_manager_verify_update`` — verify_update() returns
   True for a known file + checksum.

BackupManager unit tests:
4. ``test_backup_manager_create_mock`` — create_backup() returns a
   valid ZIP file path.
5. ``test_backup_manager_list_backups`` — list_backups() returns a
   list with >=1 entry after creating one.
6. ``test_backup_manager_delete_backup`` — delete_backup() removes
   the file.
7. ``test_backup_manager_skips_secrets`` — created backup ZIP does
   NOT contain api_credentials data (only metadata).
8. ``test_backup_manager_restore_mock`` — restore_backup() returns
   summary dict.
9. ``test_backup_manager_schedule`` — schedule_automatic_backups()
   returns a job_id.

FastAPI route tests (use the shared `client` fixture from conftest.py):
10. ``test_api_system_version`` — GET /system/version returns 200 +
    version field.
11. ``test_api_system_check_updates`` — GET /system/updates/check
    returns 200.
12. ``test_api_system_create_backup`` — POST /system/backup returns
    200 + archive_path.
13. ``test_api_system_list_backups`` — GET /system/backup/list returns
    200 + list.
14. ``test_api_system_tray_state`` — GET /system/tray/state returns
    200 + state field.

All tests run in mock mode (autouse via conftest.py) — no real HTTP
calls, no real DB writes, no real scheduler firing.
"""
from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# 1-3. UpdateManager unit tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_backup_dir(tmp_path: Path) -> Path:
    """Redirect BackupManager's backup_dir to a tmp path so we don't
    pollute /home/z/my-project/backups/ during tests.

    Restores the original afterwards."""
    from automation_service.backup.manager import backup_manager

    prev = backup_manager.backup_dir
    new = tmp_path / "backups"
    new.mkdir(parents=True, exist_ok=True)
    backup_manager.backup_dir = new
    yield new
    backup_manager.backup_dir = prev


@pytest.mark.asyncio
async def test_update_manager_check_mock() -> None:
    """check_for_updates() returns an UpdateInfo in mock mode."""
    from automation_service.update.manager import update_manager

    info = await update_manager.check_for_updates()
    assert info is not None, "expected a non-None UpdateInfo in mock mode"
    assert info.version == "9.9.9-mock"
    assert info.download_url.startswith("mock://")
    assert len(info.sha256_checksum) == 64  # SHA256 hex
    assert info.signature  # non-empty so signature verification is exercised


def test_update_manager_get_current_version() -> None:
    """get_current_version() returns settings.service_version."""
    from automation_service.config import settings
    from automation_service.update.manager import update_manager

    # The mock check_for_updates bumps current_version on apply; reset
    # so the test is deterministic regardless of test order.
    update_manager.current_version = settings.service_version
    assert update_manager.get_current_version() == settings.service_version


@pytest.mark.asyncio
async def test_update_manager_verify_update(tmp_path: Path) -> None:
    """verify_update() returns True for a known file + matching checksum."""
    from automation_service.update.manager import update_manager

    payload = b"hello world"
    fpath = tmp_path / "test.bin"
    fpath.write_bytes(payload)
    expected = hashlib.sha256(payload).hexdigest()

    ok = await update_manager.verify_update(fpath, expected)
    assert ok is True

    # Wrong checksum -> False
    ok = await update_manager.verify_update(fpath, "0" * 64)
    assert ok is False

    # Missing file -> False
    ok = await update_manager.verify_update(tmp_path / "missing.bin", expected)
    assert ok is False


# ---------------------------------------------------------------------------
# 4-9. BackupManager unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_backup_manager_create_mock(tmp_backup_dir: Path) -> None:
    """create_backup() returns a valid ZIP file path in mock mode."""
    from automation_service.backup.manager import backup_manager

    archive = await backup_manager.create_backup()
    assert archive.exists()
    assert archive.suffix == ".zip"
    assert archive.is_file()
    assert zipfile.is_zipfile(archive)
    # The mock archive contains a manifest.json + (mock mode) only.
    with zipfile.ZipFile(archive, "r") as zf:
        names = zf.namelist()
    assert "manifest.json" in names


@pytest.mark.asyncio
async def test_backup_manager_list_backups(tmp_backup_dir: Path) -> None:
    """list_backups() returns a list with >=1 entry after creating one."""
    from automation_service.backup.manager import backup_manager

    # Start clean — wipe any leftover archives from a previous test.
    for p in tmp_backup_dir.glob("*.zip"):
        p.unlink()

    await backup_manager.create_backup()
    backups = await backup_manager.list_backups()
    assert isinstance(backups, list)
    assert len(backups) >= 1
    # BackupInfo fields are populated.
    info = backups[0]
    assert info.filename.endswith(".zip")
    assert info.size_bytes > 0
    assert info.file_count >= 1


@pytest.mark.asyncio
async def test_backup_manager_delete_backup(tmp_backup_dir: Path) -> None:
    """delete_backup() removes the file."""
    from automation_service.backup.manager import backup_manager

    # Start clean.
    for p in tmp_backup_dir.glob("*.zip"):
        p.unlink()

    archive = await backup_manager.create_backup()
    assert archive.exists()

    ok = await backup_manager.delete_backup(archive)
    assert ok is True
    assert not archive.exists()

    # Deleting again returns False (already gone).
    ok = await backup_manager.delete_backup(archive)
    assert ok is False


@pytest.mark.asyncio
async def test_backup_manager_skips_secrets(tmp_backup_dir: Path) -> None:
    """Created backup ZIP does NOT contain api_credentials data (only metadata).

    CRITICAL invariant (section 91): the api_credentials table is NEVER
    backed up in any form. We verify:
      * No file named ``database/api_credentials.json`` appears in the archive.
      * The manifest's ``tables.skipped`` list includes ``api_credentials``.
      * The manifest's ``api_credentials_ref`` field is set to
        ``INTENTIONALLY_OMITTED``.
    """
    import json

    from automation_service.backup.manager import backup_manager

    archive = await backup_manager.create_backup()
    with zipfile.ZipFile(archive, "r") as zf:
        names = zf.namelist()
        manifest = json.loads(zf.read("manifest.json"))

    # No api_credentials table export.
    assert "database/api_credentials.json" not in names, (
        "api_credentials table leaked into backup archive (section 91 violation)"
    )
    # Manifest explicitly records the skip.
    skipped = manifest.get("tables", {}).get("skipped", [])
    assert "api_credentials" in skipped, (
        "manifest doesn't record api_credentials as skipped"
    )
    # Manifest explicitly records that no credential_store_ref is included.
    assert manifest.get("api_credentials_ref") == "INTENTIONALLY_OMITTED", (
        "manifest leaked api_credentials_ref value (section 91 violation)"
    )


@pytest.mark.asyncio
async def test_backup_manager_restore_mock(tmp_backup_dir: Path) -> None:
    """restore_backup() returns a summary dict (mock mode archive).

    The mock archive contains no real workflows / DB, so the summary
    will show zeros — but the dict shape must be correct.
    """
    from automation_service.backup.manager import backup_manager

    archive = await backup_manager.create_backup()
    summary = await backup_manager.restore_backup(archive)

    assert isinstance(summary, dict)
    assert "workflows_restored" in summary
    assert "settings_restored" in summary
    assert "db_restored" in summary
    assert isinstance(summary["workflows_restored"], int)
    assert isinstance(summary["settings_restored"], int)
    assert isinstance(summary["db_restored"], bool)


@pytest.mark.asyncio
async def test_backup_manager_schedule(tmp_backup_dir: Path) -> None:
    """schedule_automatic_backups() returns a job_id string."""
    from automation_service.backup.manager import backup_manager

    job_id = await backup_manager.schedule_automatic_backups("0 2 * * *")
    assert isinstance(job_id, str)
    assert len(job_id) > 0

    # Cancel cleanup so we don't leak jobs into other tests.
    await backup_manager.cancel_automatic_backups(job_id)


# ---------------------------------------------------------------------------
# 10-14. FastAPI route tests (use the shared `client` fixture from conftest.py)
# ---------------------------------------------------------------------------


def test_api_system_version(client) -> None:
    """GET /system/version returns 200 + {version, git_commit, build_date}."""
    r = client.get("/system/version")
    assert r.status_code == 200
    body = r.json()
    assert "version" in body
    assert "git_commit" in body
    assert "build_date" in body
    assert isinstance(body["version"], str)


def test_api_system_check_updates(client) -> None:
    """GET /system/updates/check returns 200 + update metadata (mock mode)."""
    r = client.get("/system/updates/check")
    assert r.status_code == 200
    body = r.json()
    assert "update" in body
    assert "current_version" in body
    # Mock mode returns a non-None UpdateInfo.
    assert body["update"] is not None
    assert body["update"]["version"] == "9.9.9-mock"


def test_api_system_create_backup(client, tmp_path) -> None:
    """POST /system/backup returns 200 + archive_path + size_bytes."""
    # Redirect backup_manager to a tmp dir so we don't pollute the
    # real /home/z/my-project/backups/ during the API test.
    from automation_service.backup.manager import backup_manager

    prev = backup_manager.backup_dir
    tmp_backup = tmp_path / "backups"
    tmp_backup.mkdir(parents=True, exist_ok=True)
    backup_manager.backup_dir = tmp_backup
    try:
        r = client.post("/system/backup", json={})
        assert r.status_code == 200
        body = r.json()
        assert "archive_path" in body
        assert "size_bytes" in body
        assert "mock_mode" in body
        archive = Path(body["archive_path"])
        assert archive.exists()
        assert archive.suffix == ".zip"
    finally:
        backup_manager.backup_dir = prev


def test_api_system_list_backups(client, tmp_path) -> None:
    """GET /system/backup/list returns 200 + {backups: [...], count: int}."""
    from automation_service.backup.manager import backup_manager

    prev = backup_manager.backup_dir
    tmp_backup = tmp_path / "backups"
    tmp_backup.mkdir(parents=True, exist_ok=True)
    backup_manager.backup_dir = tmp_backup
    try:
        # Create one so the list isn't empty.
        client.post("/system/backup", json={})
        r = client.get("/system/backup/list")
        assert r.status_code == 200
        body = r.json()
        assert "backups" in body
        assert "count" in body
        assert body["count"] >= 1
        assert isinstance(body["backups"], list)
        assert body["backups"][0]["filename"].endswith(".zip")
    finally:
        backup_manager.backup_dir = prev


def test_api_system_tray_state(client) -> None:
    """GET /system/tray/state returns 200 + {state}.

    Default state should be ``idle`` (the module-level _tray_state
    variable). POST can update it.
    """
    # Reset state to a known value first (in case another test left it
    # in a different state).
    client.post("/system/tray/state", json={"state": "idle"})

    r = client.get("/system/tray/state")
    assert r.status_code == 200
    body = r.json()
    assert "state" in body
    assert body["state"] in {"idle", "running", "paused", "error"}

    # Set to running and verify.
    r2 = client.post("/system/tray/state", json={"state": "running"})
    assert r2.status_code == 200
    assert r2.json()["state"] == "running"

    # Invalid state -> 400.
    r3 = client.post("/system/tray/state", json={"state": "bogus"})
    assert r3.status_code == 400

    # Reset for downstream tests.
    client.post("/system/tray/state", json={"state": "idle"})
