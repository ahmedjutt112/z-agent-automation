"""Top-level ``ai_providers`` package — provider registry + helpers.

This package lives at ``apps/automation-service/ai_providers/`` (OUTSIDE the
``automation_service`` Python package) so the same metadata is importable by
the ``zai`` CLI in :mod:`app.main` and the automation-service code under
:mod:`automation_service.ai_providers.base`.

Importing this module is dependency-free; only :data:`registry.PROVIDERS`
and small read-only helpers are exposed here.
"""

from __future__ import annotations

from .registry import (  # noqa: F401  (re-export)
    PROVIDERS,
    get_display_name,
    non_openai_compatible_names,
    openai_compatible_names,
    supports_model_list_names,
)

__all__ = [
    "PROVIDERS",
    "get_display_name",
    "non_openai_compatible_names",
    "openai_compatible_names",
    "supports_model_list_names",
]
