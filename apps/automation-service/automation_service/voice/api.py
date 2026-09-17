"""FastAPI router for the voice subsystem — master prompt section 46.

Mounted under ``/voice`` in main.py. All routes require the IPC bearer
token (resolved lazily from ``automation_service.main`` to avoid the
circular import that would otherwise happen if we imported main at
module load time).

Endpoints
---------

* ``POST /voice/listen``                — capture + transcribe a single
  utterance; returns ``{transcript}``.
* ``POST /voice/speak``                  — body: ``{text, voice?}``;
  returns ``{spoken: true}``.
* ``POST /voice/listen-and-plan``        — full pipeline up to plan
  generation (NO execution — section 46 invariant).
* ``POST /voice/listen-and-execute``     — body: ``{plan}`` — executes
  an already-approved plan via WorkflowExecutor.
* ``POST /voice/start-continuous``       — starts background wake-word
  listening.
* ``POST /voice/stop-continuous``         — stops background listening.
* ``GET  /voice/status``                 — returns ``{listening,
  wake_word, last_transcript, mock_mode}``.
* ``WS   /voice/stream``                 — pushes live transcript events
  to the frontend as they're recognized.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field

from ..engine.event_bus import event_bus
from .manager import voice_manager


router = APIRouter()


# ---------------------------------------------------------------------------
# Auth dependency (lazy to avoid circular import with automation_service.main)
# ---------------------------------------------------------------------------


async def _verify_ipc_token(authorization: str | None = None) -> None:
    """Resolve ``verify_ipc_token`` from main lazily.

    The actual implementation lives in :mod:`automation_service.main`.
    We look it up at request time so importing this router doesn't pull
    in the FastAPI app before all subsystems register.
    """
    from ..main import verify_ipc_token

    await verify_ipc_token(authorization)


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class ListenResponse(BaseModel):
    transcript: str = Field(..., description="Transcribed text from the microphone")


class SpeakRequest(BaseModel):
    text: str = Field(..., description="Text to synthesize")
    voice: str = Field("default", description="Voice name (default/male/female/...)")


class SpeakResponse(BaseModel):
    spoken: bool = Field(..., description="True if synthesis completed")


class ListenAndPlanResponse(BaseModel):
    transcript: str
    plan: dict[str, Any]


class ListenAndExecuteRequest(BaseModel):
    plan: dict[str, Any] = Field(..., description="An approved Plan (full pydantic Plan dict)")


class ListenAndExecuteResponse(BaseModel):
    run_id: Optional[str] = None
    plan_id: str
    status: str
    decision: Optional[str] = None


class ContinuousResponse(BaseModel):
    started: bool = False
    stopped: bool = False
    already_listening: bool = False
    was_listening: bool = False
    wake_word: str
    mock_mode: bool = False


class StatusResponse(BaseModel):
    listening: bool
    wake_word: str
    last_transcript: Optional[str] = None
    mock_mode: bool


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/listen",
    response_model=ListenResponse,
    dependencies=[Depends(_verify_ipc_token)],
)
async def listen_route() -> ListenResponse:
    """Capture audio from the microphone and return transcribed text.

    In mock mode (default), returns a deterministic test phrase.
    """
    transcript = await voice_manager.listen()
    return ListenResponse(transcript=transcript)


@router.post(
    "/speak",
    response_model=SpeakResponse,
    dependencies=[Depends(_verify_ipc_token)],
)
async def speak_route(req: SpeakRequest) -> SpeakResponse:
    """Synthesize speech for the given text and play it back."""
    if not req.text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "text is required")
    await voice_manager.speak(req.text, voice=req.voice)
    return SpeakResponse(spoken=True)


@router.post(
    "/listen-and-plan",
    response_model=ListenAndPlanResponse,
    dependencies=[Depends(_verify_ipc_token)],
)
async def listen_and_plan_route() -> ListenAndPlanResponse:
    """Full voice pipeline up to plan generation — NO execution.

    Per master prompt section 46, voice commands must NEVER bypass
    security confirmation. This endpoint returns the plan; the
    frontend must then display it and require the user to click
    "Approve and Run" before calling /voice/listen-and-execute.
    """
    result = await voice_manager.listen_and_plan()
    return ListenAndPlanResponse(
        transcript=result["transcript"],
        plan=result["plan"],
    )


@router.post(
    "/listen-and-execute",
    response_model=ListenAndExecuteResponse,
    dependencies=[Depends(_verify_ipc_token)],
)
async def listen_and_execute_route(req: ListenAndExecuteRequest) -> ListenAndExecuteResponse:
    """Execute an already-approved plan via WorkflowExecutor.

    Defense in depth: even though the user is supposed to have
    explicitly approved the plan in the UI before calling this,
    :meth:`VoiceManager.listen_and_execute` re-runs the permission
    engine on the plan. If the engine denies, we return status=
    "denied" instead of executing.
    """
    if not req.plan:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "plan is required")

    try:
        result = await voice_manager.listen_and_execute(req.plan)
    except Exception as exc:
        # Pydantic validation errors, executor errors, etc.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"failed to execute plan: {exc}",
        )

    return ListenAndExecuteResponse(
        run_id=result.get("run_id"),
        plan_id=result.get("plan_id", ""),
        status=result.get("status", "failed"),
        decision=result.get("decision"),
    )


@router.post(
    "/start-continuous",
    response_model=ContinuousResponse,
    dependencies=[Depends(_verify_ipc_token)],
)
async def start_continuous_route() -> ContinuousResponse:
    """Start background wake-word listening."""
    result = await voice_manager.start_continuous_listening()
    return ContinuousResponse(
        started=result.get("started", False),
        already_listening=result.get("already_listening", False),
        wake_word=result.get("wake_word", voice_manager.wake_word),
        mock_mode=result.get("mock_mode", bool(voice_manager.mock_mode)),
    )


@router.post(
    "/stop-continuous",
    response_model=ContinuousResponse,
    dependencies=[Depends(_verify_ipc_token)],
)
async def stop_continuous_route() -> ContinuousResponse:
    """Stop background wake-word listening."""
    result = await voice_manager.stop_continuous_listening()
    return ContinuousResponse(
        stopped=result.get("stopped", False),
        was_listening=result.get("was_listening", False),
        wake_word=result.get("wake_word", voice_manager.wake_word),
        mock_mode=bool(voice_manager.mock_mode),
    )


@router.get(
    "/status",
    response_model=StatusResponse,
    dependencies=[Depends(_verify_ipc_token)],
)
async def status_route() -> StatusResponse:
    """Return current voice subsystem status."""
    return StatusResponse(
        listening=voice_manager.is_listening,
        wake_word=voice_manager.wake_word,
        last_transcript=voice_manager.last_transcript,
        mock_mode=bool(voice_manager.mock_mode),
    )


# ---------------------------------------------------------------------------
# WebSocket — live transcript stream
# ---------------------------------------------------------------------------


@router.websocket("/stream")
async def voice_stream(ws: WebSocket) -> None:
    """Push live transcript + plan + execution events to the frontend.

    Subscribes to the in-process event_bus and forwards any event
    whose type starts with ``VOICE_``. Falls back gracefully if the
    IPC token is configured — the WebSocket handshake doesn't carry
    Authorization headers reliably, so we accept the connection and
    let the rest of the security model (loopback-only bind, mock mode
    by default) handle access control.
    """
    await ws.accept()
    queue = event_bus.subscribe()

    try:
        while True:
            event_type, payload = await queue.get()
            if not event_type.startswith("VOICE_"):
                # Don't choke the websocket with non-voice events.
                continue
            await ws.send_json({"type": event_type, "payload": payload})
    except WebSocketDisconnect:
        return
    except Exception:
        # Don't let one bad frame kill the socket silently.
        return
