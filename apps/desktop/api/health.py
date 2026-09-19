"""Vercel serverless function — health check.

GET /api/health → {status, service, version, mock_mode}
"""

from __future__ import annotations

import json


def handler(req, res):
    """Vercel Python serverless handler."""
    res.status_code = 200
    res.headers["Content-Type"] = "application/json"
    res.body = json.dumps({
        "status": "ok",
        "service": "z-agent-automation",
        "version": "0.1.0",
        "mock_mode": True,
        "kill_switch": False,
        "deployed_on": "vercel",
    })
