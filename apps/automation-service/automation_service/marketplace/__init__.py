"""Marketplace package — master prompt §52 (template marketplace).

Provides:
- :class:`MarketplaceManager` — in-memory store of marketplace templates with
  install / uninstall / rate / submit / search operations.
- :class:`MarketplaceTemplate` — pydantic schema for a marketplace listing.
- :class:`MarketplaceCategory` — enum of the 10 required marketplace
  categories (productivity, developer, marketing, data-entry, reporting,
  file-management, browser-automation, email-automation, excel-automation,
  pdf-automation).

Master prompt §52 mandates: imported workflows MUST be sandboxed and
permission-scanned before they can be executed. :meth:`MarketplaceManager.
install_template` runs every installed workflow through
:func:`permission_engine.evaluate_plan` and persists it with
``enabled=False`` so the user must manually review and enable it before any
node can run.
"""

from __future__ import annotations

from .manager import (
    MarketplaceCategory,
    MarketplaceManager,
    MarketplaceTemplate,
    marketplace_manager,
)

__all__ = [
    "MarketplaceCategory",
    "MarketplaceManager",
    "MarketplaceTemplate",
    "marketplace_manager",
]
