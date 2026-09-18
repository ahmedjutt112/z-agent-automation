"""Tests for the voice control subsystem — master prompt section 46.

Test plan
---------

1. ``test_voice_manager_listen_mock`` — VoiceManager().listen() returns
   the deterministic mock phrase in mock mode.
2. ``test_voice_manager_speak_mock`` — speak() doesn't raise in mock mode.
3. ``test_voice_manager_listen_and_plan_mock`` — listen_and_plan()
   returns ``{transcript, plan}`` without executing the plan.
4. ``test_voice_manager_listen_and_execute_mock`` — listen_and_execute()
   returns a run_id (defends the invariants even in mock mode).
5. ``test_voice_set_wake_word`` — set_wake_word() updates the wake word.
6. ``test_voice_start_stop_continuous`` — start_continuous_listening()
   then stop_continuous_listening() round-trip.
7. ``test_api_voice_listen`` — POST /voice/listen returns {transcript}.
8. ``test_api_voice_speak`` — POST /voice/speak returns {spoken: true}.
9. ``test_api_voice_listen_and_plan`` — POST /voice/listen-and-plan
   returns {transcript, plan}.
10. ``test_api_voice_status`` — GET /voice/status returns {listening,
    wake_word, mock_mode}.
11. ``test_api_voice_listen_and_execute`` — POST /voice/listen-and-execute
    with an approved plan returns run_id.
12. ``test_api_voice_start_stop_continuous`` — POST /voice/start-continuous
    then /voice/stop-continuous round-trip.

All tests run in mock mode (autouse via conftest.py).
"""
from __future__ import annotations

import asyncio

import pytest


# ---------------------------------------------------------------------------
# 1-6. VoiceManager unit tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_voice_manager() -> None:
    """Reset the singleton's state between tests so we don't bleed
    listening/transcript/wake_word across tests."""
    from automation_service.voice.manager import voice_manager

    voice_manager.wake_word = "computer"
    voice_manager._listening = False  # noqa: SLF001
    voice_manager.last_transcript = None
    voice_manager._continuous_task = None  # noqa: SLF001
    yield
    # Best-effort: cancel any lingering continuous task.
    if voice_manager._continuous_task and not voice_manager._continuous_task.done():  # noqa: SLF001
        voice_manager._continuous_task.cancel()  # noqa: SLF001
    voice_manager._listening = False  # noqa: SLF001


@pytest.mark.asyncio
async def test_voice_manager_listen_mock() -> None:
    """VoiceManager().listen() returns deterministic text in mock mode."""
    from automation_service.voice.manager import voice_manager

    transcript = await voice_manager.listen()
    assert isinstance(transcript, str)
    assert len(transcript) > 0
    # Mock mode should return the canonical phrase.
    assert transcript == "open chrome and search for AI automation"
    # last_transcript should be updated.
    assert voice_manager.last_transcript == transcript


@pytest.mark.asyncio
async def test_voice_manager_speak_mock() -> None:
    """speak() must not raise in mock mode."""
    from automation_service.voice.manager import voice_manager

    # Should complete without raising.
    await voice_manager.speak("Hello, world")
    await voice_manager.speak("Voice control is working", voice="female")


@pytest.mark.asyncio
async def test_voice_manager_listen_and_plan_mock() -> None:
    """listen_and_plan() returns {transcript, plan} without executing."""
    from automation_service.voice.manager import voice_manager

    result = await voice_manager.listen_and_plan()

    assert "transcript" in result
    assert "plan" in result
    assert isinstance(result["transcript"], str)
    assert len(result["transcript"]) > 0
    assert isinstance(result["plan"], dict)
    # The plan dict should at minimum carry goal + steps + overall_risk
    # (mirrors the Plan pydantic model).
    assert "goal" in result["plan"]
    assert "steps" in result["plan"]
    assert "overall_risk" in result["plan"]
    # CRITICAL invariant — listen_and_plan must NOT execute the plan.
    # The plan must be returned to the caller for explicit approval.
    assert "run_id" not in result


@pytest.mark.asyncio
async def test_voice_manager_listen_and_execute_mock() -> None:
    """listen_and_execute() returns a run_id for an approved plan."""
    from automation_service.voice.manager import voice_manager

    # First generate a plan via listen_and_plan, then execute it.
    plan_result = await voice_manager.listen_and_plan()
    approved_plan = plan_result["plan"]

    exec_result = await voice_manager.listen_and_execute(approved_plan)
    assert "run_id" in exec_result
    assert exec_result["run_id"] is not None
    assert len(exec_result["run_id"]) > 0
    assert exec_result["status"] in {"running", "completed", "failed"}


def test_voice_set_wake_word() -> None:
    """set_wake_word() updates the wake word on the singleton."""
    from automation_service.voice.manager import voice_manager

    assert voice_manager.wake_word == "computer"
    voice_manager.set_wake_word("Jarvis")
    assert voice_manager.wake_word == "jarvis"  # lowercased

    # Empty wake word should be rejected.
    with pytest.raises(ValueError):
        voice_manager.set_wake_word("")
    with pytest.raises(ValueError):
        voice_manager.set_wake_word("   ")

    # Wake word should be unchanged after the failed call.
    assert voice_manager.wake_word == "jarvis"


@pytest.mark.asyncio
async def test_voice_start_stop_continuous() -> None:
    """start_continuous_listening then stop_continuous_listening round-trip."""
    from automation_service.voice.manager import voice_manager

    # Start — should return {started: True, ...}.
    start_result = await voice_manager.start_continuous_listening()
    assert start_result["started"] is True
    assert voice_manager.is_listening is True

    # Stop — should return {stopped: True, ...}.
    stop_result = await voice_manager.stop_continuous_listening()
    assert stop_result["stopped"] is True
    assert voice_manager.is_listening is False


# ---------------------------------------------------------------------------
# 7-11. FastAPI route tests (use the shared `client` fixture from conftest.py)
# ---------------------------------------------------------------------------


def test_api_voice_listen(client) -> None:
    """POST /voice/listen returns {transcript: ...}."""
    r = client.post("/voice/listen")
    assert r.status_code == 200
    body = r.json()
    assert "transcript" in body
    assert isinstance(body["transcript"], str)
    assert len(body["transcript"]) > 0


def test_api_voice_speak(client) -> None:
    """POST /voice/speak returns {spoken: true}."""
    r = client.post("/voice/speak", json={"text": "Hello world", "voice": "default"})
    assert r.status_code == 200
    body = r.json()
    assert body["spoken"] is True


def test_api_voice_listen_and_plan(client) -> None:
    """POST /voice/listen-and-plan returns {transcript, plan}."""
    r = client.post("/voice/listen-and-plan")
    assert r.status_code == 200
    body = r.json()
    assert "transcript" in body
    assert "plan" in body
    assert isinstance(body["plan"], dict)
    assert "goal" in body["plan"]
    assert "steps" in body["plan"]


def test_api_voice_status(client) -> None:
    """GET /voice/status returns {listening, wake_word, mock_mode}."""
    r = client.get("/voice/status")
    assert r.status_code == 200
    body = r.json()
    assert "listening" in body
    assert "wake_word" in body
    assert "mock_mode" in body
    # mock_mode should be True in tests (conftest pins it).
    assert body["mock_mode"] is True
    # Default wake word should be "computer".
    assert body["wake_word"] == "computer"


def test_api_voice_listen_and_execute(client) -> None:
    """POST /voice/listen-and-execute with an approved plan returns run_id."""
    # First generate a plan via listen-and-plan.
    plan_resp = client.post("/voice/listen-and-plan")
    assert plan_resp.status_code == 200
    plan = plan_resp.json()["plan"]

    # Now execute it.
    exec_resp = client.post("/voice/listen-and-execute", json={"plan": plan})
    assert exec_resp.status_code == 200
    body = exec_resp.json()
    assert "run_id" in body
    assert body["run_id"] is not None
    assert body["status"] in {"running", "completed", "failed"}


def test_api_voice_start_stop_continuous(client) -> None:
    """POST /voice/start-continuous then /voice/stop-continuous round-trip."""
    start = client.post("/voice/start-continuous")
    assert start.status_code == 200
    start_body = start.json()
    assert start_body["started"] is True

    # Verify status reflects listening state.
    status_resp = client.get("/voice/status")
    assert status_resp.status_code == 200
    assert status_resp.json()["listening"] is True

    stop = client.post("/voice/stop-continuous")
    assert stop.status_code == 200
    stop_body = stop.json()
    assert stop_body["stopped"] is True

    # Verify status reflects stopped state.
    status_after = client.get("/voice/status")
    assert status_after.status_code == 200
    assert status_after.json()["listening"] is False
