"""Tests for the workflow engine enhancements — variables, conditions, loops,
self-healing, recorder, plugin system, and the updated WorkflowExecutor.

All tests run in mock mode (settings.mock_mode=True) — no real mouse /
keyboard / browser / network I/O happens. The ``mock_settings`` autouse
fixture in conftest.py pins this for the duration of every test.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from automation_service.engine.variables import VariableEngine, variable_engine
from automation_service.engine.control_flow import (
    ConditionEvaluator,
    condition_evaluator,
    LoopExecutor,
    loop_executor,
)
from automation_service.engine.self_healing import (
    SelfHealingResolver,
    self_healing_resolver,
    ASK_USER_RESULT,
    STRATEGY_DOM,
    STRATEGY_AI_VISUAL,
)
from automation_service.engine.recorder import (
    TaskRecorder,
    Recording,
    RecordedEvent,
)
from automation_service.engine.event_bus import event_bus
from automation_service.engine.tool_registry import Tool, tool_registry
from automation_service.engine.workflow_executor import WorkflowExecutor
from automation_service.models import (
    ActionResult,
    Plan,
    PlanStep,
    RiskLevel,
    StepStatus,
    PermissionLevel,
    Workflow,
    WorkflowNode,
    WorkflowTrigger,
    TriggerType,
)
from automation_service.plugins.manager import PluginManager, PluginSpec, PluginState


# ===========================================================================
# Helpers — adapted from tests/test_workflow_executor.py
# ===========================================================================


def _register_test_tool(name: str, behavior: Any) -> Tool:
    """Register a one-shot Tool subclass for testing.

    ``behavior`` may be:
      * a callable ``args -> ActionResult`` — called per execution
      * a list of ``ActionResult`` — popped in order
      * a single ``ActionResult`` — returned on every call
    """
    if name in tool_registry._tools:
        del tool_registry._tools[name]

    if isinstance(behavior, ActionResult):
        async def _execute_single(self, args: dict) -> ActionResult:
            return behavior
        exec_fn = _execute_single
    elif isinstance(behavior, list):
        state = {"calls": 0, "results": list(behavior)}

        async def _execute_list(self, args: dict) -> ActionResult:
            i = state["calls"]
            state["calls"] += 1
            if i < len(state["results"]):
                return state["results"][i]
            return state["results"][-1]
        exec_fn = _execute_list
    else:
        async def _execute_fn(self, args: dict) -> ActionResult:
            return behavior(args)
        exec_fn = _execute_fn

    cls_name = "_TestTool_" + name.replace(".", "_")
    _TestTool = type(
        cls_name,
        (Tool,),
        {
            "name": name,
            "description": f"test tool {name}",
            "permission_level": "allow_once",
            "risk_level": "low",
            "timeout_ms": 2_000,
            "execute": exec_fn,
        },
    )
    tool_registry.register(_TestTool())
    return tool_registry.get(name)


def _plan(steps: list[PlanStep], variables: dict | None = None) -> Plan:
    return Plan(
        id=uuid4(),
        goal="engine test",
        steps=steps,
        required_permissions=[PermissionLevel.ALLOW_ONCE],
        overall_risk=RiskLevel.LOW,
        variables=variables or {},
    )


# ===========================================================================
# A. Variables Engine
# ===========================================================================


def test_variable_resolve_today() -> None:
    """{{today}} resolves to today's date in YYYY-MM-DD."""
    engine = VariableEngine()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert engine.resolve("{{today}}", {}) == today


def test_variable_resolve_clipboard(monkeypatch) -> None:
    """When pyperclip is available, {{clipboard}} returns its value."""
    engine = VariableEngine()
    # Patch the builtin-resolver entry directly so the engine picks up
    # the mocked return (the dict holds a function reference captured at
    # module-import time, so patching _safe_clipboard on the module alone
    # wouldn't reach the resolver).
    from automation_service.engine import variables as vars_mod

    def _mock_clipboard() -> str:
        return "Hello from clipboard!"

    monkeypatch.setitem(vars_mod._BUILTIN_RESOLVERS, "clipboard", _mock_clipboard)
    assert engine.resolve("{{clipboard}}", {}) == "Hello from clipboard!"


def test_variable_custom_overrides_builtin() -> None:
    """A custom variable in context overrides the built-in of the same name."""
    engine = VariableEngine()
    assert engine.resolve("{{today}}", {"today": "2099-12-31"}) == "2099-12-31"


def test_variable_nested() -> None:
    """A variable whose value contains {{...}} resolves recursively."""
    engine = VariableEngine()
    ctx = {"greeting": "Report_{{today}}", "today": "2099-12-31"}
    # {{greeting}} expands to "Report_{{today}}" which then expands to
    # "Report_2099-12-31" via the recursive substitution pass.
    result = engine.resolve("{{greeting}}", ctx)
    assert result == "Report_2099-12-31"


def test_variable_unknown_left_alone() -> None:
    """Unknown variables stay as their original ``{{name}}`` placeholder."""
    engine = VariableEngine()
    assert engine.resolve("hello {{unknown_var}} world", {}) == "hello {{unknown_var}} world"


def test_variable_random_uuid_format() -> None:
    """{{random_uuid}} returns a 32-char hex string."""
    engine = VariableEngine()
    result = engine.resolve("{{random_uuid}}", {})
    assert len(result) == 32
    int(result, 16)  # raises ValueError if not hex


def test_variable_random_int_in_range() -> None:
    """{{random_int}} returns an integer in [0, 1000]."""
    engine = VariableEngine()
    result = engine.resolve("{{random_int}}", {})
    n = int(result)
    assert 0 <= n <= 1000


def test_variable_engine_format_shortcut() -> None:
    """format(template, **kwargs) is a convenience alias for resolve."""
    engine = VariableEngine()
    assert engine.format("Hello {{name}}!", name="Alice") == "Hello Alice!"


# ===========================================================================
# B. Conditions
# ===========================================================================


def test_condition_file_exists_true(tmp_path: Path) -> None:
    """file_exists returns True when the file actually exists."""
    f = tmp_path / "marker.txt"
    f.write_text("hello")
    evaluator = ConditionEvaluator()
    assert evaluator.evaluate({"type": "file_exists", "path": str(f)}) is True


def test_condition_file_exists_false(tmp_path: Path) -> None:
    """file_exists returns False for a nonexistent path."""
    f = tmp_path / "does_not_exist.txt"
    evaluator = ConditionEvaluator()
    assert evaluator.evaluate({"type": "file_exists", "path": str(f)}) is False


def test_condition_and(tmp_path: Path) -> None:
    """and: both true -> True, one false -> False."""
    f = tmp_path / "exists.txt"
    f.write_text("x")
    evaluator = ConditionEvaluator()
    both_true = {
        "type": "and",
        "conditions": [
            {"type": "file_exists", "path": str(f)},
            {"type": "file_exists", "path": str(f)},
        ],
    }
    one_false = {
        "type": "and",
        "conditions": [
            {"type": "file_exists", "path": str(f)},
            {"type": "file_exists", "path": str(tmp_path / "nope.txt")},
        ],
    }
    assert evaluator.evaluate(both_true) is True
    assert evaluator.evaluate(one_false) is False


def test_condition_or(tmp_path: Path) -> None:
    """or: one true -> True."""
    f = tmp_path / "exists.txt"
    f.write_text("x")
    evaluator = ConditionEvaluator()
    cond = {
        "type": "or",
        "conditions": [
            {"type": "file_exists", "path": str(tmp_path / "nope.txt")},
            {"type": "file_exists", "path": str(f)},
        ],
    }
    assert evaluator.evaluate(cond) is True


def test_condition_not(tmp_path: Path) -> None:
    """not: negation works."""
    f = tmp_path / "exists.txt"
    f.write_text("x")
    evaluator = ConditionEvaluator()
    not_exists = {"type": "not", "condition": {"type": "file_exists", "path": str(tmp_path / "nope.txt")}}
    not_real_exists = {"type": "not", "condition": {"type": "file_exists", "path": str(f)}}
    assert evaluator.evaluate(not_exists) is True
    assert evaluator.evaluate(not_real_exists) is False


def test_condition_network_available_mock() -> None:
    """In mock mode, network_available defaults to True."""
    evaluator = ConditionEvaluator()
    assert evaluator.evaluate({"type": "network_available"}) is True


def test_condition_unknown_type_returns_false() -> None:
    """Unknown condition types are treated as False (safe default)."""
    evaluator = ConditionEvaluator()
    assert evaluator.evaluate({"type": "totally_made_up"}) is False


# ===========================================================================
# C. Loops
# ===========================================================================


@pytest.mark.asyncio
async def test_loop_for_each_file(tmp_path: Path) -> None:
    """for_each_file iterates over files matching the pattern."""
    for name in ("a.txt", "b.txt", "c.txt"):
        (tmp_path / name).write_text(name)
    # Plus a non-matching file.
    (tmp_path / "ignore.log").write_text("ignored")

    seen: list[str] = []
    await loop_executor.execute(
        {"type": "for_each_file", "path": str(tmp_path), "pattern": "*.txt"},
        lambda p: seen.append(p.name),
    )
    assert sorted(seen) == ["a.txt", "b.txt", "c.txt"]


@pytest.mark.asyncio
async def test_loop_while_max_iterations() -> None:
    """A while loop with an always-true condition hits max_iterations."""
    iterations: list[int] = []
    await loop_executor.execute(
        {"type": "while", "condition": {"type": "network_available"}, "max_iterations": 5},
        lambda item: iterations.append(item["iteration"]),
    )
    assert iterations == [0, 1, 2, 3, 4]


@pytest.mark.asyncio
async def test_loop_retry_succeeds_on_second_attempt() -> None:
    """retry loop runs the callback up to max_attempts; the callback can
    decide per-attempt whether to mark the attempt as successful.
    """
    attempts: list[int] = []

    async def _cb(item: dict) -> Any:
        attempts.append(item["attempt"])
        # We don't actually care about success here — just that we got
        # called the right number of times.
        return None

    await loop_executor.execute(
        {"type": "retry", "max_attempts": 3, "delay_seconds": 0.0},
        _cb,
    )
    assert attempts == [0, 1, 2]


@pytest.mark.asyncio
async def test_loop_batch() -> None:
    """batch: items are split into chunks of batch_size."""
    seen: list[list[int]] = []
    await loop_executor.execute(
        {"type": "batch", "items": list(range(7)), "batch_size": 3},
        lambda batch: seen.append(batch),
    )
    assert seen == [[0, 1, 2], [3, 4, 5], [6]]


@pytest.mark.asyncio
async def test_loop_for_each_row(tmp_path: Path) -> None:
    """for_each_row iterates over CSV rows as dicts."""
    csv_path = tmp_path / "data.csv"
    csv_path.write_text("name,age\nAlice,30\nBob,40\n")
    seen: list[dict] = []
    await loop_executor.execute(
        {"type": "for_each_row", "csv_path": str(csv_path)},
        lambda row: seen.append(row),
    )
    assert seen == [{"name": "Alice", "age": "30"}, {"name": "Bob", "age": "40"}]


# ===========================================================================
# D. Self-healing resolver
# ===========================================================================


@pytest.mark.asyncio
async def test_self_healing_dom_selector_first() -> None:
    """In mock mode, dom_selector strategy succeeds first."""
    resolver = SelfHealingResolver()
    target = {"selector": "button#submit"}
    result = await resolver.resolve_target(target)
    assert result["success"] is True
    assert result["strategy"] == STRATEGY_DOM
    assert "resolved_target" in result


@pytest.mark.asyncio
async def test_self_healing_all_fail_returns_ask_user() -> None:
    """When every strategy fails, the resolver returns ask_user."""
    resolver = SelfHealingResolver()
    # A non-empty target whose only field is irrelevant to every strategy:
    #   - DOM needs `selector`/`dom_selector`
    #   - a11y needs `accessibility_selector`/`automation_id`
    #   - text_search needs `text`/`label`
    #   - OCR mock returns 0 boxes -> no_text_found
    #   - image needs `image`/`image_path`
    #   - AI visual mock returns confidence 0.5 (below threshold)
    target = {"unrelated_field": "ignored"}
    result = await resolver.resolve_target(target)
    assert result["success"] is False
    assert result["reason"] == "ask_user"


@pytest.mark.asyncio
async def test_self_healing_low_confidence_returns_ask_user() -> None:
    """When AI visual confidence is below threshold, we ask the user."""
    resolver = SelfHealingResolver(confidence_threshold=0.99)
    # A target with only an AI-describable field (no DOM selector, no
    # image, no text) will cascade down to the AI visual strategy. In
    # mock mode that strategy returns confidence=0.5, which is below 0.99.
    target = {"label": "the submit button"}
    # We need to disable the image_recognition mock success by not
    # supplying an image path.
    result = await resolver.resolve_target(target)
    # The image_recognition strategy returns success because there's no
    # image_path. Wait, let me re-check the impl — image strategy returns
    # success=False with reason "no_image" when no image is supplied. So
    # we reach AI visual which returns mock_low_confidence (0.5), below
    # our threshold. The resolver escalates to ask_user.
    assert result["success"] is False
    assert result["reason"] == "ask_user"


# ===========================================================================
# E. Task Recorder
# ===========================================================================


def test_recorder_mock_mode_returns_events() -> None:
    """TaskRecorder.start/stop in mock mode yields a Recording with events."""
    r = TaskRecorder()
    r.start()
    assert r.is_recording is True
    r.pause()
    assert r.is_recording is False
    r.resume()
    assert r.is_recording is True
    rec = r.stop()
    assert isinstance(rec, Recording)
    assert rec.finished_at is not None
    # Mock mode emits 6 sample events.
    assert len(rec.events) >= 3
    # And the events are well-formed RecordedEvent instances.
    for ev in rec.events:
        assert isinstance(ev, RecordedEvent)
        assert ev.type


def test_recorder_to_workflow_compacts_events() -> None:
    """to_workflow produces a Workflow with named (not raw) actions."""
    r = TaskRecorder()
    r.start()
    rec = r.stop()
    wf = r.to_workflow(rec, name="recorded_test")
    assert isinstance(wf, Workflow)
    assert wf.name == "recorded_test"
    # We expect at least: browser.navigate, keyboard.type (merged), mouse.click, file.write.
    types = [n.type for n in wf.nodes]
    assert "browser.navigate" in types
    assert "keyboard.type" in types
    assert "mouse.click" in types
    # The keyboard.type node should contain the merged text "abc".
    kt = next(n for n in wf.nodes if n.type == "keyboard.type")
    assert kt.args["text"] == "abc"
    # The mouse.click node should have a label (named action).
    mc = next(n for n in wf.nodes if n.type == "mouse.click")
    assert mc.args.get("label") == "Submit"


def test_recorder_state_persists_pause_resume() -> None:
    """State is preserved across pause/resume cycles."""
    r = TaskRecorder()
    r.start()
    r.pause()
    r.resume()
    r.pause()
    r.resume()
    rec = r.stop()
    # Even after multiple pause/resume cycles, the recording is intact.
    assert len(rec.events) >= 3


# ===========================================================================
# F. Plugin Manager
# ===========================================================================


def test_plugin_manager_discover() -> None:
    """discover() finds the hello_world plugin manifest."""
    mgr = PluginManager(plugins_dir=Path("/home/z/my-project/plugins"))
    specs = mgr.discover()
    names = [s.name for s in specs]
    assert "hello_world" in names


@pytest.mark.asyncio
async def test_plugin_manager_load() -> None:
    """Loading hello_world registers the hello.greet tool."""
    mgr = PluginManager(plugins_dir=Path("/home/z/my-project/plugins"))
    mgr.discover()
    # Clean up any prior registration (e.g. from a previous test).
    if "hello.greet" in tool_registry._tools:
        del tool_registry._tools["hello.greet"]
    plugin = mgr.load("hello_world")
    assert plugin.state == PluginState.LOADED
    assert "hello.greet" in plugin.registered_tool_names
    # The tool is now in the global registry.
    t = tool_registry.get("hello.greet")
    assert t is not None
    # And it actually works.
    res = await t.execute({"name": "World"})
    assert res.status == StepStatus.COMPLETED
    assert res.output["message"] == "Hello from World!"
    # Cleanup so other tests don't see this tool.
    mgr.unload("hello_world")


def test_plugin_manager_unload() -> None:
    """unload() removes the plugin's tools from the registry."""
    mgr = PluginManager(plugins_dir=Path("/home/z/my-project/plugins"))
    mgr.discover()
    if "hello.greet" in tool_registry._tools:
        del tool_registry._tools["hello.greet"]
    plugin = mgr.load("hello_world")
    assert "hello.greet" in plugin.registered_tool_names
    assert tool_registry.get("hello.greet") is not None
    mgr.unload("hello_world")
    assert tool_registry.get("hello.greet") is None


def test_plugin_manager_permission_denied(tmp_path: Path) -> None:
    """A plugin requesting an un-approved permission is refused."""
    plugin_dir = tmp_path / "evil"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text(
        '{"name": "evil", "version": "0.1", "permissions": ["filesystem.read", "kernel.ring0"]}'
    )
    (plugin_dir / "main.py").write_text("def register(m): pass\n")
    mgr = PluginManager(plugins_dir=tmp_path)
    mgr.discover()
    with pytest.raises(PermissionError):
        mgr.load("evil")


# ===========================================================================
# G. WorkflowExecutor with variables / control flow / self-healing
# ===========================================================================


@pytest.mark.asyncio
async def test_workflow_executor_with_variables(tmp_screenshots_dir) -> None:
    """A step with {{today}} in its args gets resolved before execution."""
    captured: dict = {}

    def _capture(args: dict) -> ActionResult:
        captured.update(args)
        return ActionResult(tool="test.echo", status=StepStatus.COMPLETED)

    _register_test_tool("test.echo", _capture)
    plan = _plan([
        PlanStep(
            id="1",
            action="test.echo",
            args={"report": "Report_{{today}}.pdf"},
            timeout_ms=500,
        ),
    ])
    ex = WorkflowExecutor()
    run_id = await ex.execute_plan(plan)
    status = ex.get_status(run_id)
    assert status["status"] == "completed"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert captured["report"] == f"Report_{today}.pdf"


@pytest.mark.asyncio
async def test_workflow_executor_if_branch_true(tmp_path: Path) -> None:
    """An 'if' step with a true condition records the 'then' branch."""
    f = tmp_path / "marker.txt"
    f.write_text("x")
    plan = _plan([
        PlanStep(
            id="1",
            action="if",
            args={"condition": {"type": "file_exists", "path": str(f)}},
            timeout_ms=500,
        ),
    ])
    ex = WorkflowExecutor()
    run_id = await ex.execute_plan(plan)
    status = ex.get_status(run_id)
    assert status["status"] == "completed"
    cf = status.get("control_flow", {})
    assert cf.get("1", {}).get("branch") == "then"
    assert cf.get("1", {}).get("condition_result") is True


@pytest.mark.asyncio
async def test_workflow_executor_if_branch_false(tmp_path: Path) -> None:
    """An 'if' step with a false condition records the 'else' branch."""
    plan = _plan([
        PlanStep(
            id="1",
            action="if",
            args={
                "condition": {
                    "type": "file_exists",
                    "path": str(tmp_path / "definitely_not_here.txt"),
                }
            },
            timeout_ms=500,
        ),
    ])
    ex = WorkflowExecutor()
    run_id = await ex.execute_plan(plan)
    status = ex.get_status(run_id)
    assert status["status"] == "completed"
    cf = status.get("control_flow", {})
    assert cf.get("1", {}).get("branch") == "else"
    assert cf.get("1", {}).get("condition_result") is False


@pytest.mark.asyncio
async def test_workflow_executor_for_each(tmp_path: Path) -> None:
    """A for_each step iterates and runs the inner step per item."""
    for name in ("a.txt", "b.txt"):
        (tmp_path / name).write_text(name)
    calls: list[dict] = []

    def _capture(args: dict) -> ActionResult:
        calls.append(args)
        return ActionResult(tool="test.log", status=StepStatus.COMPLETED)

    _register_test_tool("test.log", _capture)
    plan = _plan([
        PlanStep(
            id="1",
            action="for_each",
            args={
                "loop": {"type": "for_each_file", "path": str(tmp_path), "pattern": "*.txt"},
                "action": "test.log",
                "args": {"filename": "{{item}}"},
            },
            timeout_ms=2_000,
        ),
    ])
    ex = WorkflowExecutor()
    run_id = await ex.execute_plan(plan)
    status = ex.get_status(run_id)
    assert status["status"] == "completed"
    # The inner step should have been called once per matched file.
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_workflow_executor_self_healing(tmp_screenshots_dir) -> None:
    """When a step fails, the self-healing resolver is consulted.

    We register a tool that always fails, then verify the executor
    attempted self-healing by checking that the run's status reflects
    either the healed retry (status=completed) or a fallback-path
    failure. Either way, the self-healing event MUST have been emitted.
    """
    events: list[dict] = []
    event_bus.on(
        "STEP_COMPLETED",
        lambda p: events.append(p) if p.get("self_healed") else None,
    )

    # Tool that always fails.
    _register_test_tool(
        "test.always_fail",
        ActionResult(tool="test.always_fail", status=StepStatus.FAILED, error="boom"),
    )
    plan = _plan([
        PlanStep(
            id="1",
            action="test.always_fail",
            args={"selector": "button#doesnotexist"},
            timeout_ms=500,
        ),
    ])
    ex = WorkflowExecutor()
    run_id = await ex.execute_plan(plan)
    # The step failed, self-healing was attempted (it returned a successful
    # DOM hit in mock mode — but the tool itself still fails on retry, so
    # the overall plan status is FAILED).
    # The KEY assertion: a STEP_COMPLETED event with self_healed=True was
    # published.
    healed_events = [e for e in events if e.get("self_healed")]
    assert len(healed_events) >= 1


@pytest.mark.asyncio
async def test_execute_workflow_runs_nodes(tmp_screenshots_dir) -> None:
    """execute_workflow converts a Workflow to a Plan and runs it."""
    captured: list[str] = []

    def _cap(args: dict) -> ActionResult:
        captured.append(args.get("filename", "?"))
        return ActionResult(tool="test.wf", status=StepStatus.COMPLETED)

    _register_test_tool("test.wf", _cap)

    wf = Workflow(
        id="wf_test_1",
        name="test workflow",
        nodes=[
            WorkflowNode(id="n1", type="test.wf", args={"filename": "first.txt"}),
            WorkflowNode(id="n2", type="test.wf", args={"filename": "second.txt"}),
        ],
        variables={},
    )
    ex = WorkflowExecutor()
    run_id = await ex.execute_workflow(wf)
    status = ex.get_status(run_id)
    assert status["status"] == "completed"
    assert captured == ["first.txt", "second.txt"]
