# Testing

> Test strategy for the AI PC/Laptop Automation Agent.
> Covers the testing pyramid (unit / integration / e2e), mock mode
> and dry run as first-class testing tools, and the security
> testing matrix from master prompt §96.

## 1. Overview

Testing an automation agent is harder than testing a typical web
app because:

- Real side effects (mouse moves, file writes, browser navigation)
  cannot run in CI without damaging the runner.
- AI output is non-deterministic; the same prompt can produce
  different plans.
- Time-based triggers (cron, file-watch) need controlled clocks.
- WebSocket events race with HTTP responses.

The strategy below addresses each of these with explicit mechanisms.

## 2. Testing pyramid (§63)

```
                    +--------+
                    |  E2E   |   few, slow, high-confidence
                    +--------+
                  /            \
                /                \
              /                    \
            /                        \
       +------+                  +------+
       | Int. |                  | Int. |
       +------+                  +------+
            \                        /
              \                    /
                \                /
                  +------------+
                  |   Unit    |   many, fast, isolated
                  +------------+
```

| Layer | Count target | Run time | What it asserts |
|---|---|---|---|
| Unit | hundreds | < 30 s total | Pure-Python logic, no I/O |
| Integration | tens | < 5 min total | Real subprocesses, real filesystem (temp), real SQLite |
| E2E | a handful | < 15 min total | Full user journey including Electron renderer |

The test layout mirrors the project layout:

```
tests/
├── unit/
│   ├── test_models.py
│   ├── test_tool_registry.py
│   ├── test_permission_engine.py
│   ├── test_kill_switch.py
│   ├── test_event_bus.py
│   ├── test_planner.py
│   ├── test_ai_providers.py
│   ├── test_workflow_executor.py
│   ├── test_variable_engine.py       (Phase 1)
│   ├── test_workflow_parser.py
│   ├── test_path_validation.py
│   ├── test_secret_masker.py          (Phase 1)
│   └── test_scheduler.py              (Phase 2)
├── integration/
│   ├── test_electron_python_ipc.py
│   ├── test_browser_automation.py
│   ├── test_file_operations.py
│   └── test_windows_automation.py     (Windows CI only)
├── e2e/
│   ├── test_google_search_screenshot.py     (§79)
│   └── test_organise_downloads_workflow.py
└── conftest.py
```

> The tests themselves are **Phase 1 — Coming Soon**. The
> layout above is the target. This document describes what each
> test must assert so when the tests are written the contract is
> already nailed down.

## 3. Unit tests

Unit tests import only the module under test and its pure-Python
dependencies. No I/O, no network, no subprocesses. Every unit test
runs in under 100 ms.

### 3.1 Workflow parser

File: `tests/unit/test_workflow_parser.py`

Asserts that the `Workflow` Pydantic schema:

- Accepts the canonical example from `docs/workflows.md` §2.1.
- Rejects unknown `trigger.type` values (e.g. `"moon_phase"`).
- Rejects workflows with no `start` node.
- Rejects workflows with duplicate `node.id` values.
- Rejects `next` references to nonexistent node ids.
- Accepts a workflow with 1000 nodes; rejects 1001.
- Coerces `created_at` / `updated_at` to UTC datetime objects.
- Defaults `enabled` to `True`.
- Validates `variables` keys against `^[a-zA-Z_][a-zA-Z0-9_]*$`.

Example test:

```python
import pytest
from pydantic import ValidationError
from automation_service.models import Workflow, WorkflowNode, WorkflowTrigger
from automation_service.models import TriggerType


def test_workflow_accepts_canonical_example():
    wf = Workflow(
        id="wf_001",
        name="Daily Report",
        version=1,
        trigger=WorkflowTrigger(type=TriggerType.SCHEDULE, cron="0 9 * * 1-5"),
        nodes=[WorkflowNode(id="start", type="start"), WorkflowNode(id="end", type="end")],
    )
    assert wf.enabled is True
    assert wf.trigger.timezone == "UTC"


def test_workflow_rejects_unknown_trigger_type():
    with pytest.raises(ValidationError):
        WorkflowTrigger(type="moon_phase")


def test_workflow_rejects_duplicate_node_ids():
    with pytest.raises(Exception):
        Workflow(
            id="wf_002", name="dup",
            nodes=[WorkflowNode(id="n1", type="start"), WorkflowNode(id="n1", type="end")],
        )
```

### 3.2 Tool registry

File: `tests/unit/test_tool_registry.py`

Asserts that:

- `@register_tool` rejects classes that are not `Tool` subclasses.
- Registering the same tool name twice raises `ValueError`.
- `ToolRegistry.discover()` imports every module in
  `automation_service.tools` and registers each `@register_tool`
  class exactly once.
- `ToolRegistry.get(name)` returns the registered tool or `None`.
- `ToolRegistry.all()` returns a list whose length matches the
  number of registered tools.
- Every registered tool's `spec()` returns a valid `ToolSpec` with
  all eight required fields populated.

Example:

```python
from automation_service.engine.tool_registry import ToolRegistry, Tool, register_tool


def test_register_rejects_non_tool():
    class NotATool: ...
    with pytest.raises(TypeError):
        register_tool(NotATool)


def test_duplicate_registration_raises():
    registry = ToolRegistry()

    @register_tool
    class T1(Tool):
        name = "test.dup"
        description = "d"
        async def execute(self, args): ...

    # Re-registering the same name should fail
    with pytest.raises(ValueError):
        @register_tool
        class T2(Tool):
            name = "test.dup"
            description = "d"
            async def execute(self, args): ...
```

### 3.3 Permission engine

File: `tests/unit/test_permission_engine.py`

Asserts the decision matrix:

| Risk | No grant | Grant `ALLOW_FOR_WORKFLOW` | Grant `ALWAYS_ALLOW` |
|---|---|---|---|
| LOW | allow_once | allow_once | allow_once |
| MEDIUM | ask → allow_once (MVP) | allow_for_workflow | always_allow |
| HIGH | ask → allow_once (MVP) | allow_for_workflow | always_allow |
| CRITICAL | ask → deny (MVP) | ask → deny | ask → deny |

Also asserts that:

- `grant()` only persists `ALLOW_FOR_WORKFLOW` and `ALWAYS_ALLOW`
  (never `ALLOW_ONCE` or `DENY`).
- `revoke()` removes the grant without raising if it does not exist.
- `list_grants()` returns the grant list in a stable order.
- Every `evaluate_action` call publishes a `STEP_STARTED` event on
  the bus for LOW actions and a `USER_APPROVAL_REQUIRED` event for
  HIGH/CRITICAL.

Example:

```python
import pytest
from automation_service.security.permission_engine import PermissionEngine
from automation_service.models import ActionRequest, ToolSpec, RiskLevel, PermissionLevel


@pytest.fixture
def engine():
    return PermissionEngine()


@pytest.mark.asyncio
async def test_low_risk_auto_allowed(engine):
    action = ActionRequest(tool="mouse.click", args={"x": 1, "y": 2})
    spec = ToolSpec(name="mouse.click", description="", input_schema={},
                    permission_level=PermissionLevel.ALLOW_ONCE, risk_level=RiskLevel.LOW)
    resp = await engine.evaluate_action(action, spec)
    assert resp.decision == PermissionLevel.ALLOW_ONCE


@pytest.mark.asyncio
async def test_critical_risk_denied_without_explicit_approval(engine):
    action = ActionRequest(tool="file.delete", args={"path": "/tmp/x"})
    spec = ToolSpec(name="file.delete", description="", input_schema={},
                    permission_level=PermissionLevel.ALLOW_ONCE, risk_level=RiskLevel.CRITICAL)
    resp = await engine.evaluate_action(action, spec)
    assert resp.decision == PermissionLevel.DENY
```

### 3.4 Scheduler — **Phase 2 — Coming Soon**

Will assert:

- A `cron="0 9 * * 1-5"` job fires Monday–Friday at 09:00 in the
  job's timezone.
- Missed schedule handling: if the service was down across a fire
  time, the next-run-at is advanced correctly.
- Concurrency limit: a workflow that is already running is not
  started again.
- Execution timeout: a workflow that exceeds
  `scheduled_jobs.execution_timeout` is killed and marked failed.

### 3.5 Variable engine — **Phase 1 — Coming Soon**

Will assert:

- `{{today}}` resolves to today's date in `YYYY-MM-DD`.
- `{{downloads_folder}}` resolves to `Path.home() / "Downloads"`.
- `{{clipboard}}` is masked in logs (the value itself is fine in
  the args dict, but logs must show `***REDACTED***`).
- Custom variables can reference built-ins:
  `{"dest": "{{downloads_folder}}/Reports"}` resolves to
  `/home/user/Downloads/Reports`.
- Variable resolution is depth-capped at 5.

### 3.6 Database

File: `tests/unit/test_database.py`

Uses an in-memory SQLite engine:

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from database.base import Base
from database.models import schema


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as session:
        yield session
```

Asserts:

- `init_db()` creates all 22 tables.
- `User` insert with duplicate `username` raises `IntegrityError`.
- `Workflow → WorkflowVersion → WorkflowRun → Task → TaskStep`
  cascades work as expected (inserting a step with a nonexistent
  `task_id` raises `IntegrityError`).
- The composite index `idx_tasks_status_created` exists (query
  `sqlite_master`).
- UUIDs are stored as 36-char strings.

### 3.7 AI adapters

File: `tests/unit/test_ai_providers.py`

Uses `pytest-asyncio` and mocks `aiohttp` / `openai` / `anthropic`
clients. Asserts:

- `get_provider("openai", config)` returns an `OpenAIProvider`
  instance.
- `get_provider("nonexistent", config)` raises `ValueError`.
- `OpenAIProvider.complete()` calls
  `client.chat.completions.create(model=..., messages=...)` with
  the right kwargs and returns `resp.choices[0].message.content`.
- `AnthropicProvider.complete()` extracts the system message and
  passes it as the `system=` kwarg.
- `OllamaProvider.complete()` POSTs to `http://localhost:11434/api/chat`
  with the right payload.
- `_risk_from_text()` classifies "delete files" as CRITICAL,
  "install software" as HIGH, "rename file" as MEDIUM, "click
  button" as LOW.

## 4. Integration tests

Integration tests use real subprocesses, a real (temp) filesystem,
and a real SQLite database. They use mock mode for the actual
side-effecting tools so no real clicks happen.

### 4.1 Electron ↔ Python — **Phase 1 — Coming Soon**

File: `tests/integration/test_electron_python_ipc.py`

Asserts:

- The service starts and `GET /health` returns 200 within 3 s.
- CORS rejects requests from `http://evil.example`.
- `POST /task/plan` without an `Authorization` header returns 401
  when `AUTOMATION_IPC_TOKEN` is set.
- `POST /task/plan` with a valid token returns a `Plan`.
- The WebSocket `/events` endpoint receives a `TASK_STARTED`
  event within 100 ms of `POST /task/run`.
- An unhandled exception publishes `UNHANDLED_ERROR` and returns 500.

### 4.2 Browser automation

File: `tests/integration/test_browser_automation.py`

Asserts (with `mock_mode=true`):

- `browser.open` returns `{"simulated": True, ...}`.
- `browser.navigate` returns `{"simulated": True, "url": ...}`.
- `browser.click` returns `{"simulated": True, "selector": ...}`.
- `browser.type` returns `{"simulated": True, "text": ...}`.
- `browser.extract` returns `{"simulated": True, "text": ""}`.
- A full workflow (`browser.open` → `browser.navigate` →
  `browser.click` → `browser.extract`) runs to completion in
  mock mode and emits 4 `STEP_COMPLETED` events.

With `mock_mode=false` (only in a Docker container with Chromium
installed), the same workflow actually navigates to
`https://example.com` and extracts its title.

### 4.3 File operations

File: `tests/integration/test_file_operations.py`

Asserts with a temp directory inside `Path.home() / "Documents"`:

- `file.read` reads a file written by `file.write`.
- `file.move` moves a file between two allowed roots.
- `file.rename` renames a file in place.
- `file.list` returns the right filenames.
- `_validate_path` rejects `../../etc/passwd` (path traversal).
- `_validate_path` rejects `C:/Windows/system32/config/SAM` on
  Windows.
- `_validate_path` accepts `Documents/report.txt`.

### 4.4 Windows automation — **Phase 1 — Coming Soon**

File: `tests/integration/test_windows_automation.py` (Windows CI only)

Asserts:

- `app.launch("notepad")` opens Notepad (mock-mode assert: returns
  `{"simulated": True, "app": "notepad"}`).
- `app.launch("rm -rf /")` is rejected (not in allowlist).
- `app.launch("notepad; rm -rf C:/")` is rejected (semicolon in
  app name).
- `window.list` returns at least one window when Notepad is
  running.
- `process.list` returns the Notepad process by name.

## 5. E2E test — the MVP success test (§79)

File: `tests/e2e/test_google_search_screenshot.py`

The MVP is complete only when the following user journey works
end-to-end:

> "Open Chrome, go to Google, search for AI automation, open the
> first result, take a screenshot, save it to my Desktop, and tell
> me when finished."

### 5.1 The 13-step assertion

| # | Step | Asserted by |
|---|---|---|
| 1 | Parse request | `POST /task/plan` returns 200 with a Plan whose `goal` matches |
| 2 | Generate plan | `Plan.steps` length > 0; first step `action == "app.launch"` |
| 3 | Display plan | (renderer assertion — `aria-label="plan-card"` is visible) |
| 4 | Request required permissions | `USER_APPROVAL_REQUIRED` event emitted on `/events` |
| 5 | Open Chrome | `STEP_COMPLETED` event for `app.launch` |
| 6 | Navigate | `STEP_COMPLETED` for `browser.navigate` to `https://www.google.com` |
| 7 | Search | `STEP_COMPLETED` for `browser.type` into `input[name='q']` |
| 8 | Open first result | `STEP_COMPLETED` for `browser.click` on first search result link |
| 9 | Capture screenshot | `STEP_COMPLETED` for `screen.capture` |
| 10 | Save screenshot | File exists in `Path.home() / "Desktop"` |
| 11 | Verify file exists | `STEP_VERIFIED` event with `strategy="file_exists"` |
| 12 | Report completion | `TASK_COMPLETED` event |
| 13 | Store execution logs | Row exists in `task_logs` with `task_id` matching the run |

### 5.2 E2E test skeleton

```python
import pytest
from pathlib import Path
from datetime import datetime

from automation_service.main import app
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    return TestClient(app)


@pytest.mark.e2e
@pytest.mark.skipif(
    not Path.home().joinpath("Desktop").exists(),
    reason="Desktop folder missing",
)
def test_google_search_screenshot(client, monkeypatch):
    # Mock mode so the test does not actually open Chrome in CI
    monkeypatch.setenv("AUTOMATION_MOCK_MODE", "true")

    # 1. Parse request
    r = client.post("/task/plan?goal=Open Chrome, search AI automation, screenshot, save to Desktop")
    assert r.status_code == 200
    plan = r.json()
    assert plan["goal"].startswith("Open Chrome")

    # 2. Plan has at least one step
    assert len(plan["steps"]) > 0

    # 4. Run plan (auto-approved because all steps are LOW/MEDIUM in mock mode)
    r = client.post("/task/run", json=plan)
    assert r.status_code == 200
    run_id = r.json()["run_id"]

    # 13. Check the run is recorded
    # (Once persistence is wired: SELECT * FROM workflow_runs WHERE id = run_id)
    assert run_id is not None
```

> The full e2e test (with the renderer in the loop) is **Phase 1 —
> Coming Soon**. The skeleton above exercises the API surface only;
> the renderer-driven variant uses Playwright to drive the Electron
> app itself.

## 6. Mock mode and dry run as testing tools (§64, §65)

Mock mode and dry run are not just safety features — they are the
primary mechanism for making the agent testable in CI.

### 6.1 Mock mode in unit tests

Every unit test sets `AUTOMATION_MOCK_MODE=true`. This guarantees:

- No real mouse moves, no real keystrokes.
- No real browser launches.
- No real subprocess spawns.
- `screen.capture` writes a placeholder PNG so file-existence
  assertions pass.

The mock return values include a `"simulated": True` flag that tests
can assert on to confirm they are in mock mode.

### 6.2 Mock mode in integration tests

Integration tests run with `mock_mode=true` by default. The
filesystem-touching tools (`file.read`, `file.write`, `file.move`)
do execute real filesystem ops because they are inherently safe
inside `ALLOWED_ROOTS`. The mouse/keyboard/screen/browser/app tools
are mocked.

### 6.3 Dry run in e2e tests

The full e2e test (`test_google_search_screenshot.py`) runs in
dry-run mode first to assert the plan is well-formed and would
execute the expected steps, then runs again in real mode against
a controlled browser session.

Dry run is also exposed in the renderer as a button on every
workflow card. Clicking "Dry Run" executes the workflow with
`mock_mode=true` for that run only, regardless of the global
setting.

## 7. Security testing (§96)

Master prompt §96 mandates tests against 12 attack classes. Each
must have a dedicated test in `tests/unit/test_security_*.py` or
`tests/integration/test_security_*.py`.

### 7.1 Command injection

File: `tests/integration/test_security_command_injection.py`

```python
def test_app_launch_rejects_shell_metacharacters(client):
    r = client.post("/automation/click", params={"x": 0, "y": 0})
    # irrelevant — the assertion is on app.launch below

    r = client.post(
        "/automation/click",  # placeholder; replace with app.launch endpoint when wired
        json={"app": "notepad; rm -rf C:/", "args": []},
    )
    assert r.status_code in (400, 403, 404)
```

The test asserts that `app.launch` rejects any `app` value
containing shell metacharacters (`;`, `|`, `&`, `` ` ``, `$()`).
The `APP_ALLOWLIST` lookup fails first because the string is not
in the allowlist, but a defensive regex also rejects the
metacharacters explicitly.

### 7.2 Path traversal

File: `tests/unit/test_security_path_traversal.py`

```python
from automation_service.tools.files import _validate_path


def test_path_traversal_rejected():
    with pytest.raises(PermissionError):
        _validate_path("download/../../../etc/passwd")


def test_blocked_system_path_rejected():
    with pytest.raises(PermissionError):
        _validate_path("/etc/passwd")


def test_windows_system_path_rejected():
    with pytest.raises(PermissionError):
        _validate_path("C:/Windows/System32/config/SAM")


def test_allowed_path_accepted(tmp_path):
    # tmp_path is inside the pytest tmp dir, not an ALLOWED_ROOTS,
    # so we monkeypatch ALLOWED_ROOTS to include tmp_path
    from automation_service.tools import files as files_mod
    files_mod.ALLOWED_ROOTS.append(tmp_path)
    p = _validate_path(tmp_path / "test.txt")
    assert str(p).startswith(str(tmp_path))
```

### 7.3 Prompt injection

File: `tests/integration/test_security_prompt_injection.py`

```python
def test_prompt_injection_does_not_change_plan(client, monkeypatch):
    # Simulate a webpage that contains "ignore previous instructions"
    # The planner should still produce a plan for the original goal.
    r = client.post("/task/plan", params={
        "goal": "Click the 'Download Report' button on the page"
    })
    assert r.status_code == 200
    plan = r.json()
    # The plan's goal must match what the user asked for, not what
    # the webpage says.
    assert plan["goal"].startswith("Click the 'Download Report'")
    # No step should send the user's password anywhere
    for step in plan["steps"]:
        assert "password" not in str(step.get("args", {})).lower()
```

### 7.4 Malicious workflow import — **Phase 2 — Coming Soon**

```python
def test_malicious_workflow_import_rejected(client):
    malicious = {
        "id": "wf_evil",
        "name": "Harmless-looking workflow",
        "nodes": [
            {"id": "1", "type": "file.delete",
             "args": {"path": "/home/user/Documents", "recursive": True}}
        ]
    }
    r = client.post("/workflow/import", json=malicious)
    assert r.status_code in (400, 403)
    # Or: status 200 with warnings list including "CRITICAL step present"
```

### 7.5 Malicious plugin — **Phase 4 — Coming Soon**

```python
def test_plugin_without_declared_permissions_rejected():
    # A plugin that tries to register a tool without declaring the
    # required permissions in its plugin.json must fail to load.
    ...
```

### 7.6 Privilege escalation

File: `tests/integration/test_security_privilege_escalation.py`

```python
def test_no_tool_can_elevate_to_admin(client):
    # No tool accepts a "sudo" or "runas" argument
    for tool_spec in client.get("/tools").json():
        schema = tool_spec["input_schema"]
        for prop_name in schema.get("properties", {}):
            assert prop_name.lower() not in {"sudo", "runas", "elevated", "admin"}
```

### 7.7 Credential leakage

File: `tests/unit/test_security_credential_leakage.py`

```python
def test_secret_masker_redacts_openai_key():
    from automation_service.security.masker import mask_secrets  # Phase 1
    text = "My key is sk-abc123def456ghi789jkl012mno345pqr678"
    masked = mask_secrets(text)
    assert "sk-abc123def456ghi789jkl012mno345pqr678" not in masked
    assert "REDACTED" in masked


def test_audit_log_does_not_store_api_key():
    # Insert an audit log entry with a request_json that contains
    # an API key; assert the persisted value has been masked.
    ...
```

### 7.8 IPC abuse

File: `tests/integration/test_security_ipc_abuse.py`

```python
def test_non_localhost_origin_rejected():
    # The service binds to 127.0.0.1, so a request from another host
    # cannot connect. But we also assert CORS rejects unknown origins.
    r = client.options("/health", headers={"Origin": "http://evil.example"})
    assert "http://evil.example" not in r.headers.get("access-control-allow-origin", "")


def test_missing_bearer_token_rejected(monkeypatch):
    monkeypatch.setenv("AUTOMATION_IPC_TOKEN", "secret")
    r = client.get("/tools")
    assert r.status_code == 401
```

### 7.9 Unauthorized tool execution

File: `tests/unit/test_security_unauthorized_tool.py`

```python
@pytest.mark.asyncio
async def test_unknown_tool_rejected_by_executor():
    from automation_service.engine.workflow_executor import WorkflowExecutor
    from automation_service.models import Plan, PlanStep, RiskLevel, PermissionLevel

    plan = Plan(
        goal="test", steps=[PlanStep(id="1", action="evil.tool")],
        required_permissions=[PermissionLevel.ALLOW_ONCE],
        overall_risk=RiskLevel.LOW,
    )
    executor = WorkflowExecutor()
    run_id = await executor.execute_plan(plan)
    status = executor.get_status(run_id)
    assert status["status"] == "failed"
```

### 7.10 Browser content injection

File: `tests/integration/test_security_browser_content_injection.py`

Asserts that a page the agent opens cannot redirect it to another
origin without a permission prompt. (Phase 2 — domain allowlist
runtime.)

### 7.11 Oversized input

File: `tests/integration/test_security_oversized_input.py`

```python
def test_oversized_goal_rejected(client):
    huge_goal = "x" * 1_000_000  # 1 MB
    r = client.post("/task/plan", params={"goal": huge_goal})
    assert r.status_code == 413  # or 400, depending on validation layer


def test_oversized_workflow_rejected(client):
    nodes = [{"id": str(i), "type": "start"} for i in range(1001)]
    r = client.post("/workflow", json={"id": "wf_big", "name": "big", "nodes": nodes})
    assert r.status_code == 400
```

### 7.12 Runaway loops

File: `tests/unit/test_security_runaway_loops.py`

```python
def test_loop_capped_at_max_loops():
    # A while loop whose predicate is always true must pause the run
    # after settings.max_loops iterations.
    ...
```

## 8. Test commands

```bash
# All unit tests
cd /home/z && pytest tests/unit -v

# All integration tests (mock mode by default)
cd /home/z && pytest tests/integration -v

# All e2e tests
cd /home/z && pytest tests/e2e -v

# Security tests only
cd /home/z && pytest tests/unit/test_security_ tests/integration/test_security_ -v

# Coverage
cd /home/z && pytest --cov=automation_service --cov=database --cov-report=term-missing tests/

# Watch mode (re-runs on file change)
cd /home/z && pytest-watch tests/unit

# Lint (Python)
cd /home/z && ruff check app/ apps/ database/
cd /home/z && black --check app/ apps/ database/

# Type check
cd /home/z && mypy apps/automation-service/automation_service/ database/
```

## 9. CI pipeline — **Phase 1 — Coming Soon**

The planned CI pipeline (GitHub Actions):

```yaml
# .github/workflows/ci.yml (planned)
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install ruff black mypy
      - run: ruff check .
      - run: black --check .
      - run: mypy apps/ database/

  unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e .[dev]
      - run: pytest tests/unit -v --cov

  integration:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e .[dev] && pip install playwright && playwright install chromium
      - run: pytest tests/integration -v

  e2e:
    runs-on: windows-latest   # E2E runs on Windows because the product targets Windows
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - uses: actions/setup-node@v4
      - run: pip install -e .[dev]
      - run: npm ci && npm run build
      - run: pytest tests/e2e -v
```

## 10. Test fixtures

File: `tests/conftest.py`

Common fixtures:

- `mock_mode` — sets `AUTOMATION_MOCK_MODE=true` for the test.
- `db_session` — yields a SQLAlchemy session against an in-memory
  SQLite database.
- `client` — yields a `fastapi.testclient.TestClient` against the
  service app.
- `tmp_allowed_root` — creates a temp directory and adds it to
  `files.ALLOWED_ROOTS` for the duration of the test.
- `fake_provider` — yields an `AIProvider` subclass whose
  `complete()` returns a canned JSON Plan.

## 11. Non-determinism in AI tests

AI tests are non-deterministic by nature. Two strategies mitigate
this:

1. **Mock the provider.** Unit tests for the planner mock
   `AIProvider.complete()` to return a canned JSON string. This
   makes the test fully deterministic and lets us assert on the
   parser's behaviour with known inputs.

2. **Property-based testing for the parser.** A `hypothesis`
   strategy generates random JSON objects and asserts that
   `PlannerAgent._parse_response` either returns a valid `Plan`
   or raises a `ValidationError` (never crashes).

```python
from hypothesis import given, strategies as st

@given(st.text())
def test_parse_response_never_crashes(random_text):
    planner = PlannerAgent(provider=None)
    plan = planner._parse_response("test goal", random_text)
    # Either a valid Plan or a fallback Plan — never an exception
    assert plan.goal == "test goal"
```

End-to-end AI tests (that call a real provider) are marked
`@pytest.mark.live_ai` and skipped in CI unless
`RUN_LIVE_AI_TESTS=1` is set.

## 12. Performance tests — **Phase 2 — Coming Soon**

Asserts the master prompt §59 requirements:

- Service startup < 3 s.
- Idle CPU < 2 %.
- 1000-action workflow completes in < 60 s (mock mode).
- Memory usage < 200 MB after a 100-step workflow.

## 13. Acceptance criteria

Per master prompt §97, the test suite is the gate for acceptance.
A release cannot ship if any of the following fail:

- All unit tests pass.
- All integration tests pass.
- All e2e tests pass (including the §79 Google search test).
- All security tests pass.
- Coverage on `apps/automation-service/` is ≥ 80 %.
- `ruff check .` is clean.
- `mypy apps/ database/` is clean.
- No `# TODO` markers in shipped code (greppable).

## 14. Phase map (testing-relevant)

| Feature | Status |
|---|---|
| `tests/` directory exists | Created (empty) |
| `conftest.py` with fixtures | **Phase 1 — Coming Soon** |
| Unit tests (parser, registry, permission engine, ...) | **Phase 1 — Coming Soon** |
| Integration tests (IPC, browser, files, Windows) | **Phase 1 — Coming Soon** |
| E2E test (§79 Google search) | **Phase 1 — Coming Soon** |
| Security test suite (§96, 12 attack classes) | **Phase 1 — Coming Soon** |
| Mock mode + dry run as test tools | Mock mode implemented; dry run is Phase 1 |
| Coverage gate at 80 % | **Phase 1 — Coming Soon** |
| CI pipeline (lint, unit, integration, e2e) | **Phase 1 — Coming Soon** |
| Performance tests (§59) | **Phase 2 — Coming Soon** |
| Hypothesis property-based tests for parser | **Phase 2 — Coming Soon** |
| Live AI tests (gated) | **Phase 2 — Coming Soon** |
