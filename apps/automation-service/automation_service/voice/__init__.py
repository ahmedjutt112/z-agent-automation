"""Voice control subsystem — master prompt section 46.

Public surface
--------------

* :class:`VoiceManager` — async STT + TTS pipeline that respects
  ``settings.mock_mode`` (no audio hardware touched when mock_mode=True).
* :data:`voice_manager` — module-level singleton used by the FastAPI router.
* :data:`router` — FastAPI router exposed via ``app.include_router`` in
  ``automation_service.main``.

Pipeline (per section 46):

    Microphone -> Speech-to-Text -> AI Planner -> Permission Engine
             -> Automation Engine

CRITICAL invariant: voice commands NEVER bypass the security confirmation
flow. Even if the user says "delete all files", the planner produces a
plan, the permission engine evaluates it, and the user must explicitly
click "Approve and Run" in the UI. :meth:`VoiceManager.listen_and_plan`
deliberately returns the plan WITHOUT executing it; the frontend then
triggers :meth:`VoiceManager.listen_and_execute` only after the user
approves.
"""
from __future__ import annotations

from .manager import VoiceManager, voice_manager
from .api import router

__all__ = ["VoiceManager", "voice_manager", "router"]
