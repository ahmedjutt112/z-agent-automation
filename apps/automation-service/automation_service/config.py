"""Configuration for the Automation Service.

Loads from environment variables and ``/home/z/my-project/.env``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


PROJECT_ROOT = Path("/home/z/my-project")
AUTOMATION_ROOT = PROJECT_ROOT / "apps" / "automation-service"


class ServiceSettings(BaseModel):
    """Pydantic-validated settings — keeps config typed and serializable."""

    # Service
    service_name: str = "automation-service"
    service_version: str = "0.1.0"
    host: str = "127.0.0.1"  # NEVER bind to 0.0.0.0 — see master prompt §5
    port: int = 8765

    # Paths
    project_root: Path = PROJECT_ROOT
    automation_root: Path = AUTOMATION_ROOT
    db_path: Path = PROJECT_ROOT / "db" / "custom.db"
    workflows_dir: Path = PROJECT_ROOT / "workflows"
    templates_dir: Path = PROJECT_ROOT / "templates"
    screenshots_dir: Path = PROJECT_ROOT / "download" / "screenshots"
    logs_dir: Path = PROJECT_ROOT / "logs"

    # Security
    mock_mode: bool = True  # §64 Mock Mode — safe default
    emergency_stop_shortcut: str = "ctrl+shift+esc"  # §11 — configurable
    max_actions_per_minute: int = 120  # §88 Rate Limiting
    max_ai_calls_per_task: int = 25
    max_task_duration_seconds: int = 1800
    max_loops: int = 1000
    max_file_operations: int = 500
    max_browser_tabs: int = 8

    # AI defaults (overridable per-task)
    default_ai_provider: str = "openai"
    default_ai_model: str = "gpt-4o-mini"
    use_local_model_first: bool = False
    use_vision_only_when_required: bool = True
    min_vision_confidence: float = 0.85  # §86 — don't guess if low

    # Browser
    browser_default: str = "chrome"
    browser_user_data_dir: Optional[Path] = None

    # Logging
    log_level: str = "INFO"
    log_file: Optional[Path] = PROJECT_ROOT / "logs" / "automation-service.log"
    audit_log_file: Path = PROJECT_ROOT / "logs" / "audit.log"

    # IPC
    ipc_token: Optional[str] = None  # if set, all API calls must include bearer token

    @classmethod
    def from_env(cls) -> "ServiceSettings":
        """Load from environment variables."""
        return cls(
            host=os.getenv("AUTOMATION_HOST", "127.0.0.1"),
            port=int(os.getenv("AUTOMATION_PORT", "8765")),
            mock_mode=os.getenv("AUTOMATION_MOCK_MODE", "true").lower() == "true",
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            default_ai_provider=os.getenv("DEFAULT_AI_PROVIDER", "openai"),
            default_ai_model=os.getenv("DEFAULT_AI_MODEL", "gpt-4o-mini"),
            use_local_model_first=os.getenv("USE_LOCAL_MODEL_FIRST", "false").lower() == "true",
            ipc_token=os.getenv("AUTOMATION_IPC_TOKEN"),
        )


# Module-level singleton
settings = ServiceSettings.from_env()


def ensure_runtime_dirs() -> None:
    """Create directories the service expects to write into."""
    for d in (
        settings.workflows_dir,
        settings.templates_dir,
        settings.screenshots_dir,
        settings.logs_dir,
        settings.db_path.parent,
    ):
        d.mkdir(parents=True, exist_ok=True)
