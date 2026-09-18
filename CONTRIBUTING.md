# Contributing to z-agent

Thanks for helping build the AI PC/Laptop Automation Agent. This guide covers
local setup, the project's architecture, the code-style bar every PR must
meet, and the master-prompt compliance checklist.

## 1. Development setup

### Prerequisites

- **Python 3.12+** (the `automation-service` backend targets `py312`).
- **Node 20+** (the Electron desktop shell).
- **[uv](https://github.com/astral-sh/uv)** for Python dependency management.
- On Linux: `libgtk-3-dev libnotify-dev libnss3 libxss1 libxtst6 xdg-utils`
  for Electron native modules.

### Bootstrap

```bash
# 1. Python env + deps (pyproject.toml lives at /home/z)
cd /home/z
uv sync

# 2. Frontend deps
cd /home/z/my-project/apps/desktop
npm ci      # or: npm install

# 3. Environment file
cp /home/z/my-project/.env.example /home/z/my-project/.env
# Edit .env: set DATABASE_URL, AUTOMATION_MOCK_MODE, IPC token, etc.

# 4. Initialise the SQLite DB
uv run python /home/z/my-project/scripts/init_db.py

# 5. Start the desktop dev shell (Vite on 5173 + Electron)
cd apps/desktop
npm run dev
```

In mock mode (`AUTOMATION_MOCK_MODE=true`) the entire stack runs without any
real OS control or network credentials — every tool returns deterministic
sample data. Use this for front-end work and unit tests.

## 2. Architecture overview

The repository is a small monorepo:

```
/home/z/
├── pyproject.toml                    Python project root (uv)
└── my-project/
    ├── apps/
    │   ├── automation-service/       FastAPI backend + automation engine
    │   └── desktop/                  Electron + React + Vite frontend
    ├── database/                     SQLAlchemy models + Alembic migrations
    ├── plugins/                      Plugin packages (loaded by PluginManager)
    ├── scripts/                      Operational scripts (init_db, …)
    ├── workflows/                    JSON workflow definitions
    ├── tests/                        Python tests (unit / integration / e2e)
    └── docs/                         Architecture, security, AI-agent docs
```

Deep dives:

- `docs/architecture.md` — overall system design.
- `docs/automation-engine.md` — workflow executor, tool registry, scheduler.
- `docs/database.md` — schema, migrations, query patterns.
- `docs/security.md` — permission engine, secrets handling, audit log.
- `docs/testing.md` — test layout and conventions.

The desktop shell (`apps/desktop`) talks to the automation-service over
localhost HTTP. In dev, Electron spawns Vite on port 5173 and waits for it
before loading the renderer; in production the renderer is built to
`renderer/dist/` and loaded from `file://`.

## 3. Code style

### TypeScript (frontend)

- `tsconfig.json` runs in **strict** mode with `noUnusedLocals`,
  `noUnusedParameters`, `noImplicitReturns`, `noFallthroughCasesInSwitch`.
- Run `npm run typecheck` before pushing — `tsc --noEmit` must be clean.
- Prettier config (`.prettierrc`): single quotes, trailing commas, 100 cols.
- ESLint config (`.eslintrc.json`): `eslint:recommended` +
  `@typescript-eslint/recommended` + `react` + `react-hooks`.
- Imports use the `@/` alias → `renderer/src/`.

### Python (backend)

- All public functions must have **type hints** (master prompt §94).
- **Ruff** is the linter/formatter of record:
  - `uv run ruff check apps/automation-service/ database/ tests/`
  - `uv run ruff format apps/automation-service/ database/ tests/`
- Selected rule families: `E F W I N B C4 UP SIM`. Line length is 100 but
  `E501` is ignored (formatter handles wrapping).
- Black is also configured for contributors who haven't adopted Ruff yet;
  its output matches Ruff format on the same 100-col / double-quote profile.

### Pre-commit checklist

```bash
# Python
uv run ruff check --fix apps/automation-service/ database/ tests/
uv run ruff format apps/automation-service/ database/ tests/
uv run pytest -q

# Frontend
cd apps/desktop
npm run typecheck
npm run lint
npm run format
npm run test
```

## 4. Testing

| Layer          | Runner     | Location                                    | Notes                                            |
| -------------- | ---------- | ------------------------------------------- | ------------------------------------------------ |
| Python unit    | pytest     | `apps/automation-service/tests/`            | Mock mode by default; use `-m integration`       |
| Python e2e     | pytest     | `tests/e2e/`                                | MVP search/screenshot flows                      |
| Frontend unit  | vitest     | `apps/desktop` (co-located with source)     | Run via `npm run test`                            |
| CI             | GitHub Actions | `.github/workflows/ci.yml`             | python-tests + python-lint + frontend-build + release |

Pytest config lives in `/home/z/pyproject.toml` under
`[tool.pytest.ini_options]` with `asyncio_mode = "auto"`. The
`AUTOMATION_MOCK_MODE=true` env var forces the entire backend into mock
mode so tests run without network credentials or real OS control.

## 5. Master prompt compliance checklist

Before requesting review, confirm:

- [ ] **§5** — New IPC endpoints require a bearer token via
      `Depends(verify_ipc_token)`.
- [ ] **§9 / §10** — Risky operations declare a `risk_level`
      (`low`/`medium`/`high`/`critical`) and require explicit approval for
      `high` / `critical`.
- [ ] **§55** — Filesystem operations validate paths against the configured
      allowlist; blocked paths return 403.
- [ ] **§57** — Secrets are never logged. Token references go through
      `mask()` from `automation_service.security.credentials`.
- [ ] **§59** — Long-running tasks are async; the main process never blocks
      on I/O. Startup time < 3 seconds, low idle CPU.
- [ ] **§64** — Every external integration has a mock-mode path so tests
      and CI run without real credentials.
- [ ] **§90** — Updates flow through `automation_service/update/manager.py`
      with signature verification and atomic rollback. The Electron
      `electron-builder` publish config points at GitHub Releases but does
      NOT wire `autoUpdater` into the main process — the backend owns the
      update lifecycle.
- [ ] **§94** — TypeScript strict mode on; Python type hints on public
      APIs; Ruff + Prettier both clean.

## 6. Worklog protocol

Every subagent (LLM-driven or script-driven) must follow the protocol in
[`AGENTS.md`](./AGENTS.md):

1. **Read** `worklog.md` end-to-end before any write.
2. **Append** a new section (do not overwrite) when your Task ID is done,
   using the format documented in AGENTS.md §4.
3. The orchestrator assigns Task IDs (`1`, `2`, `2-a`, `2-b`, …). Echo
   your Task ID in your first log line and your worklog section.

Human contributors don't need to write worklog entries, but should review
recent entries before opening a PR so they don't collide with in-flight
agent work.

## 7. Security guidelines

- **Never commit `.env`.** It is gitignored. Use `.env.example` as the
  template for new contributors.
- **Secrets belong in the credentials manager**, not in code. Use the
  `automation_service.security.credentials` module — secrets are stored
  encrypted in the `api_credentials` table and only ever surfaced through
  `mask()` in logs and API responses.
- **OAuth tokens** are persisted via `oauth.store_tokens()` to the
  `api_credentials` table with `metadata_json` carrying the refresh token
  (never exposed via the status endpoint).
- **IPC bearer tokens** are read from `AUTOMATION_IPC_TOKEN` (or
  `~/.z-agent/ipc_token`); they are never logged and never sent in
  query strings.
- **Screenshots / recordings** may contain PII. They are written to
  `settings.screenshots_dir` and access is gated by the permission engine
  (§9/§10). Tests must use the `tmp_screenshots_dir` fixture so they
  never write to the real screenshots directory.
- **Dependencies**: pin every new dep in `pyproject.toml` (Python) or
  `apps/desktop/package.json` (Node). Reviewer must check the dep isn't
  pulling in a known-vulnerable transitive.

## 8. Opening a PR

1. Branch from `develop` (or `main` for hotfixes).
2. Title: `[<area>] <imperative summary>` — e.g.
   `[desktop] add per-step screenshot viewer`.
3. Description must include:
   - What changed and why (link the relevant master-prompt section).
   - How it was tested (which tests were added / run).
   - Screenshots / screen recordings for UI changes.
4. CI must be green: `python-tests`, `python-lint`, `frontend-build`.
5. Tag a maintainer for review.

Releases are cut by tagging `vX.Y.Z` on `main`. The `release` job in
`ci.yml` then builds Windows / macOS / Linux installers and uploads them
to GitHub Releases for the backend `UpdateManager` to pick up.
