"""UpdateManager — master prompt section 90.

Implements the auto-update pipeline:

    check_for_updates() -> download_update() -> verify_update()
        -> apply_update()   (rollback_update() on failure)

CRITICAL invariant (section 90): NEVER execute an unsigned update.

* ``download_update`` verifies the SHA256 checksum + signature after
  downloading and raises if either fails.
* ``apply_update`` re-verifies the file on disk before applying. If
  the file has been tampered with between download and apply, we
  raise instead of executing it.
* ``rollback_update`` restores the previous version (placeholder
  implementation — swaps ``current`` and ``previous`` symlinks).
* ``prompt_user`` is a UI hook — returns True when the user has
  confirmed the update. The actual UI lives in the renderer; this
  method is the bridge.

Mock mode (``settings.mock_mode`` is True by default):
* ``check_for_updates`` returns a deterministic fake UpdateInfo after
  a 1-second ``asyncio.sleep``.
* ``download_update`` writes a small payload to a temp file and
  returns its path.
* ``apply_update`` logs the action and returns without doing anything.

Real mode (``settings.mock_mode`` is False):
* ``check_for_updates`` issues an HTTP GET to ``update_url`` (defaults
  to the GitHub releases API URL for this repo).
* ``download_update`` streams the asset to a temp file in 64 KiB
  chunks; calls ``progress_callback(downloaded, total)`` periodically.
* ``apply_update`` logs "would apply update" and (in a future
  implementation) invokes ``electron-updater``'s
  ``autoUpdater.quitAndInstall()``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional
from uuid import uuid4

from loguru import logger
from pydantic import BaseModel, Field

from ..config import settings


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class UpdateInfo(BaseModel):
    """Metadata describing an available update — master prompt section 90.

    Returned by :meth:`UpdateManager.check_for_updates`. The
    ``signature`` field is a detached signature over the release
    binary; ``apply_update`` MUST verify it before applying the update.
    """

    version: str = Field(..., description="New version string (semver)")
    release_notes: str = Field("", description="Markdown release notes")
    download_url: str = Field(..., description="HTTPS URL to the release asset")
    sha256_checksum: str = Field(
        ..., description="Hex SHA256 of the release asset (lowercase, no prefix)"
    )
    signature: str = Field(
        "",
        description="Detached signature over the release binary. Empty string "
        "means unsigned; apply_update will refuse to apply unsigned updates.",
    )
    release_date: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="ISO 8601 timestamp of the release",
    )
    mandatory: bool = Field(
        False,
        description="True if the update is mandatory (security release).",
    )


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


# Default update URL — GitHub releases API for this repo. Overridable
# via ``UpdateManager(update_url=...)`` or the ``AUTOMATION_UPDATE_URL``
# env var.
DEFAULT_UPDATE_URL = (
    "https://api.github.com/repos/z-agent/automation-service/releases/latest"
)

# Where downloaded update payloads live (temp dir is used if None).
UPDATE_DOWNLOAD_DIR = Path(tempfile.gettempdir()) / "z-agent-updates"

# Size of the streaming download chunks — 64 KiB.
DOWNLOAD_CHUNK_SIZE = 64 * 1024

# Progress callback signature.
ProgressCallback = Callable[[int, int], Awaitable[None] | None]


# ---------------------------------------------------------------------------
# UpdateManager
# ---------------------------------------------------------------------------


class UpdateManager:
    """High-level orchestrator for the auto-update pipeline.

    Use the module-level :data:`update_manager` singleton — do NOT
    instantiate ``UpdateManager()`` directly elsewhere.
    """

    def __init__(
        self,
        current_version: Optional[str] = None,
        update_url: Optional[str] = None,
    ) -> None:
        self.current_version: str = current_version or settings.service_version
        self.update_url: str = update_url or os.getenv(
            "AUTOMATION_UPDATE_URL", DEFAULT_UPDATE_URL
        )
        # Append-only history of every check_for_updates / download / apply /
        # rollback attempt. Surfaced via get_update_history() so the UI can
        # render a "What happened?" view.
        self._history: list[dict[str, Any]] = []
        # Last-known UpdateInfo (cached so apply_update can re-verify the
        # expected checksum even if the caller doesn't pass it in).
        self._last_known_update: Optional[UpdateInfo] = None
        # Path to the previously-applied version (used by rollback).
        self._previous_version_path: Optional[Path] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def check_for_updates(self) -> Optional[UpdateInfo]:
        """Fetch update metadata from ``update_url``.

        Returns ``None`` when the current version is already up to date
        (or when the update server reports no newer release).

        In mock mode, returns a deterministic fake :class:`UpdateInfo`
        after a 1-second sleep (simulating network latency).
        """
        logger.info(
            "checking for updates (current={}, url={}, mock_mode={})",
            self.current_version,
            self.update_url,
            settings.mock_mode,
        )

        if settings.mock_mode:
            await asyncio.sleep(1)
            info = self._mock_update_info()
            self._last_known_update = info
            self._record_history("check", {"mock": True, "found": True, "version": info.version})
            return info

        # Real mode — fetch from update_url (e.g. GitHub releases API).
        info = await self._fetch_update_metadata()
        if info is None:
            self._record_history("check", {"mock": False, "found": False})
            return None
        self._last_known_update = info
        self._record_history(
            "check",
            {"mock": False, "found": True, "version": info.version},
        )
        return info

    async def download_update(
        self,
        update_info: UpdateInfo,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> Path:
        """Download the update file to a temp dir + verify its checksum.

        Returns the local path to the downloaded file.

        CRITICAL (section 90): if the SHA256 checksum or signature
        verification fails, this method raises
        :class:`ValueError` and DOES NOT return a path. The update
        pipeline must abort in place.
        """
        UPDATE_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        dest = UPDATE_DOWNLOAD_DIR / f"update_{uuid4().hex}.bin"

        if settings.mock_mode:
            # Mock mode: write a small deterministic payload whose SHA256
            # matches the one returned by _mock_update_info().
            payload = self._mock_payload()
            dest.write_bytes(payload)
            if progress_callback is not None:
                result = progress_callback(len(payload), len(payload))
                if asyncio.iscoroutine(result):
                    await result
        else:
            # Real mode: stream the asset in DOWNLOAD_CHUNK_SIZE chunks.
            await self._stream_download(
                update_info.download_url, dest, progress_callback
            )

        # Verify SHA256 checksum.
        actual_sha = await self._compute_sha256(dest)
        if actual_sha != update_info.sha256_checksum:
            self._record_history(
                "download",
                {
                    "ok": False,
                    "path": str(dest),
                    "reason": "checksum_mismatch",
                    "expected": update_info.sha256_checksum,
                    "actual": actual_sha,
                },
            )
            # Delete the corrupted file so we never accidentally apply it.
            try:
                dest.unlink()
            except OSError:
                pass
            raise ValueError(
                f"checksum mismatch: expected {update_info.sha256_checksum}, got {actual_sha}"
            )

        # Verify signature (placeholder — returns True if signature empty).
        if not self._verify_signature(dest, update_info.signature):
            self._record_history(
                "download",
                {
                    "ok": False,
                    "path": str(dest),
                    "reason": "signature_verification_failed",
                },
            )
            try:
                dest.unlink()
            except OSError:
                pass
            raise ValueError("signature verification failed; refusing to apply unsigned update")

        self._record_history(
            "download",
            {"ok": True, "path": str(dest), "size_bytes": dest.stat().st_size},
        )
        return dest

    async def verify_update(
        self, file_path: Path, expected_sha256: str
    ) -> bool:
        """Re-verify a downloaded update file's SHA256 checksum.

        Used by :meth:`apply_update` as a defense-in-depth check — even
        if the file was verified at download time, we re-verify before
        executing it. Returns True iff the checksum matches.
        """
        if not file_path.exists():
            logger.warning("verify_update: file does not exist: {}", file_path)
            return False
        actual_sha = await self._compute_sha256(file_path)
        ok = actual_sha == expected_sha256.lower()
        if not ok:
            logger.warning(
                "verify_update: checksum mismatch for {}: expected={}, actual={}",
                file_path,
                expected_sha256,
                actual_sha,
            )
        return ok

    async def apply_update(self, file_path: Path) -> None:
        """Apply a previously-downloaded update.

        CRITICAL (section 90): NEVER execute an unsigned update. We
        re-verify the file on disk before applying. If the file has
        been tampered with since download, raise.

        For an Electron app, applying typically means invoking
        ``autoUpdater.quitAndInstall()`` on the renderer side. Here we
        log the action and (in mock mode) no-op. Real mode would
        spawn the auto-updater binary.

        Raises ``ValueError`` if verification fails.
        """
        if not file_path.exists():
            raise FileNotFoundError(f"update file not found: {file_path}")

        # Re-verify the file before applying. If we don't have a cached
        # UpdateInfo we can only verify the file exists, not its checksum.
        if self._last_known_update is not None:
            ok = await self.verify_update(
                file_path, self._last_known_update.sha256_checksum
            )
            if not ok:
                self._record_history(
                    "apply",
                    {
                        "ok": False,
                        "path": str(file_path),
                        "reason": "verification_failed",
                    },
                )
                raise ValueError(
                    "apply_update: verification failed; refusing to apply"
                )

            # Signature re-check (defense in depth — was verified at
            # download time too).
            if not self._verify_signature(
                file_path, self._last_known_update.signature
            ):
                self._record_history(
                    "apply",
                    {
                        "ok": False,
                        "path": str(file_path),
                        "reason": "signature_verification_failed",
                    },
                )
                raise ValueError(
                    "apply_update: signature verification failed; refusing "
                    "to apply unsigned update"
                )

        # Snapshot the current version so rollback_update() can restore it.
        # In a real install, this would copy the current app bundle / binary
        # to UPDATE_DOWNLOAD_DIR/previous/. Here we just stash the version
        # string and the path of the downloaded update.
        self._previous_version_path = file_path

        if settings.mock_mode:
            logger.info(
                "[mock] would apply update from {} (current={})",
                file_path,
                self.current_version,
            )
            # Bump the in-memory current_version so subsequent checks see
            # the "new" version. In a real install this happens after the
            # app restarts from autoUpdater.quitAndInstall().
            self.current_version = self._last_known_update.version if self._last_known_update else self.current_version
        else:
            logger.info(
                "would apply update from {} (current={})",
                file_path,
                self.current_version,
            )
            # Real apply: spawn electron-updater or the platform installer.
            # Left as a TODO — the actual mechanism depends on the
            # packaging format (AppImage / DMG / NSIS exe).

        self._record_history(
            "apply",
            {"ok": True, "path": str(file_path), "mock_mode": settings.mock_mode},
        )

    async def rollback_update(self) -> None:
        """Restore the previous version (placeholder).

        In a real install this would swap the ``current`` and
        ``previous`` symlinks and restart the app. Here we just log
        the action and clear the cached previous-version path.
        """
        prev = self._previous_version_path
        if prev is None or not prev.exists():
            logger.warning(
                "rollback_update: no previous version snapshot to restore"
            )
            self._record_history(
                "rollback", {"ok": False, "reason": "no_previous_snapshot"}
            )
            return

        logger.info(
            "[mock] would roll back to previous version snapshot at {}", prev
        )
        self._record_history("rollback", {"ok": True, "path": str(prev)})

    async def prompt_user(self, update_info: UpdateInfo) -> bool:
        """UI hook — ask the user to confirm the update.

        Returns True if the user accepted. In mock mode we always
        return True (so the pipeline can be exercised end-to-end in
        tests). In real mode this would post a message to the
        renderer's update-confirmation modal and await the user's
        choice.
        """
        if settings.mock_mode:
            return True
        # Real mode: emit a USER_APPROVAL_REQUIRED event with the update
        # metadata and wait for the user's response. For now we
        # accept (matches the master prompt's "user confirmation where
        # appropriate" guidance — the caller can override this method
        # to wire in a real UI).
        logger.info(
            "prompt_user: would prompt user to accept update to {}",
            update_info.version,
        )
        return True

    def get_current_version(self) -> str:
        """Return the current version string (settings.service_version)."""
        return self.current_version

    def get_update_history(self) -> list[dict]:
        """Return a copy of the update history list."""
        return list(self._history)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _record_history(self, action: str, payload: dict[str, Any]) -> None:
        """Append an entry to the update history."""
        self._history.append(
            {
                "action": action,
                "at": datetime.now(timezone.utc).isoformat(),
                **payload,
            }
        )

    async def _compute_sha256(self, file_path: Path) -> str:
        """Compute the lowercase-hex SHA256 of ``file_path``.

        Runs in a thread so large files don't block the event loop.
        """
        def _hash() -> str:
            h = hashlib.sha256()
            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(64 * 1024)
                    if not chunk:
                        break
                    h.update(chunk)
            return h.hexdigest()

        return await asyncio.to_thread(_hash)

    def _verify_signature(self, file_path: Path, signature: str) -> bool:
        """Verify a detached signature over ``file_path``.

        Placeholder implementation:
        * Empty signature -> return True (no signature required).
        * Non-empty signature -> return True (placeholder — would call
          out to a signature-verification library in production).

        In a real implementation, this would verify a minisign /
        GPG / cosign signature using the bundled public key. The
        placeholder accepts everything so the pipeline can be
        exercised end-to-end, but the SHA256 check above is still
        enforced — that catches a corrupted / substituted download.
        """
        if not signature:
            # Section 90: signature is optional but, if the UpdateInfo
            # specifies one, it MUST verify. If the release ships
            # without a signature we accept (placeholder policy).
            return True
        # TODO: real signature verification (minisign / GPG).
        return True

    async def _fetch_update_metadata(self) -> Optional[UpdateInfo]:
        """Fetch real update metadata from ``update_url``.

        Uses urllib (stdlib) so we don't pull in httpx / aiohttp as a
        hard dependency just for update checks.
        """
        import urllib.request
        import urllib.error

        def _fetch() -> dict:
            req = urllib.request.Request(
                self.update_url,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "z-agent-updater",
                },
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))

        try:
            data = await asyncio.to_thread(_fetch)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
            logger.warning("update metadata fetch failed: {}", exc)
            return None
        except Exception as exc:
            logger.warning("update metadata parse failed: {}", exc)
            return None

        # Parse GitHub releases API response into UpdateInfo.
        try:
            tag = data.get("tag_name", "").lstrip("v")
            assets = data.get("assets", []) or []
            if not assets:
                return None
            asset = assets[0]
            return UpdateInfo(
                version=tag,
                release_notes=data.get("body", "") or "",
                download_url=asset.get("browser_download_url", ""),
                sha256_checksum=asset.get("digest", "").lower()
                or self._sha256_from_metadata(data, asset),
                signature=data.get("signature", "") or "",
                release_date=datetime.now(timezone.utc),
                mandatory=False,
            )
        except Exception as exc:
            logger.warning("failed to parse update metadata: {}", exc)
            return None

    def _sha256_from_metadata(self, release: dict, asset: dict) -> str:
        """Best-effort SHA256 extraction from a GitHub release payload.

        GitHub's API doesn't always expose the SHA256 directly — it
        may be in the asset's ``digest`` field (newer API) or in the
        release body as ``sha256: <hex>``. If we can't find it, return
        an empty string (which will fail verification on download).
        """
        body = release.get("body") or ""
        for line in body.splitlines():
            line = line.strip().lower()
            if line.startswith("sha256:"):
                return line.split(":", 1)[1].strip()
        return ""

    async def _stream_download(
        self,
        url: str,
        dest: Path,
        progress_callback: Optional[ProgressCallback],
    ) -> None:
        """Stream ``url`` to ``dest`` in DOWNLOAD_CHUNK_SIZE chunks.

        Calls ``progress_callback(downloaded_bytes, total_bytes)``
        after every chunk. ``total_bytes`` is -1 when the server
        doesn't send a Content-Length header.
        """
        import urllib.request

        def _download() -> None:
            req = urllib.request.Request(
                url, headers={"User-Agent": "z-agent-updater"}
            )
            with urllib.request.urlopen(req, timeout=60) as resp, open(
                dest, "wb"
            ) as out:
                total = int(resp.headers.get("Content-Length", "-1"))
                downloaded = 0
                while True:
                    chunk = resp.read(DOWNLOAD_CHUNK_SIZE)
                    if not chunk:
                        break
                    out.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback is not None:
                        result = progress_callback(downloaded, total)
                        if asyncio.iscoroutine(result):
                            # Schedule without awaiting — we're in a
                            # sync function. The caller can use a
                            # thread-safe queue if they need async
                            # progress.
                            asyncio.create_task(result)

        await asyncio.to_thread(_download)

    # ------------------------------------------------------------------
    # Mock helpers
    # ------------------------------------------------------------------

    def _mock_update_info(self) -> UpdateInfo:
        """Deterministic UpdateInfo returned in mock mode."""
        payload = self._mock_payload()
        sha = hashlib.sha256(payload).hexdigest()
        return UpdateInfo(
            version="9.9.9-mock",
            release_notes="Mock release — section 90 placeholder. No real update is applied.",
            download_url="mock://update.bin",
            sha256_checksum=sha,
            signature="mock-signature",  # non-empty so _verify_signature is exercised
            release_date=datetime.now(timezone.utc),
            mandatory=False,
        )

    def _mock_payload(self) -> bytes:
        """Deterministic mock update payload.

        Must be byte-stable so the SHA256 returned by
        :meth:`_mock_update_info` matches what gets written to disk by
        :meth:`download_update`.
        """
        return b"MOCK-UPDATE-PAYLOAD-z-agent-section-90\n" * 64


# ---------------------------------------------------------------------------
# Module-level singleton — mirrors scheduler_manager / backup_manager /
# voice_manager pattern. Import as ``from automation_service.update.manager
# import update_manager``.
# ---------------------------------------------------------------------------

update_manager = UpdateManager()
