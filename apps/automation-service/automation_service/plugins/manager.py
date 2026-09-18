"""Plugin loader / manager — master prompt section 53 (PLUGIN SYSTEM).

Discovers plugin manifests (``plugin.json``) under the plugins directory,
imports each plugin's ``main.py``, and calls its ``register(manager)``
entry point so the plugin can install tools, triggers, AI providers,
workflow nodes, etc.

Permission model
----------------
Every plugin declares a list of permissions (e.g. ``["filesystem.read",
"browser.navigate"]``). The manager checks these against the project's
permission engine before loading. Plugins requesting permissions not in
the allowlist are refused.

Sandboxing
----------
Plugins run in-process (no separate interpreter). Their tools go through
the same ``@register_tool`` decorator + permission flow as core tools, so
the security architecture (master prompt §55) still applies uniformly.

Manifest schema (``plugin.json``)::

    {
      "name": "hello_world",
      "version": "1.0.0",
      "description": "...",
      "author": "...",
      "permissions": ["filesystem.read"],
      "tools": ["tools.greet"],          # dotted module paths under the plugin
      "triggers": [],
      "ai_providers": [],
      "settings_schema": {}
    }

Plugin entry point (``main.py``)::

    from automation_service.engine.tool_registry import register_tool, Tool
    from automation_service.models import ActionResult, StepStatus

    @register_tool
    class HelloGreetTool(Tool):
        name = "hello.greet"
        ...

    def register(manager) -> None:
        # Optional hook for trigger / AI provider registration.
        manager.log("hello_world registered")
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from loguru import logger
from pydantic import BaseModel, Field

from ..config import settings
from ..engine.tool_registry import tool_registry


# Master prompt §53 — plugins live under /home/z/my-project/plugins/.
DEFAULT_PLUGINS_DIR: Path = settings.project_root / "plugins"

# Allowlist of permissions a plugin may request. Plugins asking for
# anything outside this list are refused. (Conservative default — callers
# can extend at runtime via PluginManager.allow_permission.)
DEFAULT_ALLOWED_PERMISSIONS: frozenset[str] = frozenset(
    {
        "filesystem.read",
        "filesystem.write",
        "browser.navigate",
        "browser.click",
        "browser.type",
        "screen.capture",
        "screen.ocr",
        "notifications.show",
        "clipboard.read",
        "clipboard.write",
    }
)


class PluginState(str, Enum):
    """Lifecycle state of a loaded plugin."""

    DISCOVERED = "discovered"  # manifest found, not yet loaded
    LOADED = "loaded"
    DISABLED = "disabled"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Manifest model
# ---------------------------------------------------------------------------


class PluginSpec(BaseModel):
    """The deserialized ``plugin.json`` manifest."""

    name: str
    version: str = "0.0.1"
    description: str = ""
    author: str = ""
    permissions: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)  # dotted module paths
    triggers: list[dict[str, Any]] = Field(default_factory=list)
    ai_providers: list[dict[str, Any]] = Field(default_factory=list)
    settings_schema: dict[str, Any] = Field(default_factory=dict)
    # Absolute path to the plugin directory (populated by discover()).
    plugin_dir: Optional[str] = None


# ---------------------------------------------------------------------------
# Plugin runtime wrapper
# ---------------------------------------------------------------------------


@dataclass
class Plugin:
    """A loaded (or loadable) plugin instance."""

    spec: PluginSpec
    module: Any = None  # the imported main.py module
    state: PluginState = PluginState.DISCOVERED
    error: Optional[str] = None
    # Tool names registered by this plugin (so unload() can revoke them).
    registered_tool_names: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.spec.name


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class PluginManager:
    """Discovers, loads, and unloads plugins.

    Usage::

        mgr = PluginManager()
        for spec in mgr.discover("/home/z/my-project/plugins"):
            print(spec.name, spec.version)

        plugin = mgr.load("hello_world")
        # ... plugin.registered_tool_names is now populated ...

        mgr.unload("hello_world")
    """

    def __init__(
        self,
        plugins_dir: Optional[Path] = None,
        allowed_permissions: Optional[set[str]] = None,
        registry: Any = None,
    ) -> None:
        self.plugins_dir = Path(plugins_dir) if plugins_dir else DEFAULT_PLUGINS_DIR
        self.allowed_permissions: set[str] = set(
            allowed_permissions
            if allowed_permissions is not None
            else DEFAULT_ALLOWED_PERMISSIONS
        )
        # Tool registry — defaults to the singleton but injectable for tests.
        self._registry = registry if registry is not None else tool_registry
        # Discovered specs (name -> PluginSpec). Populated by discover().
        self._specs: dict[str, PluginSpec] = {}
        # Loaded plugins (name -> Plugin). Populated by load().
        self._loaded: dict[str, Plugin] = {}

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover(self, plugins_dir: Optional[Path] = None) -> list[PluginSpec]:
        """Scan ``plugins_dir`` for ``plugin.json`` files and return their specs.

        Each subdirectory of ``plugins_dir`` that contains a ``plugin.json``
        is treated as a plugin. The manifest is parsed with Pydantic; if
        parsing fails the plugin is logged and skipped.
        """
        scan_dir = Path(plugins_dir) if plugins_dir else self.plugins_dir
        self._specs.clear()
        if not scan_dir.exists():
            logger.info("plugins dir {!r} does not exist — no plugins discovered", scan_dir)
            return []

        specs: list[PluginSpec] = []
        for child in sorted(scan_dir.iterdir()):
            if not child.is_dir():
                continue
            manifest = child / "plugin.json"
            if not manifest.exists():
                continue
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
                spec = PluginSpec(**data)
                spec.plugin_dir = str(child.resolve())
                self._specs[spec.name] = spec
                specs.append(spec)
                logger.info("discovered plugin: {} v{}", spec.name, spec.version)
            except Exception as exc:
                logger.warning("skipping plugin at {}: {}", child, exc)
        return specs

    # ------------------------------------------------------------------
    # Loading / unloading
    # ------------------------------------------------------------------

    def load(self, plugin_name: str) -> Plugin:
        """Import the plugin's ``main.py`` and invoke ``register(manager)``.

        Raises ``KeyError`` if the plugin isn't discovered. Raises
        ``PermissionError`` if the plugin requests a permission not in the
        allowlist.
        """
        if plugin_name in self._loaded:
            return self._loaded[plugin_name]

        spec = self._specs.get(plugin_name)
        if spec is None or spec.plugin_dir is None:
            raise KeyError(f"plugin {plugin_name!r} not discovered — call discover() first")

        # Permission gate — §53 "Every plugin requires declared permissions".
        denied = [p for p in spec.permissions if p not in self.allowed_permissions]
        if denied:
            plugin = Plugin(spec=spec, state=PluginState.ERROR, error=f"denied permissions: {denied}")
            self._loaded[plugin_name] = plugin
            raise PermissionError(
                f"plugin {plugin_name!r} requested permissions not in allowlist: {denied}"
            )

        plugin_dir = Path(spec.plugin_dir)
        plugin = Plugin(spec=spec, state=PluginState.LOADED)

        # Snapshot the tool registry before loading so we can detect which
        # tools the plugin added.
        tool_names_before = {t.name for t in self._registry.all()}

        try:
            module = self._import_plugin_module(plugin_dir, spec.name)
            plugin.module = module
            # Optional entry point — the plugin may use it to register
            # triggers / AI providers / workflow nodes (not just tools).
            register_fn = getattr(module, "register", None)
            if callable(register_fn):
                try:
                    register_fn(self)
                except Exception as exc:
                    logger.warning("plugin {} register() raised: {}", spec.name, exc)
                    # Non-fatal — tools may still have been registered via
                    # the @register_tool decorator at import time.

            tool_names_after = {t.name for t in self._registry.all()}
            plugin.registered_tool_names = sorted(tool_names_after - tool_names_before)
            logger.info(
                "loaded plugin {} — registered {} tools: {}",
                spec.name,
                len(plugin.registered_tool_names),
                plugin.registered_tool_names,
            )
        except Exception as exc:
            plugin.state = PluginState.ERROR
            plugin.error = str(exc)
            logger.error("failed to load plugin {}: {}", spec.name, exc)
        finally:
            self._loaded[plugin_name] = plugin
        return plugin

    def unload(self, plugin_name: str) -> None:
        """Remove all tools registered by ``plugin_name`` from the registry."""
        plugin = self._loaded.get(plugin_name)
        if plugin is None:
            return
        # Revoke tool registrations. The ToolRegistry stores tools in a dict
        # keyed by name, so a direct pop is sufficient.
        for tool_name in plugin.registered_tool_names:
            try:
                self._registry._tools.pop(tool_name, None)
            except Exception as exc:  # pragma: no cover — defensive
                logger.warning("could not revoke tool {}: {}", tool_name, exc)
        plugin.state = PluginState.DISABLED
        plugin.registered_tool_names = []
        logger.info("unloaded plugin {}", plugin_name)

    # ------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------

    def list_loaded(self) -> list[Plugin]:
        return list(self._loaded.values())

    def list_available(self) -> list[PluginSpec]:
        return list(self._specs.values())

    # ------------------------------------------------------------------
    # Hooks for plugins to use during register()
    # ------------------------------------------------------------------

    def allow_permission(self, perm: str) -> None:
        """Add a permission to the runtime allowlist."""
        self.allowed_permissions.add(perm)

    def log(self, message: str) -> None:
        """Convenience hook plugins can call from ``register()``."""
        logger.info("[plugin] {}", message)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _import_plugin_module(self, plugin_dir: Path, plugin_name: str):
        """Import ``<plugin_dir>/main.py`` as a unique module.

        We use ``importlib.util.spec_from_file_location`` so each plugin's
        ``main.py`` is loaded under a unique fully-qualified name (avoiding
        collisions if two plugins both ship a ``main.py``).
        """
        module_path = plugin_dir / "main.py"
        if not module_path.exists():
            raise FileNotFoundError(f"plugin {plugin_name!r} has no main.py at {module_path}")
        # Add the plugin directory to sys.path so its ``tools/`` subpackage
        # can be imported with a normal ``from tools.greet import ...``.
        plugin_dir_str = str(plugin_dir)
        if plugin_dir_str not in sys.path:
            sys.path.insert(0, plugin_dir_str)
        # Use a unique name so re-loading during tests works.
        unique_name = f"_automation_plugin_{plugin_name}_{uuid4().hex[:8]}"
        spec = importlib.util.spec_from_file_location(unique_name, module_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"could not build spec for {module_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[unique_name] = module
        spec.loader.exec_module(module)
        return module


# Module-level singleton.
plugin_manager = PluginManager()
