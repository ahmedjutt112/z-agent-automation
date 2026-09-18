"""Pytest configuration / fixtures for the automation-service test suite.

Master prompt section 64 mandates that every test runs in mock mode (no real
mouse / keyboard / browser / network I/O). This file:

1. Inserts ``apps/automation-service`` and ``/home/z/my-project`` onto sys.path
   so ``from automation_service.main import app`` works from any cwd.
2. Sets ``AUTOMATION_MOCK_MODE=true`` before the app is imported.
3. Provides a FastAPI ``TestClient`` fixture whose lifespan runs
   ``tool_registry.discover()`` once per session.
4. Provides an in-memory SQLAlchemy session fixture used by the database
   model tests under ``tests/unit/``.
5. Provides a ``mock_settings`` fixture that pins ``settings.mock_mode=True``
   for the duration of every test (defensive — even if a stray env var leaks).

Integration tests (marked with ``@pytest.mark.integration``) are SKIPPED by
default. They only run when the ``--run-integration`` flag is passed to
pytest AND the relevant credentials are present in env vars. See
``tests/test_integration_real.py``.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


# ---------------------------------------------------------------------------
# sys.path setup — must happen before any automation_service import
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path("/home/z/my-project")
AUTOMATION_ROOT = PROJECT_ROOT / "apps" / "automation-service"

for p in (str(AUTOMATION_ROOT), str(PROJECT_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

# Force mock mode BEFORE importing the app (config.py reads this at import).
os.environ.setdefault("AUTOMATION_MOCK_MODE", "true")
os.environ.pop("OPENAI_API_KEY", None)        # force fallback planner
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("AUTOMATION_IPC_TOKEN", None)   # no auth required in tests


from automation_service.config import settings  # noqa: E402
from automation_service.engine.tool_registry import tool_registry  # noqa: E402
from automation_service.security.kill_switch import kill_switch  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


# ---------------------------------------------------------------------------
# pytest CLI option: --run-integration
# ---------------------------------------------------------------------------


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the ``--run-integration`` CLI flag.

    When passed, integration tests (marked with ``@pytest.mark.integration``)
    are NOT skipped. Otherwise they are skipped so the default test suite
    runs without network access or real credentials.
    """
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run real-credential integration tests (skipped by default).",
    )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Skip ``@pytest.mark.integration`` tests unless ``--run-integration``
    was passed on the command line.
    """
    if config.getoption("--run-integration"):
        return  # The flag was passed — don't skip anything.
    skip_integration = pytest.mark.skip(
        reason="Integration test — pass --run-integration to enable.",
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)


# ---------------------------------------------------------------------------
# Session-scoped: discover tools exactly once
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def _discover_tools() -> None:
    """Run tool discovery exactly once for the whole test session."""
    # discover() is idempotent for the registry only when re-running from
    # the same process; tools already registered would raise ValueError.
    # Guard against re-entry by checking the registry size first.
    if not tool_registry.all():
        tool_registry.discover()


# ---------------------------------------------------------------------------
# Function-scoped: mock mode + clean state
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_settings() -> Iterator[None]:
    """Pin mock_mode=True and reset kill_switch between tests."""
    prev_mock = settings.mock_mode
    settings.mock_mode = True
    # Reset kill_switch so a previous test's engage() doesn't bleed in.
    kill_switch.reset()
    yield
    settings.mock_mode = prev_mock
    kill_switch.reset()


@pytest.fixture()
def tmp_screenshots_dir(tmp_path: Path) -> Path:
    """Redirect screenshots_dir to a tmp path so tests don't pollute the
    real download folder. Restores the original afterwards."""
    prev = settings.screenshots_dir
    new = tmp_path / "screenshots"
    new.mkdir(parents=True, exist_ok=True)
    settings.screenshots_dir = new
    yield new
    settings.screenshots_dir = prev


@pytest.fixture()
def tmp_workflows_dir(tmp_path: Path) -> Path:
    """Redirect workflows_dir to a tmp path."""
    prev = settings.workflows_dir
    new = tmp_path / "workflows"
    new.mkdir(parents=True, exist_ok=True)
    settings.workflows_dir = new
    # Wipe any leftover JSON files the previous test may have written.
    for p in new.glob("*.json"):
        p.unlink()
    yield new
    settings.workflows_dir = prev


# ---------------------------------------------------------------------------
# FastAPI TestClient
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(
    tmp_screenshots_dir: Path,
    tmp_workflows_dir: Path,
) -> Iterator[TestClient]:
    """Yield a FastAPI TestClient. Uses ``with`` so the lifespan startup
    (which calls ensure_runtime_dirs + tool_registry.discover) runs."""
    from automation_service.main import app

    # Ensure the kill_switch is disengaged before each test
    kill_switch.reset()

    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# In-memory SQLAlchemy session — used by tests/unit/test_database_models.py
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_session() -> Iterator[Session]:
    """Create a fresh in-memory SQLite database and yield a session bound
    to it. All schema tables are created from the ORM models in
    ``database.models.schema`` so the test never touches the real
    ``db/custom.db`` file."""
    # Import lazily so the automation_service tests above don't pull SQLAlchemy
    # in unless a test actually asks for it.
    from database.base import Base
    from database.models import schema  # noqa: F401  (registers metadata)

    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


# ---------------------------------------------------------------------------
# Async helper for pytest-asyncio tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def event_recorder():
    """Return a list + a callable that appends events to it.

    Usage::

        events = event_recorder()
        event_bus.on("TASK_COMPLETED", events.append)  # append receives payload only
        # ... trigger code ...
        assert any(e.get("run_id") for e in events)
    """
    record: list = []

    def _make_handler(event_type: str):
        def _handler(payload: dict) -> None:
            record.append({"type": event_type, "payload": payload})
        return _handler

    record.attach = _make_handler  # type: ignore[attr-defined]
    return record
