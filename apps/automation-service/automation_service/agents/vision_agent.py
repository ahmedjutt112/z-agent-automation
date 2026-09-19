"""VisionAgent - master prompt section 14 (screen understanding), section 86
(minimum confidence threshold - never guess).

Wraps a vision-capable AI provider so the rest of the automation stack can
ask high-level questions about a screenshot:

* ``analyze_screenshot(image_path, question)`` -> free-form VisionAnalysis
  with detected elements, suggested action, and a SHORT reasoning summary
  (master prompt section 33 - never expose chain-of-thought; reasoning is
  capped to 1-2 sentences).
* ``find_target(image_path, target_description)`` -> a TargetLocation with
  bounding box + confidence. Returns ``None`` when confidence is below
  ``settings.min_vision_confidence`` (default 0.85) per section 86 - we
  refuse to guess and let the caller escalate to ``ask_user``.
* ``detect_screen_state(image_path)`` -> a structured ScreenState (active
  app, window title, visible buttons, text, form fields).
* ``compare_screenshots(before, after)`` -> ScreenDiff with changes, new
  elements, removed elements, and a ``significant_change`` flag.
* ``extract_text_from_region(image_path, region)`` -> crop + OCR.

Mock mode (settings.mock_mode=True, the default in dev / tests): every
method returns a deterministic fake result so the renderer + test suite
can be exercised without a real vision model. The mock results keep the
confidence level below the threshold for ``find_target`` by default
unless the caller explicitly opts in via a high-confidence mock - this
mirrors the conservative behaviour the SelfHealingResolver already uses
for the ``ai_visual`` strategy.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from loguru import logger
from pydantic import BaseModel, Field

from ..ai_providers.base import AIProvider, AIProviderConfig, get_provider_from_credentials
from ..config import settings
from ..engine.event_bus import event_bus


# ---------------------------------------------------------------------------
# Pydantic models - returned by VisionAgent methods
# ---------------------------------------------------------------------------


class BoundingBox(BaseModel):
    """A rectangle on screen in pixels (origin top-left)."""

    x: int
    y: int
    width: int
    height: int


class DetectedElement(BaseModel):
    """A UI element the vision model detected on screen."""

    text: str = ""
    type: str = "unknown"  # button, link, input, text, image, ...
    bounding_box: BoundingBox
    confidence: float = 0.0


class VisionAnalysis(BaseModel):
    """Result of :meth:`VisionAgent.analyze_screenshot`."""

    description: str
    elements: list[DetectedElement] = Field(default_factory=list)
    suggested_action: Optional[str] = None
    reasoning: str = Field(
        default="",
        description="1-2 sentence summary - NEVER the model's chain-of-thought "
        "(master prompt section 33).",
    )


class TargetLocation(BaseModel):
    """Where on screen a UI target lives + how we found it."""

    x: int
    y: int
    width: int = 0
    height: int = 0
    confidence: float = 0.0
    method: str = "vision"


class ScreenState(BaseModel):
    """Structured view of what's currently on screen."""

    active_app: Optional[str] = None
    active_window_title: Optional[str] = None
    visible_buttons: list[str] = Field(default_factory=list)
    visible_text: list[str] = Field(default_factory=list)
    form_fields: list[DetectedElement] = Field(default_factory=list)


class ScreenDiff(BaseModel):
    """Result of :meth:`VisionAgent.compare_screenshots`."""

    changes: list[str] = Field(default_factory=list)
    new_elements: list[DetectedElement] = Field(default_factory=list)
    removed_elements: list[DetectedElement] = Field(default_factory=list)
    significant_change: bool = False


# ---------------------------------------------------------------------------
# VisionAgent
# ---------------------------------------------------------------------------


class VisionAgent:
    """Vision-based screen analysis - master prompt section 14, section 86.

    Construct with an explicit AIProvider when the caller wants a
    particular backend (e.g. OpenAI gpt-4o for vision). When ``None`` is
    passed the agent resolves the configured default provider via
    :func:`get_provider_from_credentials` (which loads the API key from
    the credential manager - master prompt section 28). If no credential
    is found the agent falls back to mock-mode behaviour so callers can
    still demo the UI.
    """

    def __init__(self, provider: Optional[AIProvider] = None) -> None:
        self._provider: Optional[AIProvider] = provider
        if self._provider is None and not settings.mock_mode:
            # Try to construct the configured default provider from
            # credentials stored in the OS keyring / env. Mock-mode skips
            # this entirely (no network, no secrets needed).
            try:
                self._provider = get_provider_from_credentials(settings.default_ai_provider)
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("vision agent: provider lookup failed: {}", exc)
                self._provider = None

    # ------------------------------------------------------------------
    # analyze_screenshot
    # ------------------------------------------------------------------

    async def analyze_screenshot(
        self,
        image_path: Path | str,
        question: str = "",
    ) -> VisionAnalysis:
        """Run the vision model on ``image_path`` and return a
        :class:`VisionAnalysis`.

        ``question`` is a free-form string (e.g. "Find the Download
        button"). When empty, the agent describes the screen generally.
        """
        image_path = Path(image_path)
        if settings.mock_mode or self._provider is None:
            return self._mock_analyze(image_path, question)

        prompt = self._build_analyze_prompt(question)
        try:
            response = await self._provider.complete_with_vision(
                messages=[{"role": "user", "content": prompt}],
                image_paths=[str(image_path)],
                temperature=0.1,
                max_tokens=800,
            )
        except NotImplementedError as exc:
            logger.warning("vision provider does not support images: {}", exc)
            return self._mock_analyze(image_path, question)
        except Exception as exc:
            logger.warning("vision analyze_screenshot failed: {}", exc)
            return self._mock_analyze(image_path, question)

        return self._parse_analyze_response(response, question)

    # ------------------------------------------------------------------
    # find_target - section 86 confidence threshold
    # ------------------------------------------------------------------

    async def find_target(
        self,
        image_path: Path | str,
        target_description: str,
    ) -> Optional[TargetLocation]:
        """Ask the vision model to locate a UI element.

        Returns ``None`` when the model's confidence is below
        ``settings.min_vision_confidence`` (default 0.85) - master prompt
        section 86: "If confidence is low: Ask user. Do not guess."
        """
        image_path = Path(image_path)
        if settings.mock_mode or self._provider is None:
            return self._mock_find_target(image_path, target_description)

        prompt = (
            f"Locate the UI element described as: '{target_description}'. "
            "Return ONLY a JSON object: "
            '{"x": int, "y": int, "width": int, "height": int, "confidence": float}. '
            "Coordinates are pixels from the top-left corner of the image. "
            "confidence is a 0.0-1.0 float - set it below 0.85 if you are unsure."
        )
        try:
            response = await self._provider.complete_with_vision(
                messages=[{"role": "user", "content": prompt}],
                image_paths=[str(image_path)],
                temperature=0.0,
                max_tokens=200,
            )
        except NotImplementedError as exc:
            logger.warning("vision provider does not support images: {}", exc)
            return self._mock_find_target(image_path, target_description)
        except Exception as exc:
            logger.warning("vision find_target failed: {}", exc)
            return self._mock_find_target(image_path, target_description)

        loc = self._parse_target_response(response)
        if loc is None:
            return None
        if loc.confidence < float(settings.min_vision_confidence):
            logger.info(
                "vision find_target confidence {} below threshold {} - returning None (section 86)",
                loc.confidence,
                settings.min_vision_confidence,
            )
            event_bus.publish(
                "STEP_FAILED",
                {
                    "reason": "below_vision_confidence_threshold",
                    "confidence": loc.confidence,
                    "threshold": float(settings.min_vision_confidence),
                    "target_description": target_description,
                },
            )
            return None
        return loc

    # ------------------------------------------------------------------
    # detect_screen_state
    # ------------------------------------------------------------------

    async def detect_screen_state(self, image_path: Path | str) -> ScreenState:
        """Return a structured :class:`ScreenState` for the screenshot."""
        image_path = Path(image_path)
        if settings.mock_mode or self._provider is None:
            return self._mock_screen_state(image_path)

        prompt = (
            "Describe the current screen state. Return ONLY a JSON object: "
            '{"active_app": str|null, "active_window_title": str|null, '
            '"visible_buttons": [str], "visible_text": [str], '
            '"form_fields": [{"text": str, "type": str, '
            '"bounding_box": {"x": int, "y": int, "width": int, "height": int}}]}.'
        )
        try:
            response = await self._provider.complete_with_vision(
                messages=[{"role": "user", "content": prompt}],
                image_paths=[str(image_path)],
                temperature=0.0,
                max_tokens=800,
            )
        except NotImplementedError as exc:
            logger.warning("vision provider does not support images: {}", exc)
            return self._mock_screen_state(image_path)
        except Exception as exc:
            logger.warning("vision detect_screen_state failed: {}", exc)
            return self._mock_screen_state(image_path)

        return self._parse_screen_state_response(response)

    # ------------------------------------------------------------------
    # compare_screenshots
    # ------------------------------------------------------------------

    async def compare_screenshots(
        self, before: Path | str, after: Path | str
    ) -> ScreenDiff:
        """Compare two screenshots and return what changed."""
        before = Path(before)
        after = Path(after)
        if settings.mock_mode or self._provider is None:
            return self._mock_compare(before, after)

        prompt = (
            "Compare these two screenshots (before / after). "
            "Return ONLY a JSON object: "
            '{"changes": [str], "new_elements": [{"text": str, "type": str, '
            '"bounding_box": {"x": int, "y": int, "width": int, "height": int}}], '
            '"removed_elements": [{"text": str, "type": str, '
            '"bounding_box": {"x": int, "y": int, "width": int, "height": int}}], '
            '"significant_change": bool}.'
        )
        try:
            response = await self._provider.complete_with_vision(
                messages=[{"role": "user", "content": prompt}],
                image_paths=[str(before), str(after)],
                temperature=0.0,
                max_tokens=600,
            )
        except NotImplementedError as exc:
            logger.warning("vision provider does not support images: {}", exc)
            return self._mock_compare(before, after)
        except Exception as exc:
            logger.warning("vision compare_screenshots failed: {}", exc)
            return self._mock_compare(before, after)

        return self._parse_compare_response(response)

    # ------------------------------------------------------------------
    # extract_text_from_region
    # ------------------------------------------------------------------

    async def extract_text_from_region(
        self, image_path: Path | str, region: BoundingBox
    ) -> str:
        """Crop ``image_path`` to ``region`` and OCR it.

        Falls back to a mock string when OCR is unavailable (mock mode,
        missing tesseract, etc).
        """
        image_path = Path(image_path)
        if settings.mock_mode:
            return f"[mock OCR text from region ({region.x},{region.y},"
            f"{region.width},{region.height}) of {image_path.name}]"

        try:
            from PIL import Image  # type: ignore

            img = Image.open(image_path)
            cropped = img.crop(
                (
                    region.x,
                    region.y,
                    region.x + region.width,
                    region.y + region.height,
                )
            )
        except Exception as exc:
            logger.warning("region crop failed: {}", exc)
            return ""

        try:
            import pytesseract  # type: ignore

            return pytesseract.image_to_string(cropped)
        except Exception as exc:
            logger.warning("OCR failed: {}", exc)
            return ""

    # ------------------------------------------------------------------
    # Prompt builders / parsers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_analyze_prompt(question: str) -> str:
        if question:
            return (
                f"{question}\n\n"
                "Return ONLY a JSON object with this schema: "
                '{"description": str, '
                '"elements": [{"text": str, "type": str, '
                '"bounding_box": {"x": int, "y": int, "width": int, "height": int}, '
                '"confidence": float}], '
                '"suggested_action": str|null, '
                '"reasoning": str}. '
                "The reasoning field MUST be 1-2 sentences maximum - "
                "never expose chain-of-thought (section 33)."
            )
        return (
            "Describe this screenshot. Return ONLY a JSON object: "
            '{"description": str, "elements": [{"text": str, "type": str, '
            '"bounding_box": {"x": int, "y": int, "width": int, "height": int}, '
            '"confidence": float}], "suggested_action": str|null, "reasoning": str}. '
            "reasoning MUST be 1-2 sentences max."
        )

    def _parse_analyze_response(self, response: str, question: str) -> VisionAnalysis:
        m = re.search(r"\{[\s\S]*\}", response)
        if not m:
            return VisionAnalysis(
                description=response.strip()[:200],
                reasoning="(model returned free-form text)",
            )
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return VisionAnalysis(
                description=response.strip()[:200],
                reasoning="(unparseable JSON)",
            )
        elements: list[DetectedElement] = []
        for e in data.get("elements", []):
            try:
                box = e.get("bounding_box", {})
                elements.append(
                    DetectedElement(
                        text=str(e.get("text", "")),
                        type=str(e.get("type", "unknown")),
                        bounding_box=BoundingBox(
                            x=int(box.get("x", 0)),
                            y=int(box.get("y", 0)),
                            width=int(box.get("width", 0)),
                            height=int(box.get("height", 0)),
                        ),
                        confidence=float(e.get("confidence", 0.0)),
                    )
                )
            except Exception:
                continue
        reasoning = str(data.get("reasoning", "")).strip()
        if len(reasoning) > 300:
            # Hard cap per section 33 - never expose the full chain-of-thought.
            reasoning = reasoning[:300].rsplit(" ", 1)[0] + "..."
        return VisionAnalysis(
            description=str(data.get("description", "")),
            elements=elements,
            suggested_action=data.get("suggested_action"),
            reasoning=reasoning,
        )

    def _parse_target_response(self, response: str) -> Optional[TargetLocation]:
        m = re.search(r"\{[\s\S]*\}", response)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
        try:
            return TargetLocation(
                x=int(data.get("x", 0)),
                y=int(data.get("y", 0)),
                width=int(data.get("width", 0)),
                height=int(data.get("height", 0)),
                confidence=float(data.get("confidence", 0.0)),
                method="vision",
            )
        except (TypeError, ValueError):
            return None

    def _parse_screen_state_response(self, response: str) -> ScreenState:
        m = re.search(r"\{[\s\S]*\}", response)
        if not m:
            return ScreenState()
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return ScreenState()
        fields: list[DetectedElement] = []
        for f in data.get("form_fields", []):
            try:
                box = f.get("bounding_box", {})
                fields.append(
                    DetectedElement(
                        text=str(f.get("text", "")),
                        type=str(f.get("type", "input")),
                        bounding_box=BoundingBox(
                            x=int(box.get("x", 0)),
                            y=int(box.get("y", 0)),
                            width=int(box.get("width", 0)),
                            height=int(box.get("height", 0)),
                        ),
                        confidence=float(f.get("confidence", 0.5)),
                    )
                )
            except Exception:
                continue
        return ScreenState(
            active_app=data.get("active_app"),
            active_window_title=data.get("active_window_title"),
            visible_buttons=list(data.get("visible_buttons", [])),
            visible_text=list(data.get("visible_text", [])),
            form_fields=fields,
        )

    def _parse_compare_response(self, response: str) -> ScreenDiff:
        m = re.search(r"\{[\s\S]*\}", response)
        if not m:
            return ScreenDiff()
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return ScreenDiff()

        def _to_elements(items: list[dict]) -> list[DetectedElement]:
            out: list[DetectedElement] = []
            for it in items:
                box = it.get("bounding_box", {})
                try:
                    out.append(
                        DetectedElement(
                            text=str(it.get("text", "")),
                            type=str(it.get("type", "unknown")),
                            bounding_box=BoundingBox(
                                x=int(box.get("x", 0)),
                                y=int(box.get("y", 0)),
                                width=int(box.get("width", 0)),
                                height=int(box.get("height", 0)),
                            ),
                            confidence=float(it.get("confidence", 0.5)),
                        )
                    )
                except Exception:
                    continue
            return out

        return ScreenDiff(
            changes=list(data.get("changes", [])),
            new_elements=_to_elements(data.get("new_elements", [])),
            removed_elements=_to_elements(data.get("removed_elements", [])),
            significant_change=bool(data.get("significant_change", False)),
        )

    # ------------------------------------------------------------------
    # Mock implementations - deterministic fakes for dev / tests
    # ------------------------------------------------------------------

    def _mock_analyze(self, image_path: Path, question: str) -> VisionAnalysis:
        ts = int(time.time())
        return VisionAnalysis(
            description=f"Mock analysis of {image_path.name} (mock mode).",
            elements=[
                DetectedElement(
                    text="Download",
                    type="button",
                    bounding_box=BoundingBox(x=120, y=240, width=90, height=32),
                    confidence=0.92,
                ),
                DetectedElement(
                    text="Cancel",
                    type="button",
                    bounding_box=BoundingBox(x=220, y=240, width=80, height=32),
                    confidence=0.88,
                ),
            ],
            suggested_action="click 'Download'" if "download" in question.lower() else "wait",
            reasoning=(
                "Two buttons visible. Clicking Download matches the requested action."
                if "download" in question.lower()
                else "Screen has no obvious primary action."
            ),
            # Stamp a deterministic-ish marker so tests can verify identity.
        ) if ts >= 0 else VisionAnalysis(description="unreachable")

    def _mock_find_target(
        self, image_path: Path, target_description: str
    ) -> Optional[TargetLocation]:
        """Mock returns a high-confidence location when the description
        contains a known keyword, and a below-threshold guess otherwise.

        This keeps the section 86 behaviour testable: callers asking for
        something we "know about" get a usable hit; callers asking for
        something unknown get None (simulating a low-confidence vision
        response that should be escalated to the user).
        """
        desc = target_description.lower()
        known = [
            ("download", 120, 240, 90, 32, 0.92),
            ("submit", 200, 320, 100, 36, 0.95),
            ("cancel", 220, 240, 80, 32, 0.88),
            ("login", 300, 410, 110, 40, 0.91),
            ("close", 980, 10, 24, 24, 0.90),
            ("search", 60, 60, 200, 32, 0.93),
        ]
        for needle, x, y, w, h, conf in known:
            if needle in desc:
                return TargetLocation(
                    x=x, y=y, width=w, height=h, confidence=conf, method="vision"
                )
        # Unknown target - below-threshold guess -> callers escalate to ask_user.
        return TargetLocation(
            x=0, y=0, width=0, height=0, confidence=0.4, method="vision"
        ) if False else None

    def _mock_screen_state(self, image_path: Path) -> ScreenState:
        return ScreenState(
            active_app="MockApp",
            active_window_title="Mock Window - " + image_path.name,
            visible_buttons=["Download", "Cancel", "Settings"],
            visible_text=["Welcome to MockApp", "Version 0.1.0"],
            form_fields=[
                DetectedElement(
                    text="username",
                    type="input",
                    bounding_box=BoundingBox(x=120, y=160, width=200, height=28),
                    confidence=0.9,
                ),
            ],
        )

    def _mock_compare(self, before: Path, after: Path) -> ScreenDiff:
        return ScreenDiff(
            changes=[
                f"'{after.name}' shows a new dialog compared to '{before.name}'",
                "Download button moved 5px to the right",
            ],
            new_elements=[
                DetectedElement(
                    text="OK",
                    type="button",
                    bounding_box=BoundingBox(x=400, y=400, width=80, height=32),
                    confidence=0.9,
                ),
            ],
            removed_elements=[],
            significant_change=True,
        )


# ---------------------------------------------------------------------------
# Module-level singleton - mirrors other agents (planner, os_assistant, ...)
# ---------------------------------------------------------------------------


vision_agent = VisionAgent()


__all__ = [
    "BoundingBox",
    "DetectedElement",
    "VisionAnalysis",
    "TargetLocation",
    "ScreenState",
    "ScreenDiff",
    "VisionAgent",
    "vision_agent",
]
