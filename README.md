# z-agent — AI PC/Laptop Automation Agent

A production-grade desktop automation platform that lets you control and automate your computer through natural-language instructions. Combines AI agents, desktop RPA, browser automation, file management, scheduled workflows, task recording, and 52+ AI provider integrations with strict security controls.

> **Status**: Foundation complete. 213 tests passing. Mock mode default-on for safe testing.

## What it does

Type a goal like:

> "Open Chrome, search for AI automation, take a screenshot of the first result, save it to my Desktop, and notify me when finished."

The AI:
1. Understands the request
2. Generates a structured plan (goal, steps, risk level, side effects, duration)
3. Asks for confirmation when needed (HIGH/CRITICAL risk)
4. Executes through registered tools (mouse, keyboard, browser, files, etc.)
5. Verifies results and self-heals when UI changes
6. Records every action with audit logs

## Architecture

```
Electron Desktop App  ──localhost IPC──  Python Automation Service
       (React + Vite + Tailwind)              (FastAPI on 127.0.0.1:8765)
                                                    │
                                                    ├── Tool Registry (25 tools)
                                                    ├── Permission Engine (4 risk levels)
                                                    ├── Workflow Executor (retry, fallback, checkpoint)
                                                    ├── Scheduler (APScheduler + 8 trigger types)
                                                    ├── AI Providers (52 providers + Vercel Gateway)
                                                    ├── Integrations (OAuth + Email + WhatsApp + Telegram + Discord)
                                                    ├── Plugin Manager
                                                    └── Event Bus (WebSocket live updates)
                                                          │
                                                          └── Turso libSQL cloud DB (22 tables)
```

## Project layout

```
apps/
├── desktop/                    # Electron + React desktop shell
│   ├── electron/main.ts        # contextIsolation + CSP + preload
│   ├── electron/preload.ts     # contextBridge API
│   └── renderer/               # React + Vite + Tailwind + Zustand
│       └── src/pages/          # Dashboard, AI Agent, Workflows, Integrations, Settings
└── automation-service/         # Python FastAPI service
    ├── ai_providers/           # 52 AI providers + Vercel Gateway
    └── automation_service/
        ├── agents/             # Planner, Executor, Observer, Verification, Recovery
        ├── ai_providers/       # OpenAI, Anthropic, Gemini, Cohere, Bedrock, Vertex, etc.
        ├── api/                # OAuth + Integration routers
        ├── engine/             # tool_registry, event_bus, workflow_executor, variables, control_flow, self_healing, recorder
        ├── integrations/       # OAuth + Email + WhatsApp + Telegram + Discord
        ├── plugins/            # Plugin manager (master prompt §53)
        ├── scheduler/          # APScheduler + 8 trigger types
        ├── security/           # credentials, permission_engine, kill_switch
        ├── tools/              # mouse, keyboard, screen, files, apps, browser, notifications
        ├── config.py
        ├── main.py             # FastAPI entry point
        └── models.py           # Pydantic models (Plan, Workflow, etc.)
database/
├── base.py                     # SQLAlchemy 2.x engine (Turso libSQL or local SQLite)
├── models/schema.py            # 22 ORM models
└── migrations/                 # Alembic
plugins/hello_world/            # Example plugin
docs/                           # 7 architecture docs (architecture, security, database, automation-engine, ai-agent, workflows, testing)
tests/                          # unit + integration + e2e
worklog.md                      # Multi-agent worklog (append-only)
```

## Quick start

### Backend (Python)

```bash
# Install dependencies
cd /home/z && uv sync

# Initialize database (creates 22 tables on Turso)
python /home/z/my-project/scripts/init_db.py

# Run Alembic migrations (optional, for fresh DB)
cd /home/z/my-project && python -m alembic upgrade head

# Start the automation service
cd /home/z/my-project/apps/automation-service
uvicorn automation_service.main:app --reload --host 127.0.0.1 --port 8765

# Smoke test
zai info                      # Print resolved runtime config
zai providers list            # List 52 AI providers + credential status
zai sync-models               # Sync available models from providers
zai skills                    # List installed ClawHub skills
zai mcp --validate            # Validate MCP server config
```

### Frontend (Electron)

```bash
cd /home/z/my-project/apps/desktop
npm install
npm run dev                    # Starts Vite + Electron in dev mode
```

### Tests

```bash
# Full test suite
cd /home/z && uv run pytest /home/z/my-project/apps/automation-service/tests/ /home/z/my-project/tests/ -q

# Specific module
uv run pytest /home/z/my-project/apps/automation-service/tests/test_scheduler.py -v
```

## Configuration

All secrets live in `/home/z/my-project/.env` (gitignored). See `.env.example` for the full template.

### Critical environment variables

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Turso libSQL URL (e.g. `libsql://your-db.turso.io`) |
| `TURSO_AUTH_TOKEN` | Turso auth token |
| `VERCEL_AI_GATEWAY_KEY` | Single key routes to 50+ AI providers |
| `GITHUB_TOKEN` | For GitHub automation |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / etc. | Direct provider access (optional) |
| `GOOGLE_OAUTH_CLIENT_ID` / `SECRET` | OAuth flow |
| `EMAIL_SMTP_HOST` / `EMAIL_SMTP_PASSWORD` | Email integration |
| `WHATSAPP_BUSINESS_TOKEN` / `TELEGRAM_BOT_TOKEN` / `DISCORD_BOT_TOKEN` | Messaging integrations |
| `AUTOMATION_MOCK_MODE` | `true` (default) = safe simulation; `false` = real automation |
| `AUTOMATION_IPC_TOKEN` | Optional bearer token for API auth |
| `LOG_LEVEL` | `INFO` / `DEBUG` / `WARNING` |

## Key features

### Tools (25 registered)
- **Mouse**: click, move, scroll
- **Keyboard**: type, hotkey
- **Screen**: capture, OCR
- **Files**: read, write, move, rename, list (with path-traversal protection)
- **Apps**: launch (with allowlist), window list, process list
- **Browser**: open, navigate, click, type, extract (Playwright)
- **Notifications**: email, WhatsApp, Telegram, Discord
- **Plugin tools**: extensible via plugin system

### AI providers (52 total)
- **OpenAI-compatible** (28): OpenAI, DeepSeek, Mistral, xAI Grok, Groq, Together, Fireworks, Cerebras, SambaNova, Perplexity, OpenRouter, Hugging Face, NVIDIA NIM, Novita, SiliconFlow, Hyperbolic, Lepton, FriendliAI, Baseten, Modal, Anyscale, Aleph Alpha, Writer, Upstage, Baichuan, Zhipu (GLM), Qwen, Together Computer
- **Bespoke SDK** (17): Anthropic Claude, Google Gemini, Cohere, AI21, Jina, Voyage, Stability, Replicate, Cloudflare Workers AI, AWS Bedrock, Google Vertex AI, Azure AI Foundry, IBM watsonx, Databricks, AI2, Meta Llama, SambaNova Cloud
- **Local** (2): Ollama, LM Studio
- **Aggregator** (1): Vercel AI Gateway (one API key → all 50+ providers)
- **Custom** (1): OpenAI-compatible custom endpoint

### Workflow engine
- JSON workflow format with versioning
- 14 built-in variables (`{{today}}`, `{{clipboard}}`, `{{downloads_folder}}`, etc.)
- Conditions: `if` / `else if` / `else` with file_exists, window_exists, text_exists, process_running, network_available, ai_condition
- Loops: for_each_file, for_each_row, for_each_browser_result, while, retry, batch
- Self-healing: DOM → accessibility → text → OCR → image recognition → AI visual → ask user
- Checkpoint + resume + crash recovery
- Task recorder (pynput + watchdog + Playwright)

### Security
- 4 risk levels (LOW / MEDIUM / HIGH / CRITICAL)
- 5 approval options (allow_once, allow_for_workflow, always_allow, deny, cancel)
- Emergency stop (Ctrl+Shift+Esc shortcut)
- Kill switch cancels all runs instantly
- Path-traversal protection (blocklist for /etc, /usr, C:/Windows, etc.)
- Prompt-injection defense (external content treated as untrusted data)
- Secret masking in logs (sk-, vck_, ghp_, eyJ, bot0 patterns)
- Webhook signature verification (WhatsApp HMAC-SHA256, Discord Ed25519)
- Rate limiting (max_actions_per_minute, max_ai_calls_per_task, max_loops, etc.)

### Integrations
- **OAuth**: Google, GitHub, Facebook (with CSRF state cache)
- **Email**: SMTP (send) + IMAP (receive) via stdlib
- **WhatsApp**: Cloud API v18.0 (send + webhook receive + verify)
- **Telegram**: Bot API (send + setWebhook + inbound webhook)
- **Discord**: Bot API v10 (send + interactions endpoint with slash commands)

### Scheduler
- 8 trigger types: schedule (cron/hourly/daily/weekly/monthly/once), file, hotkey, webhook, system (startup/login/idle/network)
- Timezone-aware, misfire grace (60s), coalesce (don't replay missed runs)
- Concurrency limits (1 per workflow by default)
- Persists to `scheduled_jobs` table

## Master prompt compliance

This implements the [Master Developer Prompt — AI PC/Laptop Automation Agent](docs/) specification:
- §4 Electron + TypeScript (contextIsolation, preload, CSP, sandbox)
- §5 Python automation service (FastAPI, binds to localhost only)
- §6 AI provider abstraction (52 providers + Vercel Gateway)
- §7 5 agent types (Planner, Executor, Observer, Verification, Recovery)
- §8 Tool registry with full ToolSpec (name, description, input_schema, permission_level, risk_level, timeout, rollback_strategy, verification_strategy)
- §9 4 risk levels (LOW/MEDIUM/HIGH/CRITICAL)
- §10 5 approval options
- §11 Kill switch + Ctrl+Shift+Esc shortcut
- §20 Workflow node types
- §21 Workflow JSON schema with versioning
- §22 Task recorder
- §24 Scheduler
- §25 8 trigger types
- §27 SQLite + SQLAlchemy
- §28 Database security (secrets in OS keyring or env, never plain text)
- §40 Self-healing workflows
- §41 Variables
- §42 Conditions
- §43 Loops with max_iterations
- §44 Parallel execution with locks
- §53 Plugin system
- §54 Integrations
- §55 Security architecture
- §56 Prompt injection defense
- §57 Secret protection
- §63 Testing
- §64 Mock mode
- §66 AI planning safety
- §70 Command palette
- §76 Event bus
- §79 MVP search/screenshot test
- §95 Database rules (migrations, indexes)

## Documentation

- [Architecture](docs/architecture.md)
- [Security](docs/security.md)
- [Database](docs/database.md)
- [Automation Engine](docs/automation-engine.md)
- [AI Agent](docs/ai-agent.md)
- [Workflows](docs/workflows.md)
- [Testing](docs/testing.md)

## License

Internal use only — © Z User 2026.
