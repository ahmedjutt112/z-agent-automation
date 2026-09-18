#!/usr/bin/env python3
"""Standalone health-check script used by Docker HEALTHCHECK.

GETs http://localhost:8765/health and exits:
    0  if the response JSON has status == "ok"
    1  otherwise (network error, non-200 status, unexpected body)

The script is intentionally dependency-free (stdlib only) so it works inside
the slim Python runtime image without installing `httpx` / `requests`. It is
also used by `make health` outside Docker if the service is running on the
host.

Usage:
    python scripts/healthcheck.py
    HEALTH_URL=http://127.0.0.1:8765/health python scripts/healthcheck.py

Exit codes:
    0  — service healthy
    1  — service unhealthy / unreachable
    2  — invalid arguments (should never happen; kept for argparse convention)
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

DEFAULT_URL = "http://localhost:8765/health"
TIMEOUT_SECONDS = 5


def _health_url() -> str:
    """Resolve the health endpoint URL from env or fall back to default."""
    return os.environ.get("HEALTH_URL", DEFAULT_URL).rstrip("/")


def check() -> int:
    """Perform the GET /health request and evaluate the response.

    Returns:
        0 if healthy, 1 otherwise.
    """
    url = _health_url()
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as resp:  # noqa: S310 — localhost only
            status_code = resp.status
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        # Server responded with a non-2xx status — definitely unhealthy.
        sys.stderr.write(f"healthcheck: HTTP {exc.code} from {url}\n")
        return 1
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
        # Network-layer failure — service down or unreachable.
        sys.stderr.write(f"healthcheck: cannot reach {url}: {exc}\n")
        return 1

    if status_code != 200:
        sys.stderr.write(
            f"healthcheck: unexpected status {status_code} from {url}\n"
        )
        return 1

    try:
        payload: Any = json.loads(body)
    except json.JSONDecodeError as exc:
        sys.stderr.write(
            f"healthcheck: response is not valid JSON ({exc}): {body[:200]!r}\n"
        )
        return 1

    if not isinstance(payload, dict):
        sys.stderr.write(
            f"healthcheck: response is not a JSON object: {payload!r}\n"
        )
        return 1

    status = payload.get("status")
    if status != "ok":
        sys.stderr.write(
            f"healthcheck: status != 'ok' (got {status!r}) from {url}\n"
        )
        return 1

    # Healthy — write a tiny summary line for the container log.
    sys.stdout.write(
        f"healthcheck: ok (service={payload.get('service')!r} "
        f"version={payload.get('version')!r} "
        f"mock_mode={payload.get('mock_mode')!r})\n"
    )
    return 0


def main() -> int:
    return check()


if __name__ == "__main__":
    sys.exit(main())
