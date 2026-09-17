"""Top-level pytest config for tests under /home/z/my-project/tests/.

These tests cover database models (unit/) and the end-to-end MVP scenario
(e2e/). They share the in-memory SQLite fixture and the mock-mode env setup
with the automation-service test suite.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


PROJECT_ROOT = Path("/home/z/my-project")
AUTOMATION_ROOT = PROJECT_ROOT / "apps" / "automation-service"

for p in (str(PROJECT_ROOT), str(AUTOMATION_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

# Mock-mode + no AI keys (forces fallback planner).
os.environ.setdefault("AUTOMATION_MOCK_MODE", "true")
os.environ.pop("OPENAI_API_KEY", None)
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("AUTOMATION_IPC_TOKEN", None)


# ---------------------------------------------------------------------------
# Automation-service settings + tool discovery
# ---------------------------------------------------------------------------


from automation_service.config import settings  # noqa: E402
from automation_service.engine.tool_registry import tool_registry  # noqa: E402
from automation_service.security.kill_switch import kill_switch  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _discover_tools() -> None:
    if not tool_registry.all():
        tool_registry.discover()


@pytest.fixture(autouse=True)
def mock_settings() -> Iterator[None]:
    prev = settings.mock_mode
    settings.mock_mode = True
    kill_switch.reset()
    yield
    settings.mock_mode = prev
    kill_switch.reset()


@pytest.fixture()
def tmp_screenshots_dir(tmp_path: Path) -> Path:
    prev = settings.screenshots_dir
    new = tmp_path / "screenshots"
    new.mkdir(parents=True, exist_ok=True)
    settings.screenshots_dir = new
    yield new
    settings.screenshots_dir = prev


@pytest.fixture()
def tmp_workflows_dir(tmp_path: Path) -> Path:
    prev = settings.workflows_dir
    new = tmp_path / "workflows"
    new.mkdir(parents=True, exist_ok=True)
    settings.workflows_dir = new
    yield new
    settings.workflows_dir = prev


@pytest.fixture()
def client(
    tmp_screenshots_dir: Path,
    tmp_workflows_dir: Path,
) -> Iterator:
    from fastapi.testclient import TestClient
    from automation_service.main import app

    kill_switch.reset()
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def db_session() -> Iterator[Session]:
    """In-memory SQLite session bound to the full ORM schema."""
    from database.base import Base
    from database.models import schema  # noqa: F401

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
