# ============================================================================
# Makefile — convenience targets for the AI PC/Laptop Automation Agent
# ----------------------------------------------------------------------------
# Run `make help` to see all targets. Targets are grouped by category:
#   Dev:      install, dev, build, clean
#   Quality:  test, test-integration, lint, format
#   Docker:   docker-build, docker-up, docker-down, docker-logs
#   Database: db-init, db-migrate
#   Ops:      backup, health
# ============================================================================

# ---------------------------------------------------------------------------
# Variables — all paths are absolute so `make -C /home/z/my-project` works
# from anywhere.
# ---------------------------------------------------------------------------
PROJECT_ROOT := /home/z/my-project
PY_ROOT      := /home/z
DESKTOP_DIR  := $(PROJECT_ROOT)/apps/desktop
SCRIPTS_DIR  := $(PROJECT_ROOT)/scripts

# uv invocation — always operate from the Python project root so it picks up
# /home/z/pyproject.toml + /home/z/uv.lock.
UV           := cd $(PY_ROOT) && uv run
UV_SYNC      := cd $(PY_ROOT) && uv sync

# Docker compose — run from the repo root so the relative paths in
# docker-compose.yml resolve correctly.
COMPOSE      := docker compose
COMPOSE_FILE := --file $(PROJECT_ROOT)/docker-compose.yml

# Default goal — `make` with no args prints help.
.DEFAULT_GOAL := help

# ---------------------------------------------------------------------------
# Help — auto-generated from the ## comments above each target.
# ---------------------------------------------------------------------------
.PHONY: help
help:  ## Show this help message
	@echo "AI PC/Laptop Automation Agent — Makefile targets"
	@echo ""
	@echo "Usage: make <target>"
	@echo ""
	@awk 'BEGIN {FS = ":.*##"; printf "Dev:\n"} \
	      /^[a-zA-Z_-]+:.*?##/ { printf "  %-20s %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

# ---------------------------------------------------------------------------
# Dev setup
# ---------------------------------------------------------------------------
.PHONY: install
install: sync-uvlock  ## Install Python deps (uv sync) + frontend deps (npm ci)
	@echo "[install] syncing Python venv at $(PY_ROOT)..."
	$(UV_SYNC)
	@echo "[install] installing frontend deps at $(DESKTOP_DIR)..."
	cd $(DESKTOP_DIR) && npm ci

# Internal: copy /home/z/uv.lock → ./uv.lock so the Docker build context has
# a lockfile. Both pyproject.toml files are identical (verified at
# /home/z/pyproject.toml vs /home/z/my-project/pyproject.toml), so the lock
# is valid against the repo-root pyproject.toml.
.PHONY: sync-uvlock
sync-uvlock:
	@if [ ! -f $(PROJECT_ROOT)/uv.lock ]; then \
		echo "[sync-uvlock] copying $(PY_ROOT)/uv.lock -> $(PROJECT_ROOT)/uv.lock"; \
		cp $(PY_ROOT)/uv.lock $(PROJECT_ROOT)/uv.lock; \
	elif ! cmp -s $(PY_ROOT)/uv.lock $(PROJECT_ROOT)/uv.lock; then \
		echo "[sync-uvlock] updating $(PROJECT_ROOT)/uv.lock from $(PY_ROOT)/uv.lock"; \
		cp $(PY_ROOT)/uv.lock $(PROJECT_ROOT)/uv.lock; \
	fi

.PHONY: dev
dev:  ## Start backend (uvicorn) + frontend (vite) in parallel
	@echo "[dev] starting backend on http://127.0.0.1:8765 ..."
	@echo "[dev] starting frontend on http://localhost:5173 ..."
	@bash -c '\
		$(UV) uvicorn automation_service.main:app --reload --host 127.0.0.1 --port 8765 \
			--app-dir $(PROJECT_ROOT)/apps/automation-service & \
		backend_pid=$$!; \
		cd $(DESKTOP_DIR) && npm run dev & \
		frontend_pid=$$!; \
		trap "kill $$backend_pid $$frontend_pid 2>/dev/null" EXIT INT TERM; \
		wait'

.PHONY: build
build:  ## Build the frontend renderer + package the Electron app
	@echo "[build] building renderer + Electron..."
	cd $(DESKTOP_DIR) && npm run build:all && npm run pack

.PHONY: clean
clean:  ## Remove __pycache__, .pytest_cache, node_modules, dist, build, release
	@echo "[clean] removing Python caches..."
	find $(PROJECT_ROOT) -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
	find $(PY_ROOT) -maxdepth 2 -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
	rm -rf $(PROJECT_ROOT)/.pytest_cache
	rm -rf $(PROJECT_ROOT)/apps/automation-service/.pytest_cache
	rm -rf $(PROJECT_ROOT)/.coverage
	rm -rf $(PROJECT_ROOT)/htmlcov
	@echo "[clean] removing Electron build artifacts..."
	rm -rf $(DESKTOP_DIR)/renderer/dist
	rm -rf $(DESKTOP_DIR)/dist-electron
	rm -rf $(DESKTOP_DIR)/release
	@echo "[clean] done"

# ---------------------------------------------------------------------------
# Quality — tests + lint + format
# ---------------------------------------------------------------------------
.PHONY: test
test:  ## Run pytest (full suite, mock mode)
	cd $(PY_ROOT) && uv run pytest $(PROJECT_ROOT)/apps/automation-service/tests/ $(PROJECT_ROOT)/tests/ -q

.PHONY: test-integration
test-integration:  ## Run pytest integration tests (requires real credentials)
	cd $(PY_ROOT) && uv run pytest -m integration --run-integration -v

.PHONY: test-docker
test-docker:  ## Run the Docker config tests only (fast verification)
	cd $(PY_ROOT) && uv run pytest $(PROJECT_ROOT)/tests/test_docker_config.py -v

.PHONY: lint
lint:  ## Run ruff check (Python) + tsc --noEmit (frontend)
	cd $(PY_ROOT) && uv run ruff check $(PROJECT_ROOT)/apps/automation-service/ $(PROJECT_ROOT)/database/ $(PROJECT_ROOT)/tests/
	cd $(DESKTOP_DIR) && npx tsc --noEmit

.PHONY: format
format:  ## Run ruff format (Python) + prettier --write (frontend)
	cd $(PY_ROOT) && uv run ruff format $(PROJECT_ROOT)/apps/automation-service/ $(PROJECT_ROOT)/database/ $(PROJECT_ROOT)/tests/
	cd $(DESKTOP_DIR) && npx prettier --write "renderer/src/**/*.{ts,tsx,css}"

# ---------------------------------------------------------------------------
# Docker — build / up / down / logs
# ---------------------------------------------------------------------------
.PHONY: docker-build
docker-build: sync-uvlock  ## Build the backend + frontend + nginx images
	@echo "[docker-build] building images via docker compose..."
	cd $(PROJECT_ROOT) && $(COMPOSE) build

.PHONY: docker-up
docker-up:  ## Start all services (detached)
	@echo "[docker-up] starting services..."
	cd $(PROJECT_ROOT) && $(COMPOSE) up -d
	@echo "[docker-up] frontend: http://localhost:8080  backend: http://localhost:8765  nginx: http://localhost:80"

.PHONY: docker-down
docker-down:  ## Stop + remove all services (keeps volumes)
	@echo "[docker-down] stopping services..."
	cd $(PROJECT_ROOT) && $(COMPOSE) down

.PHONY: docker-logs
docker-logs:  ## Tail logs from all services (Ctrl-C to detach)
	cd $(PROJECT_ROOT) && $(COMPOSE) logs -f

.PHONY: docker-rebuild
docker-rebuild: docker-down docker-build docker-up  ## Down + rebuild + up

# ---------------------------------------------------------------------------
# Database — init + migrate
# ---------------------------------------------------------------------------
.PHONY: db-init
db-init:  ## Initialize the database (creates 22 tables on Turso)
	cd $(PY_ROOT) && uv run python $(SCRIPTS_DIR)/init_db.py

.PHONY: db-migrate
db-migrate:  ## Run Alembic migrations (upgrade head)
	cd $(PROJECT_ROOT) && cd $(PY_ROOT) && uv run alembic -c $(PROJECT_ROOT)/alembic.ini upgrade head

# ---------------------------------------------------------------------------
# Ops — health check + backup
# ---------------------------------------------------------------------------
.PHONY: health
health:  ## Probe the backend /health endpoint
	python $(SCRIPTS_DIR)/healthcheck.py

.PHONY: backup
backup:  ## Trigger a backup via the system/backup endpoint
	curl -X POST http://localhost:8765/system/backup
