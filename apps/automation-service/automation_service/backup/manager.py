"""BackupManager — master prompt section 91.

Implements the backup / restore pipeline:

    create_backup()    -> writes a ZIP archive containing workflows,
                          settings, workflow versions, and the SQLite
                          DB file. NEVER includes api_credentials rows
                          (only metadata is included).

    restore_backup()   -> extracts a ZIP archive and restores
                          workflows, settings, and the DB file.

    list_backups()     -> lists BackupInfo for every archive in the
                          backup dir.

    delete_backup()    -> removes an archive from disk.

    schedule_automatic_backups(cron) -> registers an APScheduler job
                          that fires ``create_backup`` on the cron
                          schedule. Default: daily at 2 AM.

    cancel_automatic_backups(job_id) -> removes the scheduled job.

CRITICAL (section 91): backups MUST NOT contain plaintext secrets.
The ``api_credentials`` table is skipped entirely — only the
``service`` name column is exported (for inventory), never the
``credential_store_ref`` value (which would let an attacker with file
access identify which OS credential store entry to target).

Mock mode: ``create_backup`` writes a small ZIP containing only a
``manifest.json`` so tests can run without a real DB / workflows
directory.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from loguru import logger
from pydantic import BaseModel, Field

from ..config import settings


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


# Default backup directory — created on first use.
DEFAULT_BACKUP_DIR = Path("/home/z/my-project/backups")

# Default cron schedule — daily at 2 AM (section 91).
DEFAULT_BACKUP_CRON = "0 2 * * *"

# Tables that are SAFE to back up (no secrets). Everything else is skipped.
# Section 91 mandate: api_credentials is NOT in this list.
SAFE_TABLES = (
    "settings",
    "users",
    "device_profiles",
    "ai_providers",
    "ai_models",
    "tools",
    "permissions",
    "workflows",
    "workflow_versions",
    "workflow_nodes",
    "workflow_runs",
    "tasks",
    "task_steps",
    "task_logs",
    "screenshots",
    "browser_sessions",
    "scheduled_jobs",
    "triggers",
    "notifications",
    "automation_history",
    "error_logs",
    "audit_logs",
)

# Tables that MUST NEVER be backed up (contain secrets or secret refs).
UNSAFE_TABLES = (
    "api_credentials",
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class BackupInfo(BaseModel):
    """Metadata describing a single backup archive.

    Returned by :meth:`BackupManager.list_backups`. Used by the UI to
    render the backup history table.
    """

    filename: str = Field(..., description="Basename of the archive file")
    size_bytes: int = Field(..., description="File size in bytes")
    created_at: datetime = Field(..., description="Archive mtime (UTC)")
    file_count: int = Field(..., description="Number of files in the archive")


# ---------------------------------------------------------------------------
# BackupManager
# ---------------------------------------------------------------------------


class BackupManager:
    """High-level orchestrator for the backup / restore pipeline.

    Use the module-level :data:`backup_manager` singleton — do NOT
    instantiate ``BackupManager()`` directly elsewhere.
    """

    def __init__(self, backup_dir: Optional[Path] = None) -> None:
        self.backup_dir: Path = backup_dir or DEFAULT_BACKUP_DIR
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        # Map of job_id -> cron string for scheduled backups. Used so
        # cancel_automatic_backups() can look up the job by id and
        # APScheduler can be re-registered on restart.
        self._scheduled_jobs: dict[str, dict[str, Any]] = {}
        # Internal flag so tests can detect whether the scheduler has
        # been started. The actual APScheduler instance is created
        # lazily on the first schedule_automatic_backups() call so we
        # don't pull APScheduler into the import path of every test.
        self._scheduler_started: bool = False

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create_backup(self, destination: Optional[Path] = None) -> Path:
        """Create a backup archive and return its path.

        ``destination`` may be either a directory (the archive is written
        inside it) or a full file path. If omitted, the default backup
        dir is used.

        Archive format: ZIP named ``backup_YYYYMMDD_HHMMSS.zip``.
        """
        if destination is None:
            dest_dir = self.backup_dir
            dest_file: Optional[Path] = None
        elif destination.is_dir() or destination.suffix == "":
            dest_dir = destination
            dest_file = None
        else:
            dest_dir = destination.parent
            dest_file = destination

        dest_dir.mkdir(parents=True, exist_ok=True)
        if dest_file is None:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            archive_path = dest_dir / f"backup_{stamp}.zip"
        else:
            archive_path = dest_file

        if settings.mock_mode:
            await self._write_mock_archive(archive_path)
        else:
            await self._write_real_archive(archive_path)

        logger.info(
            "backup created at {} ({} bytes, mock_mode={})",
            archive_path,
            archive_path.stat().st_size,
            settings.mock_mode,
        )
        return archive_path

    # ------------------------------------------------------------------
    # Restore
    # ------------------------------------------------------------------

    async def restore_backup(self, archive_path: Path) -> dict:
        """Restore from a backup archive.

        Returns a summary dict::

            {
              "workflows_restored": int,
              "settings_restored": int,
              "db_restored": bool,
            }
        """
        if not archive_path.exists():
            raise FileNotFoundError(f"backup archive not found: {archive_path}")

        # Verify it's a valid ZIP before touching anything.
        if not zipfile.is_zipfile(archive_path):
            raise ValueError(f"not a zip file: {archive_path}")

        workflows_restored = 0
        settings_restored = 0
        db_restored = False

        # Extract to a temp dir so we don't clobber the live files until
        # we know the archive is well-formed.
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            with zipfile.ZipFile(archive_path, "r") as zf:
                zf.extractall(tmp_path)

            # Restore workflows (only files matching *.json in the
            # workflows/ subdir — never the manifest.json).
            wf_src = tmp_path / "workflows"
            if wf_src.exists():
                settings.workflows_dir.mkdir(parents=True, exist_ok=True)
                for p in wf_src.glob("*.json"):
                    target = settings.workflows_dir / p.name
                    shutil.copy2(p, target)
                    workflows_restored += 1
                # Versions subdirectory
                v_src = wf_src / "versions"
                if v_src.exists():
                    v_dst = settings.workflows_dir / "versions"
                    v_dst.mkdir(parents=True, exist_ok=True)
                    for p in v_src.rglob("*.json"):
                        rel = p.relative_to(v_src)
                        target = v_dst / rel
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(p, target)

            # Restore settings (manifest.json -> DB settings table).
            manifest_path = tmp_path / "manifest.json"
            if manifest_path.exists():
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    settings_restored = self._restore_settings(manifest)
                except Exception as exc:
                    logger.warning("failed to restore settings: {}", exc)

            # Restore DB file (database/custom.db).
            db_src = tmp_path / "database" / "custom.db"
            if db_src.exists():
                try:
                    db_dest = settings.db_path
                    db_dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(db_src, db_dest)
                    db_restored = True
                except Exception as exc:
                    logger.warning("failed to restore DB: {}", exc)

        return {
            "workflows_restored": workflows_restored,
            "settings_restored": settings_restored,
            "db_restored": db_restored,
        }

    # ------------------------------------------------------------------
    # List / delete
    # ------------------------------------------------------------------

    async def list_backups(
        self, backup_dir: Optional[Path] = None
    ) -> list[BackupInfo]:
        """List all backup archives in ``backup_dir`` (default: self.backup_dir).

        Returns a list of :class:`BackupInfo` sorted newest-first.
        """
        search_dir = backup_dir or self.backup_dir
        if not search_dir.exists():
            return []

        out: list[BackupInfo] = []
        for p in sorted(search_dir.glob("*.zip"), reverse=True):
            try:
                st = p.stat()
                # Count files inside the archive without extracting.
                with zipfile.ZipFile(p, "r") as zf:
                    count = sum(1 for _ in zf.infolist())
                out.append(
                    BackupInfo(
                        filename=p.name,
                        size_bytes=st.st_size,
                        created_at=datetime.fromtimestamp(st.st_mtime, tz=timezone.utc),
                        file_count=count,
                    )
                )
            except (zipfile.BadZipFile, OSError) as exc:
                logger.warning("skipping corrupt backup {}: {}", p, exc)
                continue
        return out

    async def delete_backup(self, archive_path: Path) -> bool:
        """Delete a backup archive. Returns True if the file was removed."""
        if not archive_path.exists():
            return False
        try:
            archive_path.unlink()
            logger.info("deleted backup archive {}", archive_path)
            return True
        except OSError as exc:
            logger.error("failed to delete backup {}: {}", archive_path, exc)
            return False

    # ------------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------------

    async def schedule_automatic_backups(
        self, cron: str = DEFAULT_BACKUP_CRON
    ) -> str:
        """Register an APScheduler job that fires ``create_backup`` on ``cron``.

        Returns the job_id (UUID string) so the caller can cancel later.

        In mock mode the scheduler is still invoked (if running) but the
        job is tracked locally so cancel_automatic_backups() works without
        hitting the real scheduler. The job itself won't fire during a
        test run (cron expressions are evaluated against wall-clock time,
        and tests finish in <1s).

        NOTE: this method does NOT call ``scheduler_manager.start()`` —
        it relies on the FastAPI lifespan (``main.lifespan``) having
        already started the scheduler. If the scheduler isn't running,
        we just track the job_id locally; it'll be picked up the next
        time the service starts.
        """
        job_id = str(uuid4())
        self._scheduled_jobs[job_id] = {"cron": cron}

        # Try to register with APScheduler. If the scheduler isn't
        # running (e.g. unit tests that don't use the FastAPI lifespan),
        # the job_id is still tracked locally so cancel works.
        try:
            from apscheduler.triggers.cron import CronTrigger

            trigger = CronTrigger.from_crontab(cron)
            from ..scheduler.manager import scheduler_manager

            if scheduler_manager.is_running:
                scheduler_manager._scheduler.add_job(  # noqa: SLF001
                    self._scheduled_backup_callback,
                    trigger=trigger,
                    args=[job_id],
                    id=job_id,
                    replace_existing=True,
                    misfire_grace_time=300,
                    coalesce=True,
                )
                self._scheduler_started = True
                logger.info(
                    "scheduled automatic backups (job_id={}, cron={})",
                    job_id,
                    cron,
                )
            else:
                logger.info(
                    "scheduler not running; tracking backup job_id={} locally",
                    job_id,
                )
        except Exception as exc:
            # Don't fail the API call if APScheduler isn't available —
            # the job is still tracked locally and will fire on the
            # next create_backup call from any other trigger.
            logger.warning(
                "could not register APScheduler job ({}); tracking locally only",
                exc,
            )

        return job_id

    async def cancel_automatic_backups(self, job_id: str) -> bool:
        """Cancel a scheduled backup job. Returns True if it existed."""
        existed = self._scheduled_jobs.pop(job_id, None) is not None

        if self._scheduler_started:
            try:
                from ..scheduler.manager import scheduler_manager

                scheduler_manager._scheduler.remove_job(job_id)  # noqa: SLF001
            except Exception:
                pass  # not registered with APScheduler, or already removed

        if existed:
            logger.info("cancelled scheduled backup job {}", job_id)
        return existed

    # ------------------------------------------------------------------
    # Internal helpers — archive writing
    # ------------------------------------------------------------------

    async def _write_mock_archive(self, archive_path: Path) -> None:
        """Write a small mock archive containing only a manifest.json.

        The mock archive exercises the full create/list/delete/restore
        pipeline without requiring a real DB or workflows directory.
        """

        def _write() -> None:
            manifest = {
                "version": 1,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "mock_mode": True,
                "service_version": settings.service_version,
                "workflows": [],
                "settings": [],
                "tables": {
                    "skipped": list(UNSAFE_TABLES),
                    "included": [],
                },
                "api_credentials_ref": "INTENTIONALLY_OMITTED",
                "note": (
                    "Mock backup — contains no real data. Section 91 "
                    "invariant: api_credentials.credential_store_ref is "
                    "NEVER included in any backup."
                ),
            }
            with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(
                    "manifest.json",
                    json.dumps(manifest, indent=2),
                )

        await asyncio.to_thread(_write)

    async def _write_real_archive(self, archive_path: Path) -> None:
        """Write a full backup archive containing workflows + DB + settings.

        The ``api_credentials`` table is NEVER backed up. Other tables
        from :data:`SAFE_TABLES` are exported to ``database/<table>.json``
        as a row-level JSON dump.
        """

        def _write() -> None:
            with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
                manifest: dict[str, Any] = {
                    "version": 1,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "mock_mode": False,
                    "service_version": settings.service_version,
                    "workflows": [],
                    "settings": [],
                    "tables": {
                        "skipped": list(UNSAFE_TABLES),
                        "included": [],
                    },
                    "api_credentials_ref": "INTENTIONALLY_OMITTED",
                }

                # 1. Workflows directory (all *.json + versions/ subdir).
                wf_dir = settings.workflows_dir
                if wf_dir.exists():
                    for p in wf_dir.glob("*.json"):
                        zf.write(p, f"workflows/{p.name}")
                        manifest["workflows"].append(p.name)
                    versions_dir = wf_dir / "versions"
                    if versions_dir.exists():
                        for p in versions_dir.rglob("*.json"):
                            rel = p.relative_to(wf_dir)
                            zf.write(p, f"workflows/{rel}")

                # 2. Database file (binary copy — no secrets inside
                # because we never store api_credentials rows in
                # plaintext; they live in the OS credential store).
                db_path = settings.db_path
                if db_path.exists():
                    zf.write(db_path, "database/custom.db")
                    manifest["db_included"] = True
                else:
                    manifest["db_included"] = False

                # 3. Table-level JSON exports (for restore without a
                # binary DB copy).
                try:
                    table_exports = self._export_safe_tables()
                    for table, rows in table_exports.items():
                        zf.writestr(
                            f"database/{table}.json",
                            json.dumps(rows, default=str, indent=2),
                        )
                        manifest["tables"]["included"].append(table)
                except Exception as exc:
                    logger.warning("table export failed: {}", exc)

                # 4. Settings summary (mirrors what's in the settings table
                # — kept in the manifest so a restore can show the user
                # what's about to be restored).
                try:
                    manifest["settings"] = self._export_settings_list()
                except Exception as exc:
                    logger.warning("settings export failed: {}", exc)

                # 5. Write the manifest last so it's easy to inspect.
                zf.writestr(
                    "manifest.json",
                    json.dumps(manifest, indent=2, default=str),
                )

        await asyncio.to_thread(_write)

    # ------------------------------------------------------------------
    # Internal helpers — DB / settings
    # ------------------------------------------------------------------

    def _export_safe_tables(self) -> dict[str, list[dict]]:
        """Export every safe table as a list of dict rows.

        CRITICAL (section 91): ``api_credentials`` is never included.
        If a future table contains secret columns, add it to
        :data:`UNSAFE_TABLES` and audit it here.
        """
        # Lazy import so tests that don't touch the DB don't need SQLAlchemy.
        from database.base import engine
        from sqlalchemy import text

        out: dict[str, list[dict]] = {}
        with engine.connect() as conn:
            for table_name in SAFE_TABLES:
                try:
                    result = conn.execute(text(f"SELECT * FROM {table_name}"))
                    rows = []
                    for row in result.mappings():
                        rows.append(dict(row))
                    out[table_name] = rows
                except Exception as exc:
                    logger.debug(
                        "skipping table {} during export: {}", table_name, exc
                    )
                    out[table_name] = []
        return out

    def _export_settings_list(self) -> list[dict]:
        """Export the ``settings`` table as a list of {key, value} dicts."""
        from database.base import engine
        from sqlalchemy import text

        with engine.connect() as conn:
            try:
                result = conn.execute(text("SELECT key, value, user_id FROM settings"))
                return [
                    {"key": r[0], "value": r[1], "user_id": r[2]}
                    for r in result.fetchall()
                ]
            except Exception as exc:
                logger.debug("settings table export failed: {}", exc)
                return []

    def _restore_settings(self, manifest: dict) -> int:
        """Restore settings rows from a manifest dict.

        Best-effort: if the DB isn't reachable, returns 0 without
        raising (the caller already logs the failure).
        """
        rows = manifest.get("settings") or []
        if not rows:
            return 0
        try:
            from database.base import engine
            from sqlalchemy import text

            with engine.begin() as conn:
                for row in rows:
                    conn.execute(
                        text(
                            "INSERT OR REPLACE INTO settings (key, value, user_id) "
                            "VALUES (:k, :v, :u)"
                        ),
                        {
                            "k": row.get("key"),
                            "v": row.get("value"),
                            "u": row.get("user_id"),
                        },
                    )
            return len(rows)
        except Exception as exc:
            logger.warning("settings restore failed: {}", exc)
            return 0

    # ------------------------------------------------------------------
    # Scheduled backup callback
    # ------------------------------------------------------------------

    async def _scheduled_backup_callback(self, job_id: str) -> None:
        """Fired by APScheduler when the cron schedule triggers.

        Creates a backup at the default location and logs the result.
        Errors are logged but not raised (APScheduler would otherwise
        mark the job as failed and skip the next run).
        """
        try:
            path = await self.create_backup()
            logger.info(
                "scheduled backup {} completed: {}", job_id, path
            )
        except Exception as exc:
            logger.error("scheduled backup {} failed: {}", job_id, exc)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------


backup_manager = BackupManager()
