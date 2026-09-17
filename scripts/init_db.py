"""Initialize the project SQLite database with core tables.

Usage::

    python /home/z/my-project/scripts/init_db.py
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timezone

# Ensure the app package is importable
sys.path.insert(0, "/home/z")

from app.config import settings  # noqa: E402
from app.logger import logger    # noqa: E402


SCHEMA_SQL = """
-- Track environment setup metadata
CREATE TABLE IF NOT EXISTS _meta (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Subagent work-log index (mirrors entries in worklog.md)
CREATE TABLE IF NOT EXISTS worklog_entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT NOT NULL,
    agent_name  TEXT NOT NULL,
    task_summary TEXT,
    created_at  TEXT NOT NULL,
    UNIQUE(task_id)
);

-- Track MCP server invocations (best-effort)
CREATE TABLE IF NOT EXISTS mcp_invocations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    server_name TEXT NOT NULL,
    tool_name   TEXT NOT NULL,
    args_json   TEXT,
    result_json TEXT,
    started_at  TEXT NOT NULL,
    finished_at TEXT
);

-- Track skill loads
CREATE TABLE IF NOT EXISTS skill_loads (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_name  TEXT NOT NULL,
    loaded_at   TEXT NOT NULL
);
"""


def init_db() -> int:
    db_path = settings.db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Initializing SQLite database at {}", db_path)

    with sqlite3.connect(str(db_path)) as conn:
        conn.executescript(SCHEMA_SQL)
        now = datetime.now(timezone.utc).isoformat()
        conn.executemany(
            "INSERT OR REPLACE INTO _meta(key, value, updated_at) VALUES (?, ?, ?)",
            [
                ("schema_version", "1", now),
                ("created_by", "z-agent", now),
                ("project_root", str(settings.project_root), now),
                ("initialized_at", now, now),
            ],
        )

    logger.info("Database ready — schema v1")
    return 0


if __name__ == "__main__":
    sys.exit(init_db())
