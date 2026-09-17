"""Model sync — query each provider's /v1/models endpoint and upsert into ai_models.

The master prompt §6 (expanded scope) requires supporting 50+ AI providers.
Each OpenAI-compatible provider exposes a ``GET {base_url}/models`` endpoint;
this module iterates over every entry in ``registry.PROVIDERS``, calls
``list_models()`` on each, and upserts the results into the ``ai_models``
SQLAlchemy table (database/models/schema.py::AIModel).

Behaviour:
- Skips providers without a credential (returns count=0 in the result dict).
- One provider failure does NOT stop the sync — failures are logged and
  the loop continues.
- Uses batch commits (every ``BATCH_SIZE`` models) to avoid holding a long
  transaction open during large syncs.
- In mock mode (``AUTOMATION_MOCK_MODE=true``), providers still need a
  credential before their list_models() is called, so a fresh test
  environment with no credentials yields ``{provider: 0}`` for every entry.
- The Vercel AI Gateway is treated as a special case: it's called once and
  aggregates all upstream providers.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Optional

from loguru import logger


# How many AIModel rows to accumulate before committing.
BATCH_SIZE = 50


def _ensure_automation_root_on_path() -> None:
    """Make ``automation_service.*`` and the top-level ``ai_providers``
    package importable regardless of how this module was loaded."""
    automation_root = str(Path(__file__).resolve().parents[3])
    if automation_root not in sys.path:
        sys.path.insert(0, automation_root)


_ensure_automation_root_on_path()


# Now safe to import everything.
from ai_providers import registry as provider_registry  # type: ignore  # noqa: E402

from automation_service.ai_providers.base import (  # noqa: E402
    AIProviderConfig,
    get_provider,
)


# ---------------------------------------------------------------------------
# Upsert helpers
# ---------------------------------------------------------------------------


def _get_or_create_provider_row(session, name: str, info: dict) -> Any:
    """Get or create an ai_providers row for ``name``."""
    from database.models.schema import AIProvider as AIProviderRow

    row = session.query(AIProviderRow).filter_by(name=name).first()
    if row is not None:
        return row

    row = AIProviderRow(
        name=name,
        provider_type=name,
        base_url=info.get("base_url"),
        enabled=True,
        is_default=False,
        capabilities={
            "vision": False,
            "reasoning": False,
            "openai_compatible": info.get("openai_compatible", False),
        },
    )
    session.add(row)
    session.flush()  # populate row.id
    return row


def _upsert_model_row(session, provider_row, model_info: dict) -> bool:
    """Insert-or-update an ai_models row. Returns True if a row was written."""
    from database.models.schema import AIModel

    model_id = model_info.get("id") or ""
    if not model_id:
        return False

    existing = (
        session.query(AIModel)
        .filter_by(provider_id=provider_row.id, model_id=model_id)
        .first()
    )
    if existing is not None:
        # Update mutable fields only if they changed.
        changed = False
        new_name = model_info.get("display_name") or model_id
        if existing.display_name != new_name:
            existing.display_name = new_name
            changed = True
        new_vision = bool(model_info.get("supports_vision", False))
        if existing.supports_vision != new_vision:
            existing.supports_vision = new_vision
            changed = True
        if changed:
            # Touch updated_at
            existing.enabled = existing.enabled  # no-op, triggers onupdate
        return changed

    new = AIModel(
        provider_id=provider_row.id,
        model_id=model_id,
        display_name=model_info.get("display_name") or model_id,
        supports_vision=bool(model_info.get("supports_vision", False)),
        supports_reasoning=False,
        max_tokens=4096,
        enabled=True,
    )
    session.add(new)
    return True


# ---------------------------------------------------------------------------
# Credential lookup — uses automation_service.security.credentials
# ---------------------------------------------------------------------------


def _get_credential_safe(service: Optional[str]) -> Optional[str]:
    if not service:
        return None
    try:
        from automation_service.security.credentials import get_credential
        return get_credential(service)
    except Exception as exc:
        logger.warning("credential lookup failed (service={} err={})", service, exc)
        return None


# ---------------------------------------------------------------------------
# Main sync routine
# ---------------------------------------------------------------------------


async def sync_models(session=None, *, include_vercel_gateway: bool = True) -> dict[str, int]:
    """Sync models for every provider in ``registry.PROVIDERS``.

    Args:
        session: An open SQLAlchemy session. If ``None``, a new session is
            created from ``database.base.SessionLocal`` and closed at the end.
        include_vercel_gateway: When True, also call the Vercel AI Gateway
            (which aggregates all upstream providers) and store its results.

    Returns:
        ``{provider_name: count_of_models_synced}`` for EVERY provider in
        the registry. Providers without a credential get count=0.
    """
    from database.base import SessionLocal
    from database.models.schema import AIProvider as AIProviderRow  # noqa: F401
    from database.models.schema import AIModel  # noqa: F401  (registers metadata)

    own_session = session is None
    if own_session:
        session = SessionLocal()

    results: dict[str, int] = {}
    pending_since_commit = 0

    try:
        # ---- 1. Iterate registry providers ----
        for name, info in provider_registry.PROVIDERS.items():
            results[name] = 0  # default to zero; overwritten if we sync anything

            # Vercel gateway handled separately below
            if name == "vercel_gateway":
                continue

            env_key = info.get("env_key")
            api_key = _get_credential_safe(env_key)

            # Local providers (ollama, lm_studio) have no env_key — they're
            # always available when the local server is up.
            if not api_key and env_key is not None:
                logger.info("sync_models: skip {} (no credential for {})", name, env_key)
                continue

            # In mock mode, local providers (no env_key, e.g. lm_studio)
            # don't have a real local server running — skip them so the
            # sync returns all-zero counts (consistent with the "no
            # credentials → count=0" contract). In production (mock mode
            # off), the local server is expected to be up.
            if (
                not api_key
                and env_key is None
                and os.environ.get("AUTOMATION_MOCK_MODE", "true").lower() == "true"
            ):
                logger.info("sync_models: skip {} (local provider, mock mode)", name)
                continue

            # Only OpenAI-compatible providers expose a usable /models endpoint
            # through the OpenAICompatibleProvider class. For non-compat ones
            # without a concrete implementation, list_models() would return [].
            if not info.get("openai_compatible") and name not in {"ollama", "lm_studio", "gemini"}:
                logger.info("sync_models: skip {} (non-OpenAI-compatible, no concrete impl)", name)
                continue

            try:
                cfg = AIProviderConfig(
                    name=name,
                    api_key=api_key,
                    base_url=info.get("base_url"),
                    model=info.get("default_model", ""),
                )
                provider = get_provider(name, cfg)

                # Provider must expose list_models()
                if not hasattr(provider, "list_models"):
                    logger.info("sync_models: skip {} (no list_models method)", name)
                    continue

                logger.info("sync_models: calling list_models on {}", name)
                models = await provider.list_models()
                if not models:
                    logger.info("sync_models: {} returned 0 models", name)
                    continue

                provider_row = _get_or_create_provider_row(session, name, info)
                # ``written`` = how many model records we processed (inserted
                # OR up-to-date). This is what users want to see: "how many
                # models does provider X expose right now?"
                written = 0
                inserted_or_updated = 0
                for m in models:
                    written += 1
                    if _upsert_model_row(session, provider_row, m):
                        inserted_or_updated += 1
                        pending_since_commit += 1
                        if pending_since_commit >= BATCH_SIZE:
                            session.commit()
                            pending_since_commit = 0
                            logger.info(
                                "sync_models: batch commit ({} rows so far for {})",
                                inserted_or_updated, name,
                            )
                results[name] = written
                logger.info(
                    "sync_models: {} synced {} models ({} new/updated)",
                    name, written, inserted_or_updated,
                )
            except Exception as exc:
                # One provider's failure must NOT stop the rest.
                logger.error("sync_models: {} failed ({})", name, exc)
                results[name] = 0

        # ---- 2. Vercel AI Gateway — called once, aggregates everything ----
        if include_vercel_gateway:
            gw_info = provider_registry.PROVIDERS.get("vercel_gateway", {})
            gw_key = _get_credential_safe(gw_info.get("env_key"))
            if not gw_key:
                logger.info("sync_models: skip vercel_gateway (no credential)")
                results["vercel_gateway"] = 0
            else:
                try:
                    from automation_service.ai_providers.vercel_gateway import (
                        VercelAIGatewayProvider,
                    )
                    gw_cfg = AIProviderConfig(
                        name="vercel_gateway",
                        api_key=gw_key,
                        base_url=gw_info.get("base_url"),
                        model=gw_info.get("default_model", "openai/gpt-4o-mini"),
                    )
                    gw_provider = VercelAIGatewayProvider(gw_cfg)
                    logger.info("sync_models: calling list_models on vercel_gateway")
                    models = await gw_provider.list_models()
                    provider_row = _get_or_create_provider_row(session, "vercel_gateway", gw_info)
                    written = 0
                    inserted_or_updated = 0
                    for m in models:
                        written += 1
                        if _upsert_model_row(session, provider_row, m):
                            inserted_or_updated += 1
                            pending_since_commit += 1
                            if pending_since_commit >= BATCH_SIZE:
                                session.commit()
                                pending_since_commit = 0
                    results["vercel_gateway"] = written
                    logger.info(
                        "sync_models: vercel_gateway synced {} models ({} new/updated)",
                        written, inserted_or_updated,
                    )
                except Exception as exc:
                    logger.error("sync_models: vercel_gateway failed ({})", exc)
                    results["vercel_gateway"] = 0

        # Final commit for any remaining rows
        if pending_since_commit > 0:
            session.commit()
            pending_since_commit = 0

    finally:
        if own_session and session is not None:
            session.close()

    return results


__all__ = ["sync_models", "BATCH_SIZE"]
