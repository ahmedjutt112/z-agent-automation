# z-agent

A modular agent runtime built on Python 3.12 + FastMCP + ClawHub skills.

## Quick Start

```bash
# 1. Install dependencies (if not already done)
cd /home/z && uv sync

# 2. Initialize the database
python /home/z/my-project/scripts/init_db.py

# 3. Smoke-test the CLI
zai info           # Print resolved runtime configuration
zai setup          # Ensure all expected directories exist
zai skills         # List installed ClawHub skills
zai mcp --validate # Validate MCP server config
```

## Project Layout

```
/home/z/                            ← Python package root
├── pyproject.toml                  ← z-agent project + `zai` console script
├── uv.lock
├── .venv/                          ← Python 3.12 venv
├── app/                            ← Python package
│   ├── __init__.py
│   ├── main.py                     ← `main()` — entry point for `zai`
│   ├── config.py                   ← Settings dataclass + .env loader
│   └── logger.py                   ← loguru logger
└── my-project/                     ← Runtime workspace (git repo)
    ├── .env                        ← DATABASE_URL + optional API keys (gitignored)
    ├── .env.example                ← Template (committed)
    ├── .mcp.json                   ← MCP server registry
    ├── AGENTS.md                   ← Subagent conventions
    ├── README.md                   ← THIS FILE
    ├── worklog.md                  ← Shared multi-agent worklog
    ├── db/custom.db                ← SQLite database
    ├── agents/                     ← Per-agent prompt snippets
    ├── mcp/server.py               ← Custom FastMCP server
    ├── scripts/init_db.py          ← DB initializer
    ├── config/                     ← Static config
    ├── skills/                     ← ClawHub skills catalog (50+)
    ├── download/                   ← User-facing deliverables
    └── upload/                     ← Scratch uploads
```

## Configuration

Environment variables are loaded from `/home/z/my-project/.env` (see
`.env.example` for the full list). The most important ones:

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `file:/home/z/my-project/db/custom.db` | SQLite database URL |
| `LOG_LEVEL` | `INFO` | loguru log level |
| `LOG_FILE` | (unset) | Optional rotating log file |
| `SKILLS_DIR` | `/home/z/my-project/skills` | ClawHub skills root |
| `AGENTS_DIR` | `/home/z/my-project/agents` | Per-agent prompts |
| `DOWNLOAD_DIR` | `/home/z/my-project/download` | User-facing deliverables |
| `UPLOAD_DIR` | `/home/z/my-project/upload` | Scratch uploads |

## CLI Commands

The `zai` console script is registered in `pyproject.toml` and provides:

```bash
zai info              # Print resolved runtime configuration as JSON
zai setup             # Ensure all expected directories exist + init SQLite
zai setup --check-skills   # Same as above, plus count installed skills
zai skills            # List installed ClawHub skills
zai mcp               # Print MCP server config (raw JSON)
zai mcp --validate    # Validate config and report registered servers
```

## Skills

The project ships with 50+ ClawHub skills under `skills/`. Each skill lives in
its own directory and contains a `SKILL.md` describing how to invoke it.

Common skills: `docx`, `pdf`, `xlsx`, `pptx`, `charts`, `web-search`,
`web-reader`, `image-generation`, `image-edit`, `image-search`, `ASR`, `TTS`,
`VLM`, `LLM`, `fullstack-dev`, `coding-agent`, `ui-ux-pro-max`, `design`,
`interview-prep`, `study-buddy`, `podcast-generate`, `market-research-reports`,
`literature-survey`, `experiment-suite`, `dream-interpreter`, `gift-evaluator`,
`finance`, `stock-analysis-skill`, `aminer-daily-paper`, `aminer-deep-search`,
`aminer-free-academic`, `ai-news-collectors`, `cheat-sheet`, `content-strategy`,
`contentanalysis`, `auto-target-tracker`, `job-intent-tracker`, `version-management`,
`writing-plans`, `mindfulness-meditation`, `anti-pua`, `storyboard-manager`,
`visual-design-foundations`, `qingyan-research`, `get-fortune-analysis`,
`gaokao-*` (volunteer / recommend / collect / report), `web-shader-extractor`,
`skill-creator`, `skill-finder-cn`, `agent-browser`, `image-understand`, `task-review`.

## MCP Servers

The MCP registry lives at `/home/z/my-project/.mcp.json`. To run the custom
project-tools server standalone:

```bash
python /home/z/my-project/mcp/server.py
```

Tools exposed by the custom server:

- `project_info()` — resolved runtime configuration
- `list_skills()` — list installed ClawHub skills
- `read_skill(name)` — read a skill's `SKILL.md` content
- `list_download_files()` — list user-facing deliverables
- `db_query(sql)` — read-only SQL against the project SQLite database

## Subagents

Multi-agent work is coordinated via `AGENTS.md`. Key conventions:

1. **Task IDs** — every delegated task gets an ID reflecting global order and
   parallelism (e.g. `2-a`, `2-b`).
2. **Worklog** — every agent reads `/home/z/my-project/worklog.md` before
   working and appends a new section when done (append-only).
3. **Read-before-write** — read the relevant files before modifying anything.
4. **Deliverables** — all final outputs go under `/home/z/my-project/download/`.

## Development

```bash
# Add a new Python dependency
cd /home/z && uv add <package>

# Run the test suite
cd /home/z && pytest

# Format / lint (if configured)
cd /home/z && ruff check app/
```

## License

Internal use only — © Z User 2026.
