# syntax=docker/dockerfile:1.7
# ============================================================================
# Backend Dockerfile — AI PC/Laptop Automation Service (FastAPI on 8765)
# ----------------------------------------------------------------------------
# Build context: /home/z/my-project/  (the repo root)
# Multi-stage build:
#   Stage 1 (builder): python:3.12-slim + uv sync --frozen --no-dev
#   Stage 2 (runtime): python:3.12-slim, non-root user (UID 1000), Playwright
#                      system deps, runs uvicorn bound to 0.0.0.0:8765 so other
#                      containers in the compose network can reach it.
#
# IMPORTANT — master prompt §5 says "bind to 127.0.0.1 ONLY" for local dev, but
# inside a container 127.0.0.1 is unreachable from sibling services. The
# uvicorn CMD below overrides ServiceSettings.host with --host 0.0.0.0 so the
# compose frontend + nginx can proxy to it. The host port is not published by
# default in docker-compose.yml — nginx is the only public ingress.
#
# NOTE on uv.lock: the project's lockfile lives at /home/z/uv.lock (next to
# /home/z/pyproject.toml), NOT inside the repo root. The Makefile `docker-build`
# target syncs /home/z/uv.lock → ./uv.lock before invoking docker compose build
# so the COPY below succeeds. If you call `docker build` directly, run
# `cp ../uv.lock ./uv.lock` first.
# ============================================================================


# ---------------------------------------------------------------------------
# Stage 1 — builder: install Python deps via uv into a clean venv
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

# Build-time only: curl is needed by the uv installer; we leave it in the
# builder stage so the runtime image stays minimal.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install uv (pinned) — same installer the project uses locally.
# uv ships as a single static binary, so no further system deps are needed.
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

# The project's pyproject.toml + uv.lock live at the repo root
# (/home/z/my-project/). We copy them in first to maximise the Docker layer
# cache hit on rebuilds — any change to apps/* or database/* will NOT bust
# the uv sync layer.
WORKDIR /app
COPY pyproject.toml uv.lock ./

# Sync only production deps into a venv at /app/.venv. --frozen refuses to
# re-lock (so the build fails loudly if pyproject.toml and uv.lock disagree);
# --no-dev drops the dev/test deps so the runtime image stays small.
# --no-cache-dir avoids polluting the layer with uv's wheel cache.
RUN uv sync --frozen --no-dev --no-cache-dir


# ---------------------------------------------------------------------------
# Stage 2 — runtime: slim image with Playwright system deps + non-root user
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# Playwright browser-automation system dependencies (master prompt §16).
# `playwright install-deps` would pull in a much larger set; we install only
# the libs actually dlopen'd by Chromium on Debian slim so the runtime image
# stays under ~400 MB.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        # Playwright / Chromium runtime libs
        libnss3 \
        libnspr4 \
        libatk1.0-0 \
        libatk-bridge2.0-0 \
        libcups2 \
        libdrm2 \
        libxkbcommon0 \
        libxcomposite1 \
        libxdamage1 \
        libxfixes3 \
        libxrandr2 \
        libgbm1 \
        libxss1 \
        libasound2 \
        libpango-1.0-0 \
        libcairo2 \
        # Headless-rendering helpers
        fonts-liberation \
        fonts-dejavu-core \
        # curl is needed by the Docker HEALTHCHECK below
        curl \
        ca-certificates \
        tini \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user (UID 1000) so the uvicorn process never runs as root.
# This is the master-prompt §55 security stance: even if the container is
# compromised, the attacker does not get root inside the container.
RUN groupadd --system --gid 1000 appuser \
    && useradd --system --uid 1000 --gid appuser \
        --home-dir /app --shell /usr/sbin/nologin appuser

WORKDIR /app

# Copy the installed venv from the builder stage. uv installs into /app/.venv
# with a self-contained layout, so we can lift the entire directory verbatim.
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv

# Put the venv on PATH so `uvicorn` resolves without an absolute path.
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # Force the automation service to bind to all interfaces inside the
    # container. The compose file does NOT publish 8765 to the host by default
    # (only nginx is published); this just makes the port reachable from
    # sibling containers on the bridge network.
    AUTOMATION_HOST=0.0.0.0 \
    AUTOMATION_PORT=8765 \
    # Project root points at /app so the ServiceSettings paths resolve
    # correctly when the app reads/writes logs, workflows, screenshots.
    PROJECT_ROOT=/app

# Copy the application source. .dockerignore filters out skills/, node_modules/,
# .venv/, __pycache__/, .git/, tool-results/, upload/, db/*.db, logs/, etc.
COPY --chown=appuser:appuser apps/automation-service ./apps/automation-service
COPY --chown=appuser:appuser database ./database
COPY --chown=appuser:appuser plugins ./plugins
COPY --chown=appuser:appuser scripts ./scripts
COPY --chown=appuser:appuser workflows ./workflows
COPY --chown=appuser:appuser config ./config

# Pre-create the runtime write directories (logs/, download/screenshots/,
# db/) and chown them to the non-root user so uvicorn can write to them on
# first boot without an EACCES crash.
RUN mkdir -p /app/logs /app/download/screenshots /app/db /app/backups /app/upload \
    && chown -R appuser:appuser /app

# Drop privileges — every instruction after this runs as appuser (UID 1000).
USER appuser

# Expose the FastAPI port. The compose file maps 8765:8765 only on the
# backend service; nginx proxies :80 → frontend:80 + /api → backend:8765.
EXPOSE 8765

# Healthcheck: poll /health every 30s. The compose file overrides this with
# a tighter interval + start-period, but having a Dockerfile-level default
# means the image is self-describing when run standalone via `docker run`.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl --fail --silent http://localhost:8765/health || exit 1

# tini is the PID-1 init; it reaps zombie processes and forwards signals so
# `docker stop` cleanly shuts down uvicorn (otherwise SIGTERM is ignored and
# Docker falls back to SIGKILL after the 10s grace period).
ENTRYPOINT ["/usr/bin/tini", "--"]

# Run uvicorn bound to 0.0.0.0 (NOT 127.0.0.1) so the compose network can
# reach the service. --workers 1 keeps the in-memory event_bus + scheduler
# single-instance; scale out via replicas requires an external broker.
CMD ["uvicorn", "automation_service.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8765", \
     "--workers", "1", \
     "--no-access-log"]
