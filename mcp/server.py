"""Custom project-scoped MCP server built on FastMCP.

Exposes tools that the agent can invoke via the Model Context Protocol::

    mcp run /home/z/my-project/mcp/server.py

Or register it via the project ``.mcp.json`` (already configured).
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

# Make the app package importable
sys.path.insert(0, "/home/z")

from fastmcp import FastMCP  # type: ignore

from app.config import settings
from app.logger import logger


# ---------------------------------------------------------------------------
# FastMCP server instance
# ---------------------------------------------------------------------------

mcp: FastMCP = FastMCP(
    name="z-agent-project-tools",
    version="0.1.0",
)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def project_info() -> dict[str, Any]:
    """Return resolved runtime configuration (paths, db, log level)."""
    return {
        "name": "z-agent",
        "version": "0.1.0",
        "project_root": str(settings.project_root),
        "db_path": str(settings.db_path),
        "log_level": settings.log_level,
        "skills_dir": str(settings.skills_dir),
        "agents_dir": str(settings.agents_dir),
    }


@mcp.tool()
def list_skills() -> list[dict[str, str]]:
    """List installed ClawHub skills (folders containing SKILL.md)."""
    skills_dir = settings.skills_dir
    if not skills_dir.exists():
        return []
    result: list[dict[str, str]] = []
    for p in sorted(skills_dir.iterdir()):
        skill_md = p / "SKILL.md"
        if p.is_dir() and skill_md.exists():
            # Read the first non-empty H1 line as the title
            title = p.name
            try:
                for line in skill_md.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("# "):
                        title = line[2:].strip()
                        break
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to read SKILL.md for {}: {}", p.name, exc)
            result.append({"name": p.name, "title": title, "path": str(p)})
    return result


@mcp.tool()
def read_skill(name: str) -> str:
    """Read the SKILL.md content of an installed skill by name."""
    skill_path = settings.skills_dir / name / "SKILL.md"
    if not skill_path.exists():
        raise FileNotFoundError(f"Skill '{name}' not found at {skill_path}")
    return skill_path.read_text(encoding="utf-8")


@mcp.tool()
def list_download_files() -> list[dict[str, str]]:
    """List files in the download directory (user-facing deliverables)."""
    download_dir = settings.download_dir
    if not download_dir.exists():
        return []
    return [
        {"name": p.name, "path": str(p), "size_bytes": str(p.stat().st_size)}
        for p in sorted(download_dir.iterdir()) if p.is_file()
    ]


@mcp.tool()
def db_query(sql: str) -> list[dict[str, Any]]:
    """Execute a read-only SQL query against the project SQLite database.

    Only SELECT statements are allowed; anything else raises ValueError.
    """
    s = sql.strip().lower()
    if not (s.startswith("select") or s.startswith("with")):
        raise ValueError("Only SELECT / WITH queries are permitted via this tool.")

    db_path = settings.db_path
    if not db_path.exists():
        raise FileNotFoundError(
            f"Database file missing at {db_path}. Run `python "
            f"/home/z/my-project/scripts/init_db.py` first."
        )

    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(sql)
        rows = [dict(r) for r in cur.fetchall()]
    return rows


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    logger.info("Starting z-agent MCP server on stdio")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
