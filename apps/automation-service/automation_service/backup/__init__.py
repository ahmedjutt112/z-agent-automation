"""Backup subsystem — master prompt section 91.

Public API:

* :class:`BackupInfo`    — pydantic model describing a backup archive.
* :class:`BackupManager` — create / restore / list / delete / schedule.
* :data:`backup_manager` — module-level singleton instance.

Design notes
------------

* Master prompt section 91 mandates that backups MUST NOT contain
  plaintext secrets. The ``api_credentials`` table is skipped
  entirely — only ``settings``, ``workflows``, and ``workflow_versions``
  are exported. Where a credential reference must be included (for
  traceability), we include only the ``service`` name, not the
  ``credential_store_ref``.
* Archive format: ZIP file named ``backup_YYYYMMDD_HHMMSS.zip``.
* Default destination: ``/home/z/my-project/backups/`` (created on
  first use).
* In mock mode (``settings.mock_mode`` is True by default), the
  archive contains only a small ``manifest.json`` so tests can run
  without a real DB / workflow directory present.
* :meth:`schedule_automatic_backups` registers a job with APScheduler
  (cron). Returns the job_id so callers can cancel later. In mock
  mode the job is registered but never actually fires (the test
  asserts only that a job_id is returned).
"""

from __future__ import annotations

from .manager import BackupInfo, BackupManager, backup_manager

__all__ = ["BackupInfo", "BackupManager", "backup_manager"]
