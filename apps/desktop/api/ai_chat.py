"""Vercel serverless function — AI chat via Vercel AI Gateway.

POST /api/ai/chat
body: {messages: [{role, content}], model?, provider?, temperature?, max_tokens?}
→ {content, model, usage}

Routes to any of 50+ providers via the single Vercel AI Gateway API key.
"""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error


GATEWAY_URL = os.environ.get("VERCEL_AI_GATEWAY_URL", "https://ai-gateway.vercel.sh/v1")
GATEWAY_KEY = os.environ.get("VERCEL_AI_GATEWAY_KEY", "")


def handler(req, res):
    """Vercel Python serverless handler."""
    # Parse request body
    try:
        body = json.loads(req.body.decode("utf-8") if isinstance(req.body, bytes) else (req.body or "{}"))
    except Exception as exc:
        res.status_code = 400
        res.headers["Content-Type"] = "application/json"
        res.body = json.dumps({"error": f"Invalid JSON: {exc}"})
        return

    messages = body.get("messages", [])
    if not messages:
        res.status_code = 400
        res.headers["Content-Type"] = "application/json"
        res.body = json.dumps({"error": "messages required"})
        return

    model = body.get("model", "openai/gpt-4o-mini")
    temperature = float(body.get("temperature", 0.7))
    max_tokens = int(body.get("max_tokens", 1000))

    # Call Vercel AI Gateway
    if not GATEWAY_KEY:
        # Demo mode — return a fake response
        res.status_code = 200
        res.headers["Content-Type"] = "application/json"
        res.body = json.dumps({
            "content": f"[Demo mode — no VERCEL_AI_GATEWAY_KEY set] You said: {messages[-1].get('content', '')[:200]}",
            "model": model,
            "usage": {"total_tokens": 0},
            "demo": True,
        })
        return

    payload = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode("utf-8")

    request = urllib.request.Request(
        f"{GATEWAY_URL}/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {GATEWAY_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
            res.status_code = 200
            res.headers["Content-Type"] = "application/json"
            res.body = json.dumps({
                "content": data.get("choices", [{}])[0].get("message", {}).get("content", ""),
                "model": data.get("model", model),
                "usage": data.get("usage", {}),
                "demo": False,
            })
    except urllib.error.HTTPError as exc:
        res.status_code = exc.code
        res.headers["Content-Type"] = "application/json"
        res.body = json.dumps({
            "error": f"AI Gateway error: {exc.reason}",
            "details": exc.read().decode("utf-8", errors="replace")[:500],
        })
    except Exception as exc:
        res.status_code = 500
        res.headers["Content-Type"] = "application/json"
        res.body = json.dumps({"error": str(exc)})
