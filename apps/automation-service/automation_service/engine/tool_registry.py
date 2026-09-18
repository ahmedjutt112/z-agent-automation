"""Tool registry and base Tool class — master prompt §8.

Every tool MUST define: name, description, input_schema, permission_level,
risk_level, timeout, rollback_strategy, verification_strategy.
"""

from __future__ import annotations

import abc
import importlib
import pkgutil
from typing import Any, Optional

from ..models import ActionRequest, ActionResult, ToolSpec, StepStatus


class Tool(abc.ABC):
    """Abstract base class for all automation tools."""

    #: Subclasses MUST set these class-level fields
    name: str = ""
    description: str = ""
    permission_level: str = "allow_once"
    risk_level: str = "low"
    timeout_ms: int = 10_000
    rollback_strategy: Optional[str] = None
    verification_strategy: Optional[str] = None
    input_schema: dict[str, Any] = {"type": "object", "properties": {}}

    @abc.abstractmethod
    async def execute(self, args: dict[str, Any]) -> ActionResult:
        """Run the tool. Subclasses return an ActionResult."""
        raise NotImplementedError

    def spec(self) -> ToolSpec:
        """Return the declared tool specification."""
        return ToolSpec(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema,
            permission_level=self.permission_level,  # type: ignore[arg-type]
            risk_level=self.risk_level,  # type: ignore[arg-type]
            timeout_ms=self.timeout_ms,
            rollback_strategy=self.rollback_strategy,
            verification_strategy=self.verification_strategy,
        )


class ToolRegistry:
    """Discovers and stores all registered tools."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if not tool.name:
            raise ValueError(f"Tool {tool.__class__.__name__} has no name")
        if tool.name in self._tools:
            raise ValueError(f"Duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def discover(self) -> None:
        """Auto-import all submodules of ``automation_service.tools`` so that
        their @register_tool decorators run."""
        from .. import tools as _tools_pkg

        for mod_info in pkgutil.iter_modules(_tools_pkg.__path__):
            importlib.import_module(f"{_tools_pkg.__name__}.{mod_info.name}")


# Singleton
tool_registry = ToolRegistry()


def register_tool(cls):
    """Class decorator: instantiates and registers a Tool subclass."""
    if not issubclass(cls, Tool):
        raise TypeError(f"@register_tool expects Tool subclass, got {cls}")
    instance = cls()
    tool_registry.register(instance)
    return cls
