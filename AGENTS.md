# AGENTS.md — Conventions for Subagents Working on z-agent

> This file is the **single source of truth** for any agent (LLM-driven or
> script-driven) operating inside this project. Read it BEFORE you start
> working — every time, no exceptions.

## 1. Project Layout

```
/home/z/                            ← Python package root (pyproject.toml lives here)
├── pyproject.toml                  ← z-agent project + zai console script
├── uv.lock
├── .venv/                          ← Python 3.12 venv
├── app/                            ← THE Python package
│   ├── __init__.py
│   ├── main.py                     ← exposes main() referenced by `zai`
│   ├── config.py                   ← Settings dataclass + .env loader
│   └── logger.py                   ← loguru-based logger
└── my-project/                     ← Runtime workspace (git repo)
    ├── .env                        ← DATABASE_URL + optional keys (gitignored)
    ├── .env.example                ← template (committed)
    ├── .mcp.json                   ← MCP server registry
    ├── .claude/                    ← Claude Code config drop-in
    ├── AGENTS.md                   ← THIS FILE
    ├── README.md                   ← Project README
    ├── worklog.md                  ← Shared multi-agent work log (append-only)
    ├── db/custom.db                ← SQLite database (init_db.py)
    ├── agents/                     ← Per-agent prompt snippets
    ├── mcp/server.py               ← Custom FastMCP server
    ├── scripts/                    ← Helper scripts (init_db.py, etc.)
    ├── config/                     ← Static config files
    ├── skills/                     ← ClawHub skills catalog (50+ skills)
    ├── download/                   ← User-facing deliverables (committed README only)
    └── upload/                     ← Scratch upload dir
```

## 2. Read-Before-Write Rule (CRITICAL)

Every agent MUST, before doing any write:

1. Read `/home/z/my-project/worklog.md` to understand what previous agents have done.
2. Read `/home/z/my-project/.env` (if env vars are needed).
3. Read the relevant section of `README.md`.

Skipping these reads risks producing duplicate work or breaking earlier outputs.

## 3. Task IDs

Every subagent task gets an ID that reflects global order and parallelism:

- Sequential: `1`, `2`, `3`, ...
- Parallel branches: `2-a`, `2-b`, `2-c` (all under parent `2`).

The orchestrator assigns the Task ID when delegating via the `Task` tool. The
subagent MUST echo this Task ID in:

1. Its first log line ("Starting Task ID=2-a").
2. The worklog entry it appends when done (see below).

## 4. Worklog Protocol

The shared worklog lives at `/home/z/my-project/worklog.md`. It is
**append-only** and shared across ALL agents (do NOT create per-agent log files).

### Read Phase

Before starting work, the agent reads the worklog end-to-end to discover:

- Which tasks have been completed (so we don't redo them).
- Which decisions were made (so we stay consistent).
- Where artifacts were saved (so we can reuse them).

### Write Phase

After finishing a Task ID, the agent appends a new section to the worklog using
this EXACT format:

```markdown
---
Task ID: <task id, e.g. 2-a>
Agent: <agent name, e.g. general-purpose / Explore / full-stack-developer>
Task: <the task you were asked to do>

Work Log:
- <concrete step 1>
- <concrete step 2>
- ...

Stage Summary:
- <key results / important decisions / produced artifacts>
```

Rules:

- Start the section with a line containing exactly `---`.
- Do NOT overwrite existing content. Use `Write` tool with the existing file
  content + your new section appended (or use `Edit` to append).
- Write substantive logs — not one-liners. List concrete steps and decisions.

## 5. File Output Rules

- **All deliverable files** MUST live under `/home/z/my-project/download/`.
- **All scripts** MUST live under `/home/z/my-project/scripts/` (per Script Persistence Rule).
- **All agent prompt snippets** MUST live under `/home/z/my-project/agents/`.
- **All MCP server code** MUST live under `/home/z/my-project/mcp/`.
- NEVER write to `/tmp`, `~`, or system directories.

## 6. Skill Invocation

Skills (in `/home/z/my-project/skills/`) are loaded via the `Skill` tool with
`command="<skill-name>"` — never by reading SKILL.md directly during a run.

Common skills:

| Skill | Purpose |
|---|---|
| `docx` | Word document creation/editing |
| `pdf` | PDF generation (ReportLab / Playwright / LaTeX) |
| `xlsx` | Excel workbook creation/editing |
| `pptx` | PowerPoint deck creation/editing |
| `charts` | Data charts and structural diagrams |
| `web-search` | Live web search via Z.ai SDK |
| `web-reader` | Article content extraction |
| `image-generation` / `image-edit` / `image-search` | Visual asset work |
| `ASR` / `TTS` / `VLM` / `LLM` | Z.ai SDK media tools |
| `fullstack-dev` | Next.js 16 + Prisma + Tailwind CSS scaffolding |

Read the corresponding `skills/<name>/SKILL.md` ONLY when you need to understand
the skill's internals — never as part of the normal execution flow.

## 7. MCP Servers

The MCP server registry lives at `/home/z/my-project/.mcp.json`. Currently
registered:

| Name | Purpose |
|---|---|
| `filesystem` | Read/write the project workspace |
| `sqlite` | Query the project SQLite DB (`/home/z/my-project/db/custom.db`) |
| `web-search` | Fetch arbitrary URLs and return markdown |
| `project-tools` | Custom FastMCP server (`mcp/server.py`) exposing project_info / list_skills / read_skill / list_download_files / db_query |

The custom server can be run standalone:

```bash
python /home/z/my-project/mcp/server.py
```

## 8. Database

SQLite path: `/home/z/my-project/db/custom.db` (configured via `DATABASE_URL`
in `.env`).

Schema is initialized by `python /home/z/my-project/scripts/init_db.py`. Tables:

- `_meta` — key/value runtime metadata
- `worklog_entries` — mirrors worklog.md entries
- `mcp_invocations` — tracks MCP tool calls (best-effort)
- `skill_loads` — tracks skill invocations

Use `app.config.settings.db_path` to get the path programmatically.

## 9. Logging

Use the project logger, not `print()`:

```python
from app.logger import logger
logger.info("hello {}", name)
logger.error("failed: {}", exc)
```

Log level defaults to `INFO`. Override with `LOG_LEVEL=DEBUG` in `.env`.

## 10. Verification Before Reporting Done

Before reporting a task as complete:

1. Run `python -c "from app.main import main; main([])"` to verify imports work.
2. Run `python /home/z/my-project/scripts/init_db.py` to verify DB is healthy.
3. Run `zai info` and `zai mcp --validate` for sanity.
4. Append your worklog entry.
5. THEN report completion to the orchestrator.

If any verification fails, do NOT mark the task complete — escalate.
