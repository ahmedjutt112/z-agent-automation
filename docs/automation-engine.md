# Automation Engine

> How the AI PC/Laptop Automation Agent actually moves the mouse,
> presses keys, opens browsers, and reads files.
> Source-of-truth:
> `apps/automation-service/automation_service/engine/tool_registry.py`,
> `apps/automation-service/automation_service/engine/workflow_executor.py`,
> `apps/automation-service/automation_service/engine/event_bus.py`,
> and the `tools/` package.

## 1. Overview

The automation engine is a Python process (FastAPI service) that
turns a structured `Plan` into real side effects on the user's
computer. It is the **HOW** layer per master prompt §2:

- The AI decides WHAT should happen.
- The **automation engine** decides HOW it can safely happen.
- The security layer decides WHETHER it is allowed to happen.

The engine has three subsystems:

1. **Tool registry** — a typed catalogue of every action the engine
   can perform. Each tool declares its inputs, risk level, permission
   level, timeout, rollback, and verification strategy (§8).
2. **Workflow executor** — walks a `Plan` step by step, enforces
   timeouts and retries, handles fallbacks, and emits events.
3. **Event bus** — an in-process pub/sub that streams every state
   transition to the renderer via WebSocket (§76, §77).

Everything in mock mode (§64) is a no-op simulation: clicks return
"would have clicked at (x, y)" without moving the cursor; file
writes return "would have written N bytes" without touching disk.
This is critical for safe testing and workflow preview.

## 2. Tool registry architecture (§8)

Source: `apps/automation-service/automation_service/engine/tool_registry.py`

### 2.1 The `Tool` abstract base class

Every tool subclasses `Tool` and declares its metadata as class
attributes:

```python
class Tool(abc.ABC):
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
        return ToolSpec(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema,
            permission_level=self.permission_level,
            risk_level=self.risk_level,
            timeout_ms=self.timeout_ms,
            rollback_strategy=self.rollback_strategy,
            verification_strategy=self.verification_strategy,
        )
```

The eight declared fields are exactly what master prompt §8 requires.
`spec()` materialises them as a Pydantic `ToolSpec` that the API
serialises for the renderer so the workflow builder can render a
typed input form per tool.

### 2.2 The `@register_tool` decorator

```python
def register_tool(cls):
    if not issubclass(cls, Tool):
        raise TypeError(f"@register_tool expects Tool subclass, got {cls}")
    instance = cls()
    tool_registry.register(instance)
    return cls
```

It instantiates the class and registers the instance with the
singleton `tool_registry`. Registering the same name twice raises
`ValueError("Duplicate tool name: ...")` at import time, so typos
are caught before the service starts accepting traffic.

### 2.3 Auto-discovery

```python
class ToolRegistry:
    def discover(self) -> None:
        from . import tools as _tools_pkg
        for mod_info in pkgutil.iter_modules(_tools_pkg.__path__):
            importlib.import_module(f"{_tools_pkg.__name__}.{mod_info.name}")
```

`discover()` walks every module in `automation_service/tools/` and
imports it. Each module's top-level `@register_tool` decorators run
at import time, so every public tool in the package is registered
automatically. Adding a new tool requires zero wiring — drop a
file in `tools/`, decorate the class, restart the service.

### 2.4 Currently registered tools

The MVP ships with the following tools, grouped by module:

| Module | Tool names | Risk levels |
|---|---|---|
| `tools/mouse.py` | `mouse.click`, `mouse.move`, `mouse.scroll` | all LOW |
| `tools/keyboard.py` | `keyboard.type`, `keyboard.hotkey` | both MEDIUM (typing can submit forms) |
| `tools/screen.py` | `screen.capture`, `screen.ocr` | both LOW |
| `tools/files.py` | `file.read`, `file.write`, `file.move`, `file.rename`, `file.list` | LOW, MEDIUM, MEDIUM, MEDIUM, LOW |
| `tools/apps.py` | `app.launch`, `window.list`, `process.list` | MEDIUM, LOW, LOW |
| `tools/browser.py` | `browser.open`, `browser.navigate`, `browser.click`, `browser.type`, `browser.extract` | LOW, LOW, MEDIUM, MEDIUM, LOW |

Future tools (Phase 2+): `file.delete` (CRITICAL), `window.focus`,
`window.minimize`, `window.close`, `app.close`, `app.wait_ready`,
`browser.download`, `browser.scroll`, `browser.wait_for_element`,
`clipboard.read`, `clipboard.write`, `system.notify`,
`command.run` (CRITICAL), `python.eval` (CRITICAL).

### 2.5 The `ToolSpec` Pydantic model

`apps/automation-service/automation_service/models.py` defines:

```python
class ToolSpec(BaseModel):
    name: str = Field(..., description="Dotted tool name, e.g. 'mouse.click'")
    description: str
    input_schema: dict[str, Any] = Field(..., description="JSON Schema for tool input")
    permission_level: PermissionLevel
    risk_level: RiskLevel
    timeout_ms: int = Field(default=10_000, ge=100, le=600_000)
    rollback_strategy: Optional[str] = None
    verification_strategy: Optional[str] = None
```

`GET /tools` returns `[t.spec().model_dump() for t in tool_registry.all()]`,
which the renderer uses to render the workflow builder's actions
panel and the inspector for each node.

### 2.6 Example tool — `mouse.click`

```python
@register_tool
class MouseClickTool(Tool):
    name = "mouse.click"
    description = "Click at screen coordinates (x, y) with the given button."
    permission_level = "allow_once"
    risk_level = "low"
    timeout_ms = 5_000
    input_schema = {
        "type": "object",
        "properties": {
            "x": {"type": "integer", "minimum": 0},
            "y": {"type": "integer", "minimum": 0},
            "button": {"type": "string", "enum": ["left", "right", "middle"], "default": "left"},
            "clicks": {"type": "integer", "minimum": 1, "default": 1},
        },
        "required": ["x", "y"],
    }

    async def execute(self, args: dict[str, Any]) -> ActionResult:
        start = datetime.now(timezone.utc)
        x, y = int(args["x"]), int(args["y"])
        button = args.get("button", "left")
        clicks = int(args.get("clicks", 1))

        if settings.mock_mode:
            return ActionResult(
                tool=self.name,
                status=StepStatus.COMPLETED,
                output={"simulated": True, "x": x, "y": y, "button": button, "clicks": clicks},
                finished_at=datetime.now(timezone.utc),
                duration_ms=int((datetime.now(timezone.utc) - start).total_seconds() * 1000),
            )

        try:
            import pyautogui  # type: ignore
            pyautogui.click(x=x, y=y, button=button, clicks=clicks)
            return ActionResult(
                tool=self.name,
                status=StepStatus.COMPLETED,
                output={"x": x, "y": y, "button": button, "clicks": clicks},
                finished_at=datetime.now(timezone.utc),
                duration_ms=int((datetime.now(timezone.utc) - start).total_seconds() * 1000),
            )
        except Exception as exc:
            return ActionResult(
                tool=self.name,
                status=StepStatus.FAILED,
                error=str(exc),
                ...
            )
```

Note the pattern:

1. Compute `start` for `duration_ms`.
2. If `settings.mock_mode`, short-circuit and return a `COMPLETED`
   result with `output.simulated = True`.
3. Otherwise lazily `import pyautogui` (so the service starts even
   if the optional native dep is missing).
4. Catch every exception and convert to `ActionResult(status=FAILED,
   error=str(exc))` — never let an exception bubble out of a tool.

This pattern is repeated across every tool. Copy it for new tools.

## 3. Mock mode (§64)

Source: `apps/automation-service/automation_service/config.py`
(`settings.mock_mode`) and every tool module.

Mock mode is **on by default** (`AUTOMATION_MOCK_MODE=true`). It is
the single most important safety switch in the system. When enabled:

- `mouse.click` does not move the cursor — it returns
  `{"simulated": True, "x": x, "y": y, "button": button}`.
- `keyboard.type` does not type — it returns
  `{"simulated": True, "text": text, "length": len(text)}`.
- `screen.capture` writes a placeholder PNG to
  `download/screenshots/` so file-path verifications still pass.
- `browser.open` does not launch a browser — `BrowserSessionManager`
  short-circuits and returns `None`.
- `file.read` / `file.write` / `file.move` / `file.rename` / `file.list`
  DO still run (they are pure filesystem operations that are
  inherently safe inside `ALLOWED_ROOTS`), but their `ActionResult`
  is tagged with `simulated: True` to make it clear in logs that
  mock mode is active.
- `app.launch` checks the allowlist but does not call
  `subprocess.Popen`.

The point of mock mode is:

1. **Test the pipeline end-to-end without side effects.** A workflow
   that exercises the planner, permission engine, executor, event
   bus, and database logging can be validated without clicking real
   buttons.
2. **Preview workflows.** Before running a destructive workflow, the
   user clicks "Dry Run" (§65), which is mock mode for the duration
   of the run.
3. **CI.** The full test suite runs with mock mode on so it cannot
   damage the CI machine.

The service reports mock mode in `GET /health` so the renderer can
show a "MOCK MODE" badge in the toolbar:

```json
{
  "status": "ok",
  "service": "automation-service",
  "version": "0.1.0",
  "mock_mode": true,
  "kill_switch": false
}
```

## 4. Dry run (§65)

Dry run is a thin layer over mock mode. Every workflow supports
three run modes:

| Mode | Behaviour |
|---|---|
| Run | `mock_mode = false` for the duration of this run (still subject to risk-level gates) |
| Dry Run | `mock_mode = true` for the duration of this run, regardless of the global setting |
| Preview | Dry run + render the expected side effects in the UI without executing |

Dry Run implementation (planned in `WorkflowExecutor`):

```python
async def execute_plan(self, plan: Plan, dry_run: bool = False) -> str:
    original_mock = settings.mock_mode
    if dry_run:
        settings.mock_mode = True
    try:
        return await self._execute_plan_impl(plan)
    finally:
        settings.mock_mode = original_mock
```

> The `dry_run` parameter on `POST /task/run` is **Phase 1 — Coming
> Soon**. The plumbing exists in mock mode; what is missing is the
> route flag and the renderer button.

## 5. Risk level hierarchy (§9)

Every tool declares a `risk_level` from the `RiskLevel` enum
(`apps/automation-service/automation_service/models.py`):

```python
class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
```

The four levels and their semantics:

### 5.1 LOW

> Auto-allowed, logged.

Examples:

- `mouse.move`, `mouse.scroll`
- `screen.capture`, `screen.ocr`
- `file.read`, `file.list`
- `browser.open`, `browser.navigate`, `browser.extract`
- `window.list`, `process.list`

These tools cannot destroy data, send messages, or spend money.
They can read state and capture pixels.

### 5.2 MEDIUM

> Auto-allowed IF a matching grant exists, else prompt.

Examples:

- `keyboard.type`, `keyboard.hotkey` (typing can submit forms / send
  messages)
- `file.write`, `file.move`, `file.rename` (file mutations)
- `app.launch` (launches a process)
- `browser.click`, `browser.type` (mutates page state)

These tools change state but are reversible or recoverable.

### 5.3 HIGH

> Explicit user approval required.

Examples (planned):

- `file.delete` (single file)
- `app.close` (closes a window/app the user may have unsaved work in)
- `browser.submit_form`
- `command.run` (allowlisted shell command)
- `clipboard.write`

These tools cause state changes that may not be reversible without
user effort.

### 5.4 CRITICAL

> Explicit user approval required even in autonomous mode.
> No "always allow" grant ever accepted.

Examples (planned):

- Deleting many files (>10)
- Unrestricted shell execution
- Financial transactions / purchases
- Password changes
- Modifying system-critical files
- Modifying security policies

The permission engine unconditionally returns `DENY` from
`evaluate_action` for CRITICAL actions that lack an explicit,
just-now-granted approval (i.e. "Always Allow" cannot apply to
CRITICAL actions).

## 6. Self-healing workflow (§40)

When a tool fails, the workflow executor consults `step.fallback`
to decide what to try next. The fallback strategy itself is a
tool name; the executor calls it with the same `args` and waits
for a result.

The master prompt §40 ordering is:

```
1. DOM selector (browser.*)
2. Accessibility / UI Automation selector
3. Text search (file / screen.ocr)
4. OCR (screen.ocr)
5. Image recognition  (Phase 3)
6. AI visual interpretation  (Phase 3)
7. Ask user
```

In the MVP only step 1 (DOM) and step 3 (text) are wired; the
fallback ordering is encoded as a chain of `PlanStep.fallback`
fields in the planner's system prompt:

```
PlanStep(
  id="click_download",
  action="browser.click",
  args={"selector": "button.download"},
  fallback="screen.ocr"     # try OCR if DOM click fails
)
```

> The full self-healing cascade (accessibility → text → OCR → image
> → AI visual) is **Phase 3 — Coming Soon**. The plumbing for
> fallbacks already exists in `WorkflowExecutor._execute_step`;
> what is missing is the orchestrator that decides which fallback
> to try based on the failure type.

### 6.1 Never blindly click random locations

The recovery agent (§7) is forbidden from clicking arbitrary
coordinates as a recovery mechanism. Every recovery action must
have a deterministic or AI-justified target with `confidence >=
settings.min_vision_confidence` (default `0.85`). If no recovery
path produces a confident target, the run pauses with
`reason="recovery_failed"` and emits a `USER_APPROVAL_REQUIRED`
event so the user can take over.

## 7. Workflow executor internals

Source: `apps/automation-service/automation_service/engine/workflow_executor.py`

### 7.1 `execute_plan(plan)`

```python
async def execute_plan(self, plan: Plan) -> str:
    run_id = str(uuid4())
    cancel_token = kill_switch.get_cancel_event()
    self._cancel_tokens[run_id] = cancel_token
    self._runs[run_id] = {
        "plan_id": str(plan.id),
        "goal": plan.goal,
        "status": TaskStatus.RUNNING.value,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "steps_total": len(plan.steps),
        "steps_completed": 0,
        "steps_failed": 0,
        "checkpoints": [],
    }
    event_bus.publish("TASK_STARTED", {"run_id": run_id, "plan_id": str(plan.id)})
    try:
        for step in plan.steps:
            if cancel_token.is_set() or kill_switch.engaged:
                self._runs[run_id]["status"] = TaskStatus.CANCELLED.value
                event_bus.publish("TASK_PAUSED", {"run_id": run_id, "reason": "kill_switch"})
                return run_id
            result = await self._execute_step(run_id, step)
            if result.status == StepStatus.FAILED:
                self._runs[run_id]["steps_failed"] += 1
                if step.fallback:
                    fb_step = PlanStep(id=step.id + "_fb", action=step.fallback, args=step.args)
                    await self._execute_step(run_id, fb_step)
                else:
                    self._runs[run_id]["status"] = TaskStatus.FAILED.value
                    event_bus.publish("TASK_FAILED", {"run_id": run_id, "step_id": step.id})
                    return run_id
            else:
                self._runs[run_id]["steps_completed"] += 1
                self._runs[run_id]["checkpoints"].append({
                    "step_id": step.id,
                    "at": datetime.now(timezone.utc).isoformat(),
                })
        self._runs[run_id]["status"] = TaskStatus.COMPLETED.value
        event_bus.publish("TASK_COMPLETED", {"run_id": run_id})
    except Exception as exc:
        self._runs[run_id]["status"] = TaskStatus.FAILED.value
        event_bus.publish("TASK_FAILED", {"run_id": run_id, "error": str(exc)})
    return run_id
```

The flow is:

1. Allocate `run_id`.
2. Subscribe a cancel token from the kill switch.
3. Build a run record (in-memory; persisted to `workflow_runs` in
   Phase 1).
4. Walk the steps. Before each step: check the kill switch.
5. Execute the step. On failure: try the fallback step.
6. On any step without a fallback that fails, mark the run failed
   and return.
7. On success of every step, mark the run completed.

### 7.2 `_execute_step(run_id, step)`

```python
async def _execute_step(self, run_id: str, step: PlanStep) -> ActionResult:
    event_bus.publish("STEP_STARTED", {"run_id": run_id, "step_id": step.id, "tool": step.action})

    tool = tool_registry.get(step.action)
    if tool is None:
        return ActionResult(
            tool=step.action,
            status=StepStatus.FAILED,
            error=f"tool '{step.action}' not registered",
        )

    attempt = 0
    last_error = None
    while attempt <= step.retry_count:
        try:
            result = await asyncio.wait_for(
                tool.execute(step.args),
                timeout=step.timeout_ms / 1000,
            )
            if result.status == StepStatus.COMPLETED:
                event_bus.publish("STEP_COMPLETED", {
                    "run_id": run_id,
                    "step_id": step.id,
                    "duration_ms": result.duration_ms,
                })
                return result
            last_error = result.error
        except asyncio.TimeoutError:
            last_error = f"timeout after {step.timeout_ms}ms"
        except Exception as exc:
            last_error = str(exc)

        attempt += 1
        if attempt <= step.retry_count:
            await asyncio.sleep(0.5 * attempt)  # linear backoff

    event_bus.publish("STEP_FAILED", {"run_id": run_id, "step_id": step.id, "error": last_error})
    return ActionResult(tool=step.action, status=StepStatus.FAILED, error=last_error)
```

Key points:

- **Unknown tool** → immediate FAILED with a clear error message;
  no retry, no fallback.
- **Timeout** → `asyncio.TimeoutError` is caught and converted to a
  normal retry attempt. After `retry_count` failures, the step fails.
- **Backoff** → linear: `0.5 * attempt` seconds. Exponential backoff
  is planned (Phase 1) — the current linear schedule is intentionally
  simple to reason about during the MVP.
- **Event emission** → every state transition publishes an event so
  the renderer can show step-by-step progress.

### 7.3 Checkpoint and resume (§61)

Every successful step appends an entry to
`self._runs[run_id]["checkpoints"]`:

```python
{"step_id": step.id, "at": datetime.now(timezone.utc).isoformat()}
```

When the renderer sends `POST /task/resume/{run_id}` (planned), the
executor reads the checkpoint list and resumes from the first step
not present in it. The resume flow:

1. Load the original `Plan` (from `tasks.plan_json` once persistence
   is wired).
2. Filter out steps whose `id` is in the checkpoints list.
3. Call `execute_plan(filtered_plan)` with the original `run_id`.

> Persisting checkpoints to SQLite is **Phase 1 — Coming Soon**. The
> in-memory structure already captures the data; only the
> write-through to `workflow_runs.checkpoint_json` is missing.

### 7.4 Crash recovery (§62)

When the service starts, it scans `workflow_runs` for rows with
`status = 'running'` (i.e. the service was killed mid-run). For
each, it emits a `TASK_PAUSED` event with `reason="crash_recovery"`
and exposes them via `GET /task/interrupted` (planned). The renderer
shows:

```
An automation was interrupted.

{goal}

Last completed step: {step_id}

[Resume] [Restart] [Discard]
```

- **Resume** — calls `POST /task/resume/{run_id}` with the original
  plan minus completed steps.
- **Restart** — calls `POST /task/run` with a fresh `Plan` and the
  same `run_id`.
- **Discard** — calls `DELETE /task/{run_id}` which sets
  `workflow_runs.status = 'cancelled'`.

> Crash recovery is **Phase 1 — Coming Soon**. The schema already
> has the `status` column and the `idx_workflow_runs_status` index
> that the startup scan will use.

## 8. Variable system (§41)

Workflow variables let users parameterise steps without hard-coding
values. The MVP supports the variables below; substitution happens
in `WorkflowExecutor` before each step's args are passed to the
tool.

| Variable | Resolves to |
|---|---|
| `{{today}}` | `datetime.now().strftime("%Y-%m-%d")` |
| `{{yesterday}}` | `(datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")` |
| `{{now}}` | ISO-8601 timestamp |
| `{{username}}` | `os.getenv("USER")` or `os.getenv("USERNAME")` |
| `{{downloads_folder}}` | `Path.home() / "Downloads"` |
| `{{documents_folder}}` | `Path.home() / "Documents"` |
| `{{desktop_folder}}` | `Path.home() / "Desktop"` |
| `{{clipboard}}` | current clipboard contents (masked in logs) |
| `{{selected_file}}` | file the user has selected in the renderer |
| `{{workflow_id}}` | current workflow's id |
| `{{run_id}}` | current run's id |

Custom variables are defined per-workflow in the `variables` dict
on the `Workflow` model:

```json
{
  "id": "wf_001",
  "name": "Daily Report",
  "variables": {
    "report_name": "Sales_Summary",
    "destination_folder": "{{documents_folder}}/Reports"
  },
  "nodes": [
    {"id": "1", "type": "file.write",
     "args": {"path": "{{destination_folder}}/{{report_name}}_{{today}}.txt",
              "content": "..."}}
  ]
}
```

Variable resolution is recursive (variables can reference other
variables) and depth-capped at 5 levels to prevent infinite loops.

> The variable substitution engine is **Phase 1 — Coming Soon**.
> The schema (`Workflow.variables`, `Plan.variables`) and the
> placeholder syntax are already defined; the resolver is the
> remaining work.

## 9. Conditions (§42)

A `Condition` node evaluates a predicate and branches to one of
`next`, `on_true`, or `on_false`. Predicates supported (planned):

| Predicate | Description |
|---|---|
| `file_exists` | `Path(path).exists()` inside `ALLOWED_ROOTS` |
| `window_exists` | A window with the given title is present |
| `text_exists` | A string is found in a file or screen OCR |
| `image_exists` | A template image is found on screen (Phase 3) |
| `browser_element_exists` | A CSS selector matches in the active browser session |
| `process_running` | A process with the given name is in `psutil.process_iter` |
| `network_available` | DNS resolution for `1.1.1.1` succeeds |
| `ai_condition` | The planner evaluates the predicate as a boolean |

Workflow JSON for a condition node:

```json
{
  "id": "if_file_exists",
  "type": "if",
  "args": {
    "predicate": "file_exists",
    "path": "{{downloads_folder}}/report.pdf"
  },
  "on_true": "move_file",
  "on_false": "download_report"
}
```

> Conditions are **Phase 2 — Coming Soon**. The `WorkflowNode`
> schema supports `next`, `on_error`, and arbitrary `args` so the
> data model is ready; the executor's branch logic is the remaining
> work.

## 10. Loops (§43)

Loop node types:

| Type | Iterates over |
|---|---|
| `for_each_file` | `Path(directory).glob(pattern)` |
| `for_each_row` | rows of an extracted table or CSV |
| `for_each_browser_result` | elements matched by a CSS selector |
| `while` | while a condition predicate is true |
| `retry_loop` | retry a sub-graph up to N times |
| `batch` | process items in batches of K |

Every loop has a hard cap of `settings.max_loops` (default 1000)
iterations. If the cap is exceeded, the run is paused with
`reason="loop_limit_exceeded"` and a `USER_APPROVAL_REQUIRED` event
is emitted.

```json
{
  "id": "loop_files",
  "type": "for_each_file",
  "args": {
    "directory": "{{downloads_folder}}",
    "pattern": "*.pdf"
  },
  "body": ["move_to_documents"],
  "max_iterations": 100
}
```

> Loops are **Phase 2 — Coming Soon**.

## 11. Parallel execution (§44)

Parallel execution is used when steps are independent (e.g.
downloading 3 unrelated files). The executor will use
`asyncio.gather` for parallel branches and a resource lock for
serialised resources.

```json
{
  "id": "parallel_downloads",
  "type": "parallel",
  "branches": [
    [{"id": "1a", "type": "browser.download", "args": {"url": "..."}}],
    [{"id": "1b", "type": "browser.download", "args": {"url": "..."}}],
    [{"id": "1c", "type": "browser.download", "args": {"url": "..."}}]
  ],
  "max_concurrency": 3
}
```

Resource locks (planned):

| Lock | Scope |
|---|---|
| `mouse` | global (only one mouse action at a time) |
| `keyboard` | global (only one keyboard action at a time) |
| `browser_session:{session_id}` | per browser session |
| `file_path:{path}` | per file path |
| `app:{name}` | per application instance |

Conflicting operations (e.g. two parallel steps trying to write the
same file) are detected at scheduling time and serialised.

> Parallel execution is **Phase 2 — Coming Soon**.

## 12. Event bus (§76)

Source: `apps/automation-service/automation_service/engine/event_bus.py`

An in-process pub/sub. Every state transition in the executor calls
`event_bus.publish(event_type, payload)`. The canonical event names
are:

```python
EVENT_TYPES = [
    "TASK_CREATED", "TASK_STARTED", "TASK_PAUSED",
    "TASK_COMPLETED", "TASK_FAILED",
    "STEP_STARTED", "STEP_COMPLETED", "STEP_FAILED",
    "APP_OPENED", "APP_CLOSED", "WINDOW_CHANGED",
    "BROWSER_NAVIGATED", "FILE_CREATED", "FILE_MOVED",
    "USER_APPROVAL_REQUIRED", "EMERGENCY_STOP",
    "SERVICE_STARTED", "SERVICE_STOPPED", "UNHANDLED_ERROR",
]
```

Three subscriber kinds:

1. `subscribe()` returns an `asyncio.Queue` that receives every
   event as a `(event_type, payload)` tuple. The WebSocket `/events`
   endpoint uses this to push events to the renderer.
2. `on(event_type, fn)` registers a synchronous handler.
3. `on_async(event_type, fn)` registers a coroutine handler that is
   scheduled with `asyncio.create_task`.

A buggy handler cannot kill the bus — exceptions are caught, logged
via `print`, and swallowed. The queue is bounded; if a subscriber
falls behind, the oldest event is dropped to make room for new ones
(this is intentional — the renderer should show the latest state,
not replay history).

## 13. Performance requirements (§59)

| Requirement | Target | Mechanism |
|---|---|---|
| Service startup | < 3 s on reasonable hardware | Lazy imports for `pyautogui`, `playwright`, `pytesseract` |
| Idle CPU | < 2 % | No background polling; event-driven only |
| Action latency | < 100 ms tool overhead | Tools run inline on the asyncio loop; blocking calls wrapped in `asyncio.to_thread` (planned) |
| Screenshot capture | only when needed | `screen.capture` is explicit; no auto-screenshot loop |
| UI responsiveness | renderer never blocks | All side effects in the Python process; renderer only renders events |

The service is single-process and single-event-loop. The Electron
renderer is a separate process and is never blocked by automation
workload.

## 14. Verification (§40)

Each `PlanStep` may carry a `verification` field — a string naming
the strategy the executor should use to confirm the step succeeded.
The MVP strategies are:

| Strategy | Implementation |
|---|---|
| `file_exists` | `Path(path).exists()` |
| `dom_text_present` | `await page.inner_text(selector)` includes `text` |
| `screenshot_diff` | image diff against a baseline (Phase 3) |
| `process_running` | `psutil.pid_exists(pid)` |
| `http_status` | HTTP HEAD returns expected status (Phase 2) |
| `none` | no verification — step is its own evidence (default) |

Verification runs after the step's primary action and emits a
`STEP_VERIFIED` event on success or `STEP_FAILED` with
`reason="verification_failed"` on failure.

> Verification strategies are **Phase 1 — Coming Soon**. The
> `PlanStep.verification` field is defined; the executor hook that
> dispatches on it is the remaining work.

## 15. Error handling (§39)

Every step carries:

```python
class PlanStep(BaseModel):
    timeout_ms: int = 10_000
    retry_count: int = 0
    fallback: Optional[str] = None
    verification: Optional[str] = None
```

(`retry_delay_ms` and `on_error` are added in Phase 1 — the schema
already reserves space via the `WorkflowNode` model which has
`retry_delay_ms` and `on_error`.)

The error-handling cascade:

1. Try the tool.
2. If timeout or exception → retry up to `retry_count` with backoff.
3. If still failing and `fallback` is set → try the fallback tool.
4. If fallback also fails → mark step failed, emit `STEP_FAILED`,
   check `on_error` for an alternate node to jump to (Phase 1).
5. If no `on_error` → mark run failed, emit `TASK_FAILED`, stop.

The user-visible message is always the `last_error` string from the
retry loop. Stack traces go to `error_logs.stack_trace` only (not
`task_logs.payload`), so the History view shows the friendly message
and the Developer view shows the trace.

## 16. Phase map

| Feature | Status |
|---|---|
| Tool registry + `@register_tool` + auto-discovery | Implemented |
| 18 tools across mouse / keyboard / screen / files / apps / browser | Implemented |
| Mock mode default ON | Implemented |
| Risk levels (LOW/MEDIUM/HIGH/CRITICAL) | Implemented (LOW + MEDIUM in active tools) |
| Permission engine | Implemented |
| Kill switch | Implemented |
| Event bus + WebSocket push | Implemented |
| Workflow executor with retry + timeout + fallback | Implemented |
| Dry run mode | **Phase 1 — Coming Soon** |
| Variable substitution (`{{today}}`, `{{clipboard}}`, ...) | **Phase 1 — Coming Soon** |
| Conditions / loops / parallel execution | **Phase 2 — Coming Soon** |
| Self-healing cascade (DOM → A11y → text → OCR → image → AI) | **Phase 3 — Coming Soon** |
| Verification strategies | **Phase 1 — Coming Soon** |
| Checkpoint persistence + resume | **Phase 1 — Coming Soon** |
| Crash recovery UI | **Phase 1 — Coming Soon** |
| Resource locks (mouse / keyboard / browser / file / app) | **Phase 2 — Coming Soon** |
| `file.delete` (CRITICAL + trash) | **Phase 2 — Coming Soon** |
| `command.run` (allowlisted shell) | **Phase 2 — Coming Soon** |
| `python.eval` (sandboxed) | **Phase 2 — Coming Soon** |
