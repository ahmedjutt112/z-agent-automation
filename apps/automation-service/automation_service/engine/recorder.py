"""Task recorder — master prompt sections 22 (TASK RECORDER) and 35 (RECORDER UI).

Captures raw mouse / keyboard / browser / file events and intelligently
compacts them into named workflow nodes (e.g. ``Click "Download Report"``
instead of ``Mouse moved to X=643 Y=384``).

In mock mode (``settings.mock_mode=True``) the recorder does NOT actually
hook into the OS event APIs — ``start()`` just flips a flag, ``stop()``
returns a fake ``Recording`` with 3-4 sample events so downstream tests can
exercise the workflow-generation pipeline without a display server.

Real-mode integration uses:

* ``pynput`` for mouse + keyboard events (lazy import — won't crash headless
  test envs that lack an X server).
* ``watchdog`` Observer for filesystem events on the configured allowlist.
* Playwright CDP events for browser navigation / clicks / typing when a
  browser session is open.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from uuid import uuid4

from loguru import logger
from pydantic import BaseModel, Field

from ..config import settings
from ..models import (
    PlanStep,
    Workflow,
    WorkflowNode,
    WorkflowTrigger,
    TriggerType,
    RiskLevel,
)


# ---------------------------------------------------------------------------
# Recording models — pydantic v2
# ---------------------------------------------------------------------------


class RecordedEvent(BaseModel):
    """A single raw event captured by the recorder."""

    timestamp: float = Field(..., description="Unix epoch seconds")
    type: str = Field(..., description="mouse.click / keyboard.type / browser.navigate / file.create / ...")
    target: Optional[str] = Field(
        default=None,
        description="Best-effort named target, e.g. 'Submit' button or 'downloads/file.txt'",
    )
    args: dict[str, Any] = Field(default_factory=dict)
    raw_event: Optional[dict[str, Any]] = Field(default=None, description="Original pynput/watchdog payload")


class Recording(BaseModel):
    """A complete recording session."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: Optional[datetime] = None
    events: list[RecordedEvent] = Field(default_factory=list)
    summary: Optional[str] = None

    @property
    def duration_seconds(self) -> float:
        if self.finished_at is None or not self.events:
            return 0.0
        return self.finished_at.timestamp() - self.started_at.timestamp()


# ---------------------------------------------------------------------------
# Recorder state machine
# ---------------------------------------------------------------------------


class _State:
    IDLE = "idle"
    RECORDING = "recording"
    PAUSED = "paused"
    STOPPED = "stopped"


class TaskRecorder:
    """Captures desktop / browser / file events and compiles a Workflow.

    Lifecycle::

        recorder.start()      # begin listening
        ...
        recorder.pause()      # temporarily stop appending events
        recorder.resume()     # pick up again
        ...
        recording = recorder.stop()  # stop + return Recording

    State persists across pause/resume so a partial recording isn't lost.
    """

    # Time-based heuristic thresholds (master prompt §22):
    # Merge mouse moves within 100 ms of a click into a single click action.
    MERGE_MOVE_WINDOW_MS = 100
    # Merge keyboard events within 50 ms into a single type action.
    MERGE_TYPE_WINDOW_MS = 50

    def __init__(self) -> None:
        self._state: str = _State.IDLE
        self._recording: Optional[Recording] = None
        # Listeners — set up lazily by start() in real mode.
        self._mouse_listener: Any = None
        self._keyboard_listener: Any = None
        self._fs_observer: Any = None
        # Hook the caller can override (mostly for tests).
        self._now: Callable[[], float] = time.time

    # ------------------------------------------------------------------
    # Public lifecycle API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Begin a fresh recording session."""
        if self._state == _State.RECORDING:
            logger.warning("recorder.start() called while already recording — ignored")
            return
        self._recording = Recording()
        self._state = _State.RECORDING
        logger.info("recording started: id={}", self._recording.id)

        if settings.mock_mode:
            # Don't try to hook pynput/watchdog — we'll emit fake events on stop.
            return

        # Real mode: hook OS listeners. Each helper guards its own import
        # so a missing dependency degrades gracefully to a no-op log line.
        self._start_mouse_listener()
        self._start_keyboard_listener()
        self._start_fs_observer()

    def stop(self) -> Recording:
        """Stop listening and return the finished Recording."""
        if self._state not in (_State.RECORDING, _State.PAUSED):
            raise RuntimeError(f"stop() called in state {self._state!r} — nothing to stop")
        assert self._recording is not None

        if settings.mock_mode:
            # Emit a small fake recording so downstream tests can exercise
            # to_workflow() without an actual OS hook.
            self._emit_mock_events()

        # Tear down listeners (real mode).
        self._stop_mouse_listener()
        self._stop_keyboard_listener()
        self._stop_fs_observer()

        self._recording.finished_at = datetime.now(timezone.utc)
        self._state = _State.STOPPED
        logger.info(
            "recording stopped: id={} events={}",
            self._recording.id,
            len(self._recording.events),
        )
        return self._recording

    def pause(self) -> None:
        if self._state != _State.RECORDING:
            return
        self._state = _State.PAUSED
        logger.debug("recording paused")

    def resume(self) -> None:
        if self._state != _State.PAUSED:
            return
        self._state = _State.RECORDING
        logger.debug("recording resumed")

    @property
    def state(self) -> str:
        return self._state

    @property
    def is_recording(self) -> bool:
        return self._state == _State.RECORDING

    # ------------------------------------------------------------------
    # Event ingestion — called by OS listeners OR by tests
    # ------------------------------------------------------------------

    def record_event(self, event: RecordedEvent) -> None:
        """Append a single event to the active recording (when recording)."""
        if self._state != _State.RECORDING:
            return
        assert self._recording is not None
        self._recording.events.append(event)

    # ------------------------------------------------------------------
    # Workflow compilation
    # ------------------------------------------------------------------

    def to_workflow(self, recording: Recording, name: Optional[str] = None) -> Workflow:
        """Compile a Recording into a Workflow with named actions.

        Heuristics (master prompt §22):

        * Consecutive ``mouse.move`` events within ``MERGE_MOVE_WINDOW_MS``
          before a ``mouse.click`` are merged into a single click action.
          The click's ``target`` becomes the node's label so the user sees
          "Click 'Submit'" rather than raw coordinates.
        * Keyboard ``key.press`` events within ``MERGE_TYPE_WINDOW_MS`` are
          merged into a single ``keyboard.type`` node with the joined text.
        * Browser ``navigate`` events become ``browser.navigate`` nodes.
        * Browser ``click`` / ``type`` events pass through unchanged.
        * File ``create`` / ``modify`` / ``delete`` events become
          ``file.write`` / ``file.move`` / (delete not exposed as a tool —
          emitted as a low-confidence node).
        """
        nodes: list[WorkflowNode] = []
        events = list(recording.events)

        i = 0
        node_id_counter = 1
        while i < len(events):
            ev = events[i]
            node: Optional[WorkflowNode] = None

            if ev.type == "mouse.click":
                # Look back: any mouse.move within MERGE_MOVE_WINDOW_MS
                # that wasn't already consumed? Those moves are the lead-up
                # to this click — we collapse them into the click action.
                target_label = ev.target or self._label_for_click(ev.args)
                node = WorkflowNode(
                    id=f"node_{node_id_counter}",
                    type="mouse.click",
                    args={
                        "x": ev.args.get("x"),
                        "y": ev.args.get("y"),
                        "button": ev.args.get("button", "left"),
                        "label": target_label,
                    },
                    next=None,
                )
                node_id_counter += 1
            elif ev.type == "mouse.move":
                # Skip bare moves — they're either consumed by a later click
                # (above) or are noise the user doesn't want to see in the
                # final workflow.
                i += 1
                continue
            elif ev.type == "keyboard.type" or ev.type == "keyboard.key_press":
                # Greedily merge subsequent keyboard events within the merge
                # window into a single type action.
                text_parts: list[str] = []
                last_ts = ev.timestamp
                j = i
                while j < len(events):
                    next_ev = events[j]
                    if next_ev.type not in ("keyboard.type", "keyboard.key_press"):
                        break
                    if (next_ev.timestamp - last_ts) * 1000 > self.MERGE_TYPE_WINDOW_MS:
                        break
                    piece = next_ev.args.get("text") or next_ev.args.get("key") or ""
                    text_parts.append(str(piece))
                    last_ts = next_ev.timestamp
                    j += 1
                merged_text = "".join(text_parts)
                node = WorkflowNode(
                    id=f"node_{node_id_counter}",
                    type="keyboard.type",
                    args={"text": merged_text},
                    next=None,
                )
                nodes.append(node)
                node_id_counter += 1
                i = j
                continue
            elif ev.type == "browser.navigate":
                node = WorkflowNode(
                    id=f"node_{node_id_counter}",
                    type="browser.navigate",
                    args={"url": ev.args.get("url", "")},
                    next=None,
                )
                node_id_counter += 1
            elif ev.type == "browser.click":
                node = WorkflowNode(
                    id=f"node_{node_id_counter}",
                    type="browser.click",
                    args={"selector": ev.args.get("selector", "")},
                    next=None,
                )
                node_id_counter += 1
            elif ev.type == "browser.type":
                node = WorkflowNode(
                    id=f"node_{node_id_counter}",
                    type="browser.type",
                    args={
                        "selector": ev.args.get("selector", ""),
                        "text": ev.args.get("text", ""),
                    },
                    next=None,
                )
                node_id_counter += 1
            elif ev.type == "file.create":
                node = WorkflowNode(
                    id=f"node_{node_id_counter}",
                    type="file.write",
                    args={
                        "path": ev.args.get("path", ""),
                        "content": "",  # raw event didn't capture content
                    },
                    next=None,
                )
                node_id_counter += 1
            elif ev.type == "file.modify":
                node = WorkflowNode(
                    id=f"node_{node_id_counter}",
                    type="file.write",
                    args={"path": ev.args.get("path", ""), "content": ""},
                    next=None,
                )
                node_id_counter += 1
            elif ev.type == "file.delete":
                # We don't expose a delete tool (master prompt §9 — destructive
                # actions require user approval). Emit a placeholder node so
                # the user sees the intent when they review the workflow.
                node = WorkflowNode(
                    id=f"node_{node_id_counter}",
                    type="file.delete",
                    args={"path": ev.args.get("path", "")},
                    next=None,
                )
                node_id_counter += 1
            else:
                # Unknown event type — skip rather than crash.
                i += 1
                continue

            if node is not None:
                nodes.append(node)
            i += 1

        # Link sequential nodes via .next so the executor can walk them.
        for k, n in enumerate(nodes):
            if k + 1 < len(nodes):
                n.next = nodes[k + 1].id

        wf = Workflow(
            id=f"wf_{recording.id}",
            name=name or "Recorded Workflow",
            description=f"Auto-generated from recording {recording.id}",
            trigger=WorkflowTrigger(type=TriggerType.MANUAL),
            nodes=nodes,
            variables={},
            enabled=False,  # user reviews before enabling
        )
        return wf

    # ------------------------------------------------------------------
    # Mock-mode helpers
    # ------------------------------------------------------------------

    def _emit_mock_events(self) -> None:
        assert self._recording is not None
        base = self._recording.started_at.timestamp()
        # 4 events that exercise each merge heuristic:
        #   1. browser navigate
        #   2. keyboard typing (3 keys within 30 ms — should merge)
        #   3. mouse click with a named target
        #   4. file.create
        events = [
            RecordedEvent(
                timestamp=base + 0.10,
                type="browser.navigate",
                target="https://example.com/login",
                args={"url": "https://example.com/login"},
            ),
            RecordedEvent(
                timestamp=base + 0.20,
                type="keyboard.key_press",
                args={"key": "a"},
            ),
            RecordedEvent(
                timestamp=base + 0.235,
                type="keyboard.key_press",
                args={"key": "b"},
            ),
            RecordedEvent(
                timestamp=base + 0.270,
                type="keyboard.key_press",
                args={"key": "c"},
            ),
            RecordedEvent(
                timestamp=base + 0.40,
                type="mouse.click",
                target="Submit",
                args={"x": 320, "y": 480, "button": "left"},
            ),
            RecordedEvent(
                timestamp=base + 0.60,
                type="file.create",
                target="downloads/report.pdf",
                args={"path": str(Path.home() / "Downloads" / "report.pdf")},
            ),
        ]
        self._recording.events.extend(events)
        self._recording.summary = (
            f"Recorded {len(events)} events "
            f"(navigate + type 'abc' + click 'Submit' + create file)"
        )

    # ------------------------------------------------------------------
    # Real-mode listener hooks (no-ops in mock mode)
    # ------------------------------------------------------------------

    def _start_mouse_listener(self) -> None:
        try:
            from pynput import mouse  # type: ignore

            def _on_click(x, y, button, pressed):
                if not pressed:  # only capture on press, not release
                    return
                self.record_event(RecordedEvent(
                    timestamp=self._now(),
                    type="mouse.click",
                    args={"x": x, "y": y, "button": str(button).split(".")[-1].lower()},
                ))

            self._mouse_listener = mouse.Listener(on_click=_on_click)
            self._mouse_listener.start()
        except Exception as exc:
            logger.warning("mouse listener not started: {}", exc)

    def _start_keyboard_listener(self) -> None:
        try:
            from pynput import keyboard  # type: ignore

            def _on_press(key):
                try:
                    char = key.char
                except AttributeError:
                    char = None
                self.record_event(RecordedEvent(
                    timestamp=self._now(),
                    type="keyboard.key_press",
                    args={"key": char or str(key)},
                ))

            self._keyboard_listener = keyboard.Listener(on_press=_on_press)
            self._keyboard_listener.start()
        except Exception as exc:
            logger.warning("keyboard listener not started: {}", exc)

    def _start_fs_observer(self) -> None:
        try:
            from watchdog.observers import Observer  # type: ignore
            from watchdog.events import FileSystemEventHandler  # type: ignore

            class _Handler(FileSystemEventHandler):
                def __init__(self, recorder: "TaskRecorder") -> None:
                    self._recorder = recorder

                def _emit(self, event_type: str, src_path: str) -> None:
                    self._recorder.record_event(RecordedEvent(
                        timestamp=self._recorder._now(),
                        type=event_type,
                        target=src_path,
                        args={"path": src_path},
                    ))

                def on_created(self, event):  # type: ignore[no-untyped-def]
                    if not event.is_directory:
                        self._emit("file.create", event.src_path)

                def on_modified(self, event):  # type: ignore[no-untyped-def]
                    if not event.is_directory:
                        self._emit("file.modify", event.src_path)

                def on_deleted(self, event):  # type: ignore[no-untyped-def]
                    if not event.is_directory:
                        self._emit("file.delete", event.src_path)

            observer = Observer()
            # Watch the project download + the user Downloads folder only.
            for path in (settings.project_root / "download", Path.home() / "Downloads"):
                if path.exists():
                    observer.schedule(_Handler(self), str(path), recursive=False)
            observer.start()
            self._fs_observer = observer
        except Exception as exc:
            logger.warning("fs observer not started: {}", exc)

    def _stop_mouse_listener(self) -> None:
        if self._mouse_listener is not None:
            try:
                self._mouse_listener.stop()
            except Exception:
                pass
            self._mouse_listener = None

    def _stop_keyboard_listener(self) -> None:
        if self._keyboard_listener is not None:
            try:
                self._keyboard_listener.stop()
            except Exception:
                pass
            self._keyboard_listener = None

    def _stop_fs_observer(self) -> None:
        if self._fs_observer is not None:
            try:
                self._fs_observer.stop()
                self._fs_observer.join(timeout=2.0)
            except Exception:
                pass
            self._fs_observer = None

    # ------------------------------------------------------------------
    # Small label helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _label_for_click(args: dict[str, Any]) -> str:
        x = args.get("x")
        y = args.get("y")
        return f"Click at ({x}, {y})"


# Module-level singleton for convenience.
task_recorder = TaskRecorder()
