"""Hello World plugin entry point — master prompt section 53.

Registers one tool, ``hello.greet``, that returns ``"Hello from {name}!"``.

Demonstrates the canonical plugin shape:

* ``plugin.json`` manifest sits next to this file.
* ``register(manager)`` is the optional entry point the
  :class:`~automation_service.plugins.manager.PluginManager` calls after
  importing this module. The ``@register_tool`` decorator runs at import
  time, so even plugins that don't define ``register()`` will work.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from automation_service.engine.tool_registry import register_tool, Tool
from automation_service.models import ActionResult, StepStatus


@register_tool
class HelloGreetTool(Tool):
    """Returns ``Hello from {name}!``."""

    name = "hello.greet"
    description = "Return a friendly greeting. Example plugin tool."
    permission_level = "allow_once"
    risk_level = "low"
    timeout_ms = 2_000
    input_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "default": "world"},
        },
    }

    async def execute(self, args: dict[str, Any]) -> ActionResult:
        start = datetime.now(timezone.utc)
        name = args.get("name") or "world"
        message = f"Hello from {name}!"
        return ActionResult(
            tool=self.name,
            status=StepStatus.COMPLETED,
            output={"message": message, "name": name},
            finished_at=datetime.now(timezone.utc),
            duration_ms=int((datetime.now(timezone.utc) - start).total_seconds() * 1000),
        )


def register(manager) -> None:
    """Plugin entry point — manager is the PluginManager instance.

    Tools were already registered at import time via the decorator above;
    this hook exists so plugins can additionally register triggers, AI
    providers, or workflow nodes if they want to.
    """
    manager.log(f"hello_world plugin loaded — registered tool 'hello.greet'")
