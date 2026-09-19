"""Vercel serverless function — list AI providers + models.

GET /api/providers → {providers: [{name, base_url, openai_compatible, has_credential}], count}
GET /api/ai/models → {models: [{id, provider, ...}], count}
"""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error


# Minimal provider list (subset of the full 52 — the most useful for a demo)
DEMO_PROVIDERS = [
    {"name": "openai", "display_name": "OpenAI", "openai_compatible": True, "default_model": "gpt-4o-mini"},
    {"name": "anthropic", "display_name": "Anthropic Claude", "openai_compatible": False, "default_model": "claude-3-5-sonnet"},
    {"name": "google", "display_name": "Google Gemini", "openai_compatible": False, "default_model": "gemini-1.5-flash"},
    {"name": "deepseek", "display_name": "DeepSeek", "openai_compatible": True, "default_model": "deepseek-chat"},
    {"name": "mistral", "display_name": "Mistral AI", "openai_compatible": True, "default_model": "mistral-large-latest"},
    {"name": "xai", "display_name": "xAI Grok", "openai_compatible": True, "default_model": "grok-2"},
    {"name": "groq", "display_name": "Groq", "openai_compatible": True, "default_model": "llama-3.3-70b-versatile"},
    {"name": "together", "display_name": "Together AI", "openai_compatible": True, "default_model": "meta/llama-3.1-70b-instruct"},
    {"name": "fireworks", "display_name": "Fireworks AI", "openai_compatible": True, "default_model": "accounts/fireworks/models/llama-v3-70b-instruct"},
    {"name": "perplexity", "display_name": "Perplexity", "openai_compatible": True, "default_model": "llama-3.1-sonar-large-128k-online"},
    {"name": "cohere", "display_name": "Cohere", "openai_compatible": False, "default_model": "command-r-plus"},
    {"name": "meta", "display_name": "Meta Llama", "openai_compatible": True, "default_model": "llama-3.1-70b-instruct"},
    {"name": "vercel_gateway", "display_name": "Vercel AI Gateway (all providers)", "openai_compatible": True, "default_model": "openai/gpt-4o-mini"},
]


def handler(req, res):
    """Vercel Python serverless handler — list providers."""
    gateway_key = os.environ.get("VERCEL_AI_GATEWAY_KEY", "")

    # If we have a gateway key, try to fetch live models
    if gateway_key and req.path and "models" in req.path:
        try:
            request = urllib.request.Request(
                "https://ai-gateway.vercel.sh/v1/models",
                headers={"Authorization": f"Bearer {gateway_key}"},
                method="GET",
            )
            with urllib.request.urlopen(request, timeout=15) as response:
                data = json.loads(response.read().decode("utf-8"))
                models = data.get("data", [])
                res.status_code = 200
                res.headers["Content-Type"] = "application/json"
                res.body = json.dumps({
                    "models": models[:50],
                    "count": len(models),
                    "source": "vercel_gateway",
                })
                return
        except Exception as exc:
            pass  # fall through to demo response

    # Demo / fallback response
    res.status_code = 200
    res.headers["Content-Type"] = "application/json"
    res.body = json.dumps({
        "providers": [
            {**p, "has_credential": bool(gateway_key) if p["name"] == "vercel_gateway" else False}
            for p in DEMO_PROVIDERS
        ],
        "count": len(DEMO_PROVIDERS),
        "demo": not bool(gateway_key),
    })
