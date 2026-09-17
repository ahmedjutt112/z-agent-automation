"""VoiceManager — master prompt section 46 (Voice Control).

Implements the voice pipeline:

    Microphone -> Speech-to-Text -> AI Planner -> Permission Engine
             -> Automation Engine

CRITICAL: voice commands NEVER bypass the security confirmation flow.
``listen_and_plan`` returns the plan WITHOUT executing it; the frontend
must call ``listen_and_execute`` only after the user clicks "Approve and
Run" in the modal.

Design notes
------------

* All third-party dependencies (``sounddevice``, ``soundfile``,
  ``z-ai-web-dev-sdk`` Node CLI, ``zai`` console script) are imported
  lazily inside the methods that actually need them. This keeps mock
  mode (the default in tests and the production default) fully
  functional without any audio hardware / native libs / Node runtime
  installed.
* Mock mode is the project-wide safe default (master prompt section 64).
  When ``settings.mock_mode`` is True, every method returns
  deterministic fake data and never touches the microphone, speaker,
  or external SDK.
* Real-mode STT / TTS are implemented via the ``z-ai`` CLI (shipped
  with the z-ai-web-dev-sdk npm package). Using the CLI keeps the
  Python service dependency-free while still hitting the real Z.ai
  cloud ASR / TTS APIs. We fall back to ``sounddevice`` + WAV file
  capture if a real microphone is required.
"""
from __future__ import annotations

import asyncio
import base64
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from loguru import logger

from ..config import settings
from ..engine.event_bus import event_bus


# Canonical mock phrase — used everywhere a deterministic transcript is
# needed in mock mode. Tests assert against this exact string.
_MOCK_PHRASE = "open chrome and search for AI automation"

# Default wake word — section 46 implies a "computer, ..." style wake
# activation. Overridable via :meth:`set_wake_word`.
_DEFAULT_WAKE_WORD = "computer"

# z-ai CLI binary — looked up once on the first real-mode call.
_ZAI_BIN_CACHE: Optional[str] = None


def _find_zai_cli() -> Optional[str]:
    """Return the path to the ``z-ai`` CLI binary, or None if not found.

    Cached after the first lookup so repeated real-mode calls don't
    re-shell out to ``shutil.which``.
    """
    global _ZAI_BIN_CACHE
    if _ZAI_BIN_CACHE is not None:
        return _ZAI_BIN_CACHE
    _ZAI_BIN_CACHE = shutil.which("z-ai")
    return _ZAI_BIN_CACHE


class VoiceManager:
    """High-level voice control surface for the automation service.

    All methods are async and safe to call from the FastAPI event loop.
    In mock mode (default), no audio hardware is touched — every call
    returns deterministic fake data.
    """

    def __init__(self) -> None:
        # Wake word ("computer" by default) — used by
        # start_continuous_listening to gate command capture.
        self.wake_word: str = _DEFAULT_WAKE_WORD
        # Continuous listening state — read by the /voice/status route
        # and mutated by start_continuous_listening / stop_continuous_listening.
        self._listening: bool = False
        # Background asyncio task polling the microphone for wake word +
        # command phrases.
        self._continuous_task: Optional[asyncio.Task[None]] = None
        # Last transcript captured by either listen() or the continuous
        # loop. Mirrored onto /voice/status so the UI can display it.
        self.last_transcript: Optional[str] = None
        # Lazily-initialized SDK handles. None means "not yet loaded".
        self._stt_client: Any = None
        self._tts_client: Any = None
        # Optional path to a WAV file used by listen() in real mode when
        # microphone capture is unavailable. Set via set_wav_source()
        # (used by tests + a future /voice/upload endpoint).
        self._wav_source: Optional[Path] = None

    # ------------------------------------------------------------------
    # Public configuration helpers
    # ------------------------------------------------------------------

    def set_wake_word(self, word: str) -> None:
        """Update the wake word. Trims + lowercases the input."""
        if not word or not word.strip():
            raise ValueError("wake word must be a non-empty string")
        self.wake_word = word.strip().lower()
        logger.info("voice wake word set to '{}'", self.wake_word)

    def set_wav_source(self, path: Path | str | None) -> None:
        """Set a fallback WAV file source for real-mode STT.

        Used when microphone capture is unavailable (headless server,
        CI sandbox). Pass None to clear the override and force
        sounddevice capture.
        """
        self._wav_source = Path(path) if path else None

    @property
    def is_listening(self) -> bool:
        return self._listening

    @property
    def mock_mode(self) -> bool:
        return bool(settings.mock_mode)

    # ------------------------------------------------------------------
    # Core pipeline primitives
    # ------------------------------------------------------------------

    async def listen(self, timeout_seconds: int = 10) -> str:
        """Capture audio from the microphone and return transcribed text.

        * Mock mode: returns the deterministic :data:`_MOCK_PHRASE`
          immediately, with no hardware access.
        * Real mode: records a WAV chunk via ``sounddevice`` (16kHz mono),
          then invokes the ``z-ai asr`` CLI to transcribe. If
          ``sounddevice`` is missing or no microphone is available,
          falls back to the configured WAV source (see
          :meth:`set_wav_source`). If neither is available, raises
          ``RuntimeError`` with a helpful install message.
        """
        if settings.mock_mode:
            logger.debug("voice listen() in mock mode -> '{}'", _MOCK_PHRASE)
            self.last_transcript = _MOCK_PHRASE
            event_bus.publish(
                "VOICE_TRANSCRIPT_RECEIVED",
                {"transcript": _MOCK_PHRASE, "mock": True},
            )
            return _MOCK_PHRASE

        # Real mode — record + transcribe.
        wav_path = await self._capture_audio(timeout_seconds)
        try:
            transcript = await self._transcribe_file(wav_path)
        finally:
            # Clean up the temp WAV unless the caller explicitly set
            # it as the source (in which case we don't own it).
            if self._wav_source is None:
                try:
                    wav_path.unlink(missing_ok=True)
                except Exception:
                    pass

        transcript = (transcript or "").strip()
        if not transcript:
            logger.warning("voice listen() returned empty transcript")
        self.last_transcript = transcript
        event_bus.publish(
            "VOICE_TRANSCRIPT_RECEIVED",
            {"transcript": transcript, "mock": False},
        )
        return transcript

    async def speak(self, text: str, voice: str = "default") -> None:
        """Synthesize speech for the given text and play it back.

        * Mock mode: logs the text and returns immediately.
        * Real mode: invokes the ``z-ai tts`` CLI to generate a WAV,
          then plays it via ``sounddevice``. If ``sounddevice`` is
          missing, the audio file is still written to a temp path and
          the user is notified of the path via a log message.
        """
        if not text:
            return

        if settings.mock_mode:
            logger.info("voice speak() mock: text='{}' voice='{}'", text, voice)
            return

        # Real mode — synthesize via z-ai TTS CLI.
        out_path = Path(tempfile.gettempdir()) / f"zai_tts_{uuid4().hex}.wav"
        try:
            await self._synthesize_text(text, out_path, voice)
            await self._play_audio_file(out_path)
        finally:
            try:
                out_path.unlink(missing_ok=True)
            except Exception:
                pass

    async def listen_and_plan(self) -> dict[str, Any]:
        """Full pipeline up to plan generation — NO execution.

        Per section 46, voice commands must NEVER bypass security
        confirmation. This method:

        1. ``listen()`` → transcribed text
        2. ``PlannerAgent.plan(text)`` → structured :class:`Plan`
        3. Returns ``{transcript, plan}`` to the caller

        The frontend is responsible for displaying the plan and
        requiring the user to click "Approve and Run" before invoking
        :meth:`listen_and_execute`.
        """
        transcript = await self.listen()

        # Lazy import to avoid pulling the AI provider stack into the
        # voice module import path (keeps mock-mode startup fast).
        from ..agents.planner import PlannerAgent

        planner = PlannerAgent()
        plan = await planner.plan(transcript)

        event_bus.publish(
            "VOICE_PLAN_GENERATED",
            {
                "transcript": transcript,
                "plan_id": str(plan.id),
                "goal": plan.goal,
                "steps_count": len(plan.steps),
                "overall_risk": plan.overall_risk.value
                if hasattr(plan.overall_risk, "value")
                else str(plan.overall_risk),
                "mock": bool(settings.mock_mode),
            },
        )

        return {
            "transcript": transcript,
            "plan": plan.model_dump(mode="json"),
        }

    async def listen_and_execute(self, approved_plan: dict[str, Any]) -> dict[str, Any]:
        """Execute an already-approved plan via WorkflowExecutor.

        Per section 46, this method MUST only be called after the user
        has explicitly approved the plan in the UI. The permission
        engine is still invoked inside WorkflowExecutor (defense in
        depth) — even if a caller bypasses the UI, the engine will
        re-evaluate risk levels and emit ``USER_APPROVAL_REQUIRED``
        events for HIGH / CRITICAL plans.
        """
        # Lazy import to avoid a circular dependency at module load.
        from ..models import Plan
        from ..engine.workflow_executor import WorkflowExecutor
        from ..security.permission_engine import permission_engine

        plan = Plan.model_validate(approved_plan)

        # Defense in depth — re-evaluate the plan through the permission
        # engine before handing it to the executor. The engine returns
        # ApprovalResponse.decision; if it's DENY, we refuse to execute.
        decision = await permission_engine.evaluate_plan(plan)
        decision_value = (
            decision.decision.value
            if hasattr(decision.decision, "value")
            else str(decision.decision)
        )
        if decision_value in {"deny", "cancel"}:
            event_bus.publish(
                "VOICE_EXECUTION_STARTED",
                {
                    "plan_id": str(plan.id),
                    "denied_by_permission_engine": True,
                    "decision": decision_value,
                },
            )
            return {
                "run_id": None,
                "plan_id": str(plan.id),
                "status": "denied",
                "decision": decision_value,
            }

        event_bus.publish(
            "VOICE_EXECUTION_STARTED",
            {
                "plan_id": str(plan.id),
                "goal": plan.goal,
                "approved": True,
                "mock": bool(settings.mock_mode),
            },
        )

        executor = WorkflowExecutor()
        run_id = await executor.execute_plan(plan)
        return {
            "run_id": run_id,
            "plan_id": str(plan.id),
            "status": "running",
        }

    # ------------------------------------------------------------------
    # Continuous listening — wake-word activation
    # ------------------------------------------------------------------

    async def start_continuous_listening(self) -> dict[str, Any]:
        """Start a background task that listens for the wake word.

        When the wake word is detected, the next utterance is captured
        and pushed to the event bus as a ``VOICE_TRANSCRIPT_RECEIVED``
        event. The frontend WebSocket picks it up and either shows a
        command input or auto-triggers :meth:`listen_and_plan`.

        In mock mode the background loop emits a single deterministic
        transcript every ``poll_interval`` seconds so the UI has
        something to display during tests.
        """
        if self._listening:
            return {
                "started": False,
                "already_listening": True,
                "wake_word": self.wake_word,
            }

        self._listening = True
        self._continuous_task = asyncio.create_task(self._continuous_loop())
        return {
            "started": True,
            "wake_word": self.wake_word,
            "mock_mode": bool(settings.mock_mode),
        }

    async def stop_continuous_listening(self) -> dict[str, Any]:
        """Stop the background wake-word loop."""
        if not self._listening:
            return {"stopped": False, "was_listening": False}

        self._listening = False
        task = self._continuous_task
        self._continuous_task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        return {"stopped": True, "wake_word": self.wake_word}

    async def _continuous_loop(self) -> None:
        """Background loop that listens for the wake word.

        In mock mode we sleep + emit a deterministic transcript every
        ~5 seconds (so the frontend gets something to render in tests).
        In real mode we poll ``listen()`` in a tight loop and only
        emit when the wake word is detected.
        """
        poll_interval = 5 if settings.mock_mode else 1
        try:
            while self._listening:
                try:
                    transcript = await self.listen(timeout_seconds=2)
                except Exception as exc:
                    logger.debug("continuous listen failed: {}", exc)
                    await asyncio.sleep(poll_interval)
                    continue

                # In mock mode, the wake word is the deterministic
                # phrase, so we just emit it as-is.
                if settings.mock_mode:
                    event_bus.publish(
                        "VOICE_TRANSCRIPT_RECEIVED",
                        {
                            "transcript": transcript,
                            "wake_word_detected": self.wake_word,
                            "mock": True,
                            "timestamp": time.time(),
                        },
                    )
                else:
                    lower = transcript.lower()
                    if self.wake_word and self.wake_word in lower:
                        cmd = lower.split(self.wake_word, 1)[-1].strip()
                        event_bus.publish(
                            "VOICE_TRANSCRIPT_RECEIVED",
                            {
                                "transcript": cmd or transcript,
                                "wake_word_detected": True,
                                "timestamp": time.time(),
                            },
                        )

                await asyncio.sleep(poll_interval)
        except asyncio.CancelledError:
            # Expected when stop_continuous_listening is called.
            pass

    # ------------------------------------------------------------------
    # Internal — audio capture / synthesis
    # ------------------------------------------------------------------

    async def _capture_audio(self, timeout_seconds: int) -> Path:
        """Record a WAV file from the microphone, or fall back to a
        pre-configured WAV source. Returns the path to the WAV.

        Raises ``RuntimeError`` with a helpful message when no audio
        source is available.
        """
        if self._wav_source is not None and self._wav_source.exists():
            return self._wav_source

        try:
            import sounddevice as sd  # type: ignore[import-not-found]
            import soundfile as sf  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "Audio capture requires 'sounddevice' + 'soundfile'. "
                "Install with: pip install sounddevice soundfile. "
                f"Original error: {exc}"
            ) from exc

        # 16kHz mono — recommended by the ASR skill (best accuracy).
        sample_rate = 16_000
        channels = 1
        out_path = Path(tempfile.gettempdir()) / f"zai_voice_{uuid4().hex}.wav"

        def _record() -> None:
            try:
                audio = sd.rec(
                    int(sample_rate * timeout_seconds),
                    samplerate=sample_rate,
                    channels=channels,
                    dtype="int16",
                )
                sd.wait()
                sf.write(str(out_path), audio, sample_rate)
            except Exception as exc:
                raise RuntimeError(f"microphone capture failed: {exc}") from exc

        try:
            await asyncio.to_thread(_record)
        except RuntimeError as exc:
            if self._wav_source is not None and self._wav_source.exists():
                logger.warning("falling back to WAV source: {}", self._wav_source)
                return self._wav_source
            raise

        return out_path

    async def _transcribe_file(self, wav_path: Path) -> str:
        """Transcribe a WAV file via the ``z-ai asr`` CLI.

        Returns the transcribed text. Raises ``RuntimeError`` if the
        CLI is not installed or returns a non-zero exit code.
        """
        cli = _find_zai_cli()
        if cli is None:
            raise RuntimeError(
                "Real-mode STT requires the 'z-ai' CLI (shipped with the "
                "z-ai-web-dev-sdk npm package). Install with: "
                "npm install -g z-ai-web-dev-sdk"
            )

        def _run() -> str:
            try:
                result = subprocess.run(
                    [cli, "asr", "--file", str(wav_path), "--stream"],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(f"ASR CLI timed out: {exc}") from exc

            if result.returncode != 0:
                raise RuntimeError(
                    f"ASR CLI failed (exit {result.returncode}): "
                    f"{result.stderr.strip() or result.stdout.strip()}"
                )
            # The CLI streams plain text to stdout in --stream mode; if
            # the user passed --output, we'd need to parse JSON. Default
            # path: stdout text.
            text = result.stdout.strip()
            # Some CLI versions print a JSON object — try to parse it.
            if text.startswith("{"):
                try:
                    return str(json.loads(text).get("text", ""))
                except json.JSONDecodeError:
                    pass
            return text

        return await asyncio.to_thread(_run)

    async def _synthesize_text(
        self, text: str, out_path: Path, voice: str = "default"
    ) -> None:
        """Generate a TTS WAV via the ``z-ai tts`` CLI.

        ``voice`` values are translated to the z-ai SDK's voice names
        (tongtong / chuichui / xiaochen / jam / kazi / douji / luodo).
        Unknown voices fall back to ``tongtong``.
        """
        cli = _find_zai_cli()
        if cli is None:
            raise RuntimeError(
                "Real-mode TTS requires the 'z-ai' CLI (shipped with the "
                "z-ai-web-dev-sdk npm package). Install with: "
                "npm install -g z-ai-web-dev-sdk"
            )

        voice_name = _VOICE_MAP.get(voice, "tongtong")

        def _run() -> None:
            try:
                result = subprocess.run(
                    [
                        cli,
                        "tts",
                        "-i",
                        text[:1024],  # API limit
                        "-o",
                        str(out_path),
                        "--voice",
                        voice_name,
                        "--format",
                        "wav",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(f"TTS CLI timed out: {exc}") from exc

            if result.returncode != 0:
                raise RuntimeError(
                    f"TTS CLI failed (exit {result.returncode}): "
                    f"{result.stderr.strip() or result.stdout.strip()}"
                )
            if not out_path.exists():
                raise RuntimeError(
                    f"TTS CLI produced no output file at {out_path}"
                )

        await asyncio.to_thread(_run)

    async def _play_audio_file(self, path: Path) -> None:
        """Play a WAV file via sounddevice. Best-effort — logs a path
        message if playback isn't available."""
        try:
            import sounddevice as sd  # type: ignore[import-not-found]
            import soundfile as sf  # type: ignore[import-not-found]
        except ImportError:
            logger.warning(
                "sounddevice not installed; TTS audio saved at {}", path
            )
            return

        def _play() -> None:
            try:
                data, sample_rate = sf.read(str(path), dtype="int16")
                sd.play(data, sample_rate)
                sd.wait()
            except Exception as exc:
                logger.warning("audio playback failed: {}", exc)

        await asyncio.to_thread(_play)


# Voice-name mapping — the z-ai SDK ships with seven voices; we expose
# a friendlier "default / male / female" surface to the UI.
_VOICE_MAP: dict[str, str] = {
    "default": "tongtong",  # warm, friendly
    "male": "xiaochen",  # calm, professional
    "female": "tongtong",  # warm, friendly
    "tongtong": "tongtong",
    "chuichui": "chuichui",
    "xiaochen": "xiaochen",
    "jam": "jam",
    "kazi": "kazi",
    "douji": "douji",
    "luodo": "luodo",
}


# Module-level singleton — mirrors the pattern used by scheduler_manager,
# permission_engine, tool_registry, kill_switch, event_bus.
voice_manager = VoiceManager()
