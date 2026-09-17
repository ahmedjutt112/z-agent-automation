"""Planner Agent — master prompt §7 (Planner), §66 (AI planning safety).

Converts a natural-language goal into a structured Plan with:
- goal
- steps (each with risk_level, confidence, fallback, verification)
- required_permissions
- overall_risk
- potential_side_effects
- estimated_duration_seconds
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from ..models import (
    ActionRequest,
    PermissionLevel,
    Plan,
    PlanStep,
    RiskLevel,
)
from ..ai_providers.base import AIProvider, AIProviderConfig, get_provider
from ..config import settings
from ..engine.event_bus import event_bus


SYSTEM_PROMPT = """You are a desktop automation planner. Convert the user's goal
into a JSON plan that the workflow engine can execute.

Available tools (each becomes a step with action=tool_name):
- mouse.click, mouse.move, mouse.scroll
- keyboard.type, keyboard.hotkey
- screen.capture, screen.ocr
- file.read, file.write, file.move, file.rename, file.list
- app.launch
- window.list, process.list
- browser.open, browser.navigate, browser.click, browser.type, browser.extract

Respond with ONLY a JSON object matching this schema:
{
  "goal": "<original goal>",
  "steps": [
    {"id": "1", "action": "<tool_name>", "args": {...}, "risk_level": "low|medium|high|critical",
     "confidence": 0.0-1.0, "timeout_ms": 10000, "retry_count": 0, "fallback": null|"tool_name",
     "verification": null|"description"}
  ],
  "required_permissions": ["allow_once"],
  "overall_risk": "low|medium|high|critical",
  "potential_side_effects": ["..."],
  "estimated_duration_seconds": 30
}

Rules:
1. Every step MUST have a risk_level.
2. Set confidence based on how sure you are the step will succeed.
3. Identify destructive operations and mark them HIGH or CRITICAL.
4. Use the simplest tool that achieves the goal — never call AI for things
   Python can determine deterministically (master prompt §58).
5. If a step might fail due to UI changes, set a fallback to a different tool
   (e.g. fallback from browser.click to screen.ocr + mouse.click).
"""


class PlannerAgent:
    """Converts natural-language goals into structured plans."""

    def __init__(self, provider: AIProvider | None = None) -> None:
        if provider is None:
            config = AIProviderConfig(
                name=settings.default_ai_provider,
                api_key=__import__("os").getenv("OPENAI_API_KEY") or __import__("os").getenv("ANTHROPIC_API_KEY"),
                model=settings.default_ai_model,
            )
            try:
                provider = get_provider(settings.default_ai_provider, config)
            except Exception:
                # Fall back to a deterministic planner for offline / mock mode
                provider = None
        self._provider = provider

    async def plan(self, goal: str) -> Plan:
        if self._provider is None:
            return self._fallback_plan(goal)

        try:
            response = await self._provider.complete(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Goal: {goal}"},
                ],
                temperature=0.1,
                max_tokens=1500,
            )
            return self._parse_response(goal, response)
        except Exception as exc:
            event_bus.publish("TASK_FAILED", {"error": f"planner AI call failed: {exc}"})
            return self._fallback_plan(goal, error=str(exc))

    def _parse_response(self, goal: str, response: str) -> Plan:
        # Extract JSON from response (it may have markdown fences)
        m = re.search(r"\{[\s\S]*\}", response)
        if not m:
            return self._fallback_plan(goal, error="no JSON in planner response")
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError as exc:
            return self._fallback_plan(goal, error=f"invalid JSON: {exc}")

        steps = [
            PlanStep(
                id=s.get("id", str(i + 1)),
                action=s["action"],
                args=s.get("args", {}),
                risk_level=RiskLevel(s.get("risk_level", "low")),
                confidence=float(s.get("confidence", 1.0)),
                timeout_ms=int(s.get("timeout_ms", 10_000)),
                retry_count=int(s.get("retry_count", 0)),
                fallback=s.get("fallback"),
                verification=s.get("verification"),
            )
            for i, s in enumerate(data.get("steps", []))
        ]

        risk_str = data.get("overall_risk", "low")
        try:
            overall_risk = RiskLevel(risk_str)
        except ValueError:
            overall_risk = max((s.risk_level for s in steps), default=RiskLevel.LOW)

        perm_strs = data.get("required_permissions", ["allow_once"])
        perms: list[PermissionLevel] = []
        for p in perm_strs:
            try:
                perms.append(PermissionLevel(p))
            except ValueError:
                pass
        if not perms:
            perms = [PermissionLevel.ALLOW_ONCE]

        return Plan(
            id=uuid4(),
            goal=goal,
            steps=steps,
            required_permissions=perms,
            overall_risk=overall_risk,
            potential_side_effects=data.get("potential_side_effects", []),
            estimated_duration_seconds=int(data.get("estimated_duration_seconds", 30)),
        )

    def _fallback_plan(self, goal: str, error: str | None = None) -> Plan:
        """When no AI provider is available, produce a minimal safe plan
        that simply logs the goal — does not execute destructive actions."""
        return Plan(
            id=uuid4(),
            goal=goal,
            steps=[
                PlanStep(
                    id="1",
                    action="screen.capture",
                    args={"filename": f"goal_{int(datetime.now(timezone.utc).timestamp())}.png"},
                    risk_level=RiskLevel.LOW,
                    confidence=1.0,
                    verification="file_exists",
                )
            ],
            required_permissions=[PermissionLevel.ALLOW_ONCE],
            overall_risk=RiskLevel.LOW,
            potential_side_effects=[],
            estimated_duration_seconds=5,
            variables={"fallback_reason": error or "no AI provider available"},
        )
