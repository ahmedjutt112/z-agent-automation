"""Auto-update subsystem — master prompt section 90.

Public API:

* :class:`UpdateInfo`    — pydantic model describing an available update.
* :class:`UpdateManager` — fetch / verify / apply / rollback orchestrator.
* :data:`update_manager` — module-level singleton instance.

Design notes
------------

* Master prompt section 90 mandates that an unsigned update is NEVER
  applied. :meth:`UpdateManager.download_update` and
  :meth:`UpdateManager.apply_update` both re-verify the SHA256 checksum
  and the detached signature before they touch the install path. If
  either verification fails, an exception is raised and the update is
  aborted in place.
* Mock mode (``settings.mock_mode``) is the project-wide safe default.
  In mock mode, ``check_for_updates`` returns a deterministic fake
  :class:`UpdateInfo` after a 1-second sleep (simulating network
  latency) — no real HTTP call is made.
* Real mode hits GitHub's releases API (configurable via
  ``update_url``) and downloads the release asset to a temp dir. The
  download is streamed in 64 KiB chunks so we can call the progress
  callback periodically.
* ``apply_update`` is intentionally a placeholder — for an Electron
  app the actual application happens through ``electron-updater``'s
  ``autoUpdater.quitAndInstall()``. We log the action and, in mock
  mode, no-op. Real mode would spawn the auto-updater process.
* ``rollback_update`` is also a placeholder — it restores the
  previously-snapshotted version from ``<update_dir>/previous/``.
"""

from __future__ import annotations

from .manager import UpdateInfo, UpdateManager, update_manager

__all__ = ["UpdateInfo", "UpdateManager", "update_manager"]
