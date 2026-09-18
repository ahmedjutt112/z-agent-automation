"""Tests that the Docker deployment configuration is wired up correctly.

These tests verify that the right files exist, parse as the format they claim
to be (YAML / Python), and contain the key directives / services / targets we
expect. They do NOT invoke `docker build` (which requires the Docker daemon
and a network connection); they are pure static-analysis checks.

The tests live under tests/ (rather than apps/automation-service/tests/)
because they cover cross-cutting repo config — not the automation service.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path("/home/z/my-project")
SCRIPTS_DIR = REPO_ROOT / "scripts"
DESKTOP = REPO_ROOT / "apps" / "desktop"


# ---------------------------------------------------------------------------
# Backend Dockerfile
# ---------------------------------------------------------------------------


def _read_dockerfile() -> str:
    path = REPO_ROOT / "Dockerfile"
    assert path.exists(), f"{path} does not exist"
    return path.read_text(encoding="utf-8")


def test_dockerfile_exists() -> None:
    assert (REPO_ROOT / "Dockerfile").exists(), "Dockerfile missing at repo root"


def test_dockerfile_multistage() -> None:
    """Dockerfile must use python:3.12-slim AND have >=2 FROM lines."""
    text = _read_dockerfile()
    assert "FROM python:3.12-slim" in text, (
        "Dockerfile must use python:3.12-slim (NOT full python:3.12)"
    )
    from_lines = [line for line in text.splitlines() if line.startswith("FROM ")]
    assert len(from_lines) >= 2, (
        f"Dockerfile must be multi-stage (>=2 FROM lines); found {len(from_lines)}"
    )


def test_dockerfile_non_root() -> None:
    """Dockerfile must drop privileges via a USER directive (non-root)."""
    text = _read_dockerfile()
    user_lines = [
        line for line in text.splitlines()
        if line.startswith("USER ")
    ]
    assert len(user_lines) >= 1, "Dockerfile must contain a USER directive (non-root)"
    # The USER line must NOT be `USER root` (which would be a no-op escape hatch).
    for line in user_lines:
        user_value = line.split("USER ", 1)[1].strip()
        assert user_value.lower() != "root", (
            "Dockerfile USER directive must not be 'root'"
        )


def test_dockerfile_exposes_port() -> None:
    """Dockerfile must EXPOSE 8765 (the FastAPI port)."""
    text = _read_dockerfile()
    assert "EXPOSE 8765" in text, "Dockerfile must contain 'EXPOSE 8765'"


def test_dockerfile_binds_to_all_interfaces() -> None:
    """Dockerfile must run uvicorn bound to 0.0.0.0 (NOT 127.0.0.1).

    Inside a container, 127.0.0.1 is unreachable from sibling containers on
    the bridge network — the compose frontend + nginx cannot proxy to a
    loopback-bound backend. The CMD must override ServiceSettings.host with
    --host 0.0.0.0.
    """
    text = _read_dockerfile()
    # The CMD line should contain --host 0.0.0.0
    cmd_lines = [
        line for line in text.splitlines()
        if "uvicorn" in line and "--host" in line
    ]
    assert cmd_lines, "Dockerfile must invoke uvicorn with --host"
    assert any("0.0.0.0" in line for line in cmd_lines), (
        "Dockerfile uvicorn CMD must use --host 0.0.0.0 (not 127.0.0.1)"
    )


def test_dockerfile_uses_uv_sync_frozen() -> None:
    """Builder stage must run `uv sync --frozen --no-dev` for reproducibility."""
    text = _read_dockerfile()
    assert "uv sync" in text, "Dockerfile must use uv sync to install deps"
    assert "--frozen" in text, (
        "uv sync must use --frozen so the lockfile is honored verbatim"
    )
    assert "--no-dev" in text, (
        "uv sync must use --no-dev so dev/test deps are excluded from runtime"
    )


def test_dockerfile_installs_playwright_deps() -> None:
    """Runtime image must include Playwright's Chromium system deps."""
    text = _read_dockerfile()
    # Spot-check a handful of the libs from the task spec.
    for lib in (
        "libnss3",
        "libatk-bridge2.0-0",
        "libdrm2",
        "libxkbcommon0",
        "libxcomposite1",
        "libxdamage1",
        "libxfixes3",
        "libxrandr2",
        "libgbm1",
        "libxss1",
        "libasound2",
        "libpango-1.0-0",
        "libcairo2",
    ):
        assert lib in text, (
            f"Dockerfile must install Playwright system dep: {lib}"
        )


def test_dockerfile_has_healthcheck() -> None:
    """Dockerfile should declare a HEALTHCHECK so the image is self-describing."""
    text = _read_dockerfile()
    assert "HEALTHCHECK" in text, (
        "Dockerfile must declare a HEALTHCHECK directive"
    )
    # The healthcheck must poll the /health endpoint.
    assert "/health" in text, "Dockerfile HEALTHCHECK must hit /health"


# ---------------------------------------------------------------------------
# Frontend Dockerfile
# ---------------------------------------------------------------------------


def _read_frontend_dockerfile() -> str:
    path = DESKTOP / "Dockerfile"
    assert path.exists(), f"{path} does not exist"
    return path.read_text(encoding="utf-8")


def test_frontend_dockerfile_exists() -> None:
    assert (DESKTOP / "Dockerfile").exists(), "apps/desktop/Dockerfile missing"


def test_frontend_dockerfile_multistage() -> None:
    """Frontend Dockerfile must use node:20-alpine + nginx:alpine."""
    text = _read_frontend_dockerfile()
    assert "FROM node:20-alpine" in text, (
        "Frontend Dockerfile must use node:20-alpine as the builder image"
    )
    assert "FROM nginx:alpine" in text, (
        "Frontend Dockerfile must use nginx:alpine as the runtime image"
    )


def test_frontend_dockerfile_runs_npm_ci() -> None:
    text = _read_frontend_dockerfile()
    assert "npm ci" in text, "Frontend Dockerfile must run `npm ci` (not npm install)"


def test_frontend_dockerfile_builds_renderer() -> None:
    text = _read_frontend_dockerfile()
    assert "npm run build" in text, (
        "Frontend Dockerfile must run `npm run build` to produce the Vite bundle"
    )


def test_frontend_dockerfile_copies_to_nginx() -> None:
    text = _read_frontend_dockerfile()
    assert "/usr/share/nginx/html" in text, (
        "Frontend Dockerfile must copy the renderer bundle to nginx's doc root"
    )


def test_frontend_dockerfile_exposes_80() -> None:
    text = _read_frontend_dockerfile()
    assert "EXPOSE 80" in text, "Frontend Dockerfile must EXPOSE 80"


# ---------------------------------------------------------------------------
# .dockerignore
# ---------------------------------------------------------------------------


def _read_dockerignore() -> str:
    path = REPO_ROOT / ".dockerignore"
    assert path.exists(), f"{path} does not exist"
    return path.read_text(encoding="utf-8")


def test_dockerignore_exists() -> None:
    assert (REPO_ROOT / ".dockerignore").exists(), ".dockerignore missing"


def test_dockerignore_excludes_secrets() -> None:
    """CRITICAL — .dockerignore MUST exclude .env so secrets don't leak into images."""
    text = _read_dockerignore()
    lines = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]
    # .env can appear as ".env" or ".env/" — both match the secret file.
    assert ".env" in lines or any(l.startswith(".env") for l in lines), (
        ".dockerignore MUST exclude .env (secrets)"
    )


def test_dockerignore_excludes_venv() -> None:
    text = _read_dockerignore()
    assert ".venv/" in text, ".dockerignore must exclude .venv/"


def test_dockerignore_excludes_skills() -> None:
    text = _read_dockerignore()
    assert "skills/" in text, ".dockerignore must exclude skills/ (50 MB catalog)"


def test_dockerignore_excludes_node_modules() -> None:
    text = _read_dockerignore()
    assert "node_modules/" in text, ".dockerignore must exclude node_modules/"


def test_dockerignore_excludes_pycache() -> None:
    text = _read_dockerignore()
    assert "__pycache__/" in text, ".dockerignore must exclude __pycache__/"


def test_dockerignore_excludes_git() -> None:
    text = _read_dockerignore()
    assert ".git/" in text, ".dockerignore must exclude .git/"


def test_dockerignore_excludes_db_files() -> None:
    text = _read_dockerignore()
    assert "db/*.db" in text, ".dockerignore must exclude db/*.db (local SQLite)"


# ---------------------------------------------------------------------------
# docker-compose.yml
# ---------------------------------------------------------------------------


def _load_compose() -> dict:
    path = REPO_ROOT / "docker-compose.yml"
    assert path.exists(), f"{path} does not exist"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_docker_compose_exists() -> None:
    path = REPO_ROOT / "docker-compose.yml"
    assert path.exists(), "docker-compose.yml missing at repo root"


def test_docker_compose_parses_as_yaml() -> None:
    data = _load_compose()
    assert isinstance(data, dict), "docker-compose.yml must parse as a YAML dict"
    assert "services" in data, "docker-compose.yml must define a 'services' key"


def test_docker_compose_has_backend_service() -> None:
    data = _load_compose()
    services = data.get("services", {})
    assert "backend" in services, "docker-compose.yml must define a 'backend' service"


def test_docker_compose_has_frontend_service() -> None:
    data = _load_compose()
    services = data.get("services", {})
    assert "frontend" in services, "docker-compose.yml must define a 'frontend' service"


def test_docker_compose_has_nginx_service() -> None:
    data = _load_compose()
    services = data.get("services", {})
    assert "nginx" in services, (
        "docker-compose.yml must define an 'nginx' reverse-proxy service"
    )


def test_docker_compose_backend_healthcheck() -> None:
    """Backend service must have a healthcheck so depends_on healthy works."""
    data = _load_compose()
    backend = data["services"]["backend"]
    assert "healthcheck" in backend, (
        "backend service must declare a healthcheck (so frontend + nginx can"
        " wait for it via depends_on: condition: service_healthy)"
    )
    hc = backend["healthcheck"]
    # The test spec calls for `curl http://localhost:8765/health`. The test list
    # format uses [CMD, curl, --fail, ...] OR a string form. Either is fine.
    test_field = hc.get("test", [])
    if isinstance(test_field, list):
        joined = " ".join(test_field)
    else:
        joined = str(test_field)
    assert "curl" in joined, "healthcheck must use curl"
    assert "/health" in joined, "healthcheck must hit /health endpoint"
    assert "8765" in joined, "healthcheck must target port 8765"


def test_docker_compose_backend_publishes_8765() -> None:
    data = _load_compose()
    backend = data["services"]["backend"]
    ports = backend.get("ports", [])
    assert any("8765" in str(p) for p in ports), (
        "backend service must publish port 8765 (host:container)"
    )


def test_docker_compose_frontend_publishes_8080() -> None:
    data = _load_compose()
    frontend = data["services"]["frontend"]
    ports = frontend.get("ports", [])
    assert any("8080" in str(p) for p in ports), (
        "frontend service must publish port 8080 on the host"
    )


def test_docker_compose_frontend_depends_on_backend() -> None:
    data = _load_compose()
    frontend = data["services"]["frontend"]
    deps = frontend.get("depends_on", {})
    assert "backend" in deps, (
        "frontend service must depend_on backend (so backend boots first)"
    )


def test_docker_compose_backend_env_file() -> None:
    """Backend must load .env via env_file so secrets stay out of the image."""
    data = _load_compose()
    backend = data["services"]["backend"]
    env_file = backend.get("env_file")
    assert env_file is not None, (
        "backend service must use env_file to load .env (secrets at runtime, "
        "NOT baked into the image)"
    )
    # env_file can be a string or a list of strings. Either way, it must
    # reference ".env".
    if isinstance(env_file, list):
        assert any(".env" in str(e) for e in env_file), (
            "backend env_file must reference .env"
        )
    else:
        assert ".env" in str(env_file), "backend env_file must reference .env"


def test_docker_compose_backend_has_volumes() -> None:
    """Backend must mount volumes for logs/workflows/download/backups so state survives restarts."""
    data = _load_compose()
    backend = data["services"]["backend"]
    volumes = backend.get("volumes", [])
    joined = " ".join(volumes)
    for required_mount in ("./logs", "./workflows", "./download", "./backups"):
        assert required_mount in joined, (
            f"backend service must mount {required_mount} as a volume"
        )


def test_docker_compose_no_database_service() -> None:
    """Turso libSQL is cloud-hosted — there must NOT be a db/postgres/mysql service."""
    data = _load_compose()
    services = data.get("services", {})
    for forbidden in ("postgres", "mysql", "mariadb", "redis", "mongodb"):
        assert forbidden not in services, (
            f"docker-compose.yml must NOT define a '{forbidden}' service "
            "(database is cloud-hosted via Turso libSQL)"
        )


def test_docker_compose_restart_policy() -> None:
    data = _load_compose()
    for svc_name in ("backend", "frontend", "nginx"):
        svc = data["services"].get(svc_name, {})
        assert svc.get("restart") == "unless-stopped", (
            f"{svc_name} service must have restart: unless-stopped"
        )


# ---------------------------------------------------------------------------
# nginx.conf
# ---------------------------------------------------------------------------


def _read_nginx_conf() -> str:
    path = REPO_ROOT / "nginx.conf"
    assert path.exists(), f"{path} does not exist"
    return path.read_text(encoding="utf-8")


def test_nginx_conf_exists() -> None:
    assert (REPO_ROOT / "nginx.conf").exists(), "nginx.conf missing at repo root"


def test_nginx_conf_proxies_backend() -> None:
    """nginx.conf must proxy_pass to backend:8765 (the compose hostname)."""
    text = _read_nginx_conf()
    assert "backend:8765" in text, (
        "nginx.conf must proxy_pass to backend:8765 (compose service hostname)"
    )
    assert "proxy_pass" in text, "nginx.conf must declare proxy_pass directives"


def test_nginx_conf_websocket_upgrade() -> None:
    """nginx.conf must set Upgrade + Connection headers for WebSocket endpoints."""
    text = _read_nginx_conf()
    assert "Upgrade" in text, (
        "nginx.conf must set 'Upgrade $http_upgrade' for WebSocket support"
    )
    assert "Connection" in text, (
        "nginx.conf must set 'Connection $connection_upgrade' for WebSocket support"
    )
    # The connection_upgrade map (http → ws upgrade) must be declared.
    assert "$connection_upgrade" in text, (
        "nginx.conf must declare the $connection_upgrade map for WS upgrade"
    )


def test_nginx_conf_proxies_events_websocket() -> None:
    text = _read_nginx_conf()
    assert "/events" in text, "nginx.conf must proxy /events (event bus WebSocket)"


def test_nginx_conf_proxies_logs_stream_websocket() -> None:
    text = _read_nginx_conf()
    assert "/logs/stream" in text, (
        "nginx.conf must proxy /logs/stream (log streaming WebSocket)"
    )


def test_nginx_conf_proxies_voice_stream_websocket() -> None:
    text = _read_nginx_conf()
    assert "/voice/stream" in text, (
        "nginx.conf must proxy /voice/stream (voice pipeline WebSocket)"
    )


def test_nginx_conf_proxies_docs() -> None:
    text = _read_nginx_conf()
    assert "/docs" in text, "nginx.conf must proxy /docs (OpenAPI Swagger UI)"


def test_nginx_conf_proxies_oauth_callback() -> None:
    text = _read_nginx_conf()
    assert "/oauth/" in text, (
        "nginx.conf must proxy /oauth/* (OAuth callbacks — no prefix strip)"
    )


def test_nginx_conf_gzip_enabled() -> None:
    text = _read_nginx_conf()
    assert "gzip on" in text, "nginx.conf must enable gzip"
    assert "application/json" in text, "nginx.conf must gzip JSON responses"
    assert "application/javascript" in text or "text/css" in text, (
        "nginx.conf must gzip JS/CSS responses"
    )


def test_nginx_conf_security_headers() -> None:
    text = _read_nginx_conf()
    assert "X-Frame-Options" in text, "nginx.conf must set X-Frame-Options"
    assert "DENY" in text, "X-Frame-Options must be DENY"
    assert "X-Content-Type-Options" in text, (
        "nginx.conf must set X-Content-Type-Options"
    )
    assert "nosniff" in text, "X-Content-Type-Options must be nosniff"
    assert "Referrer-Policy" in text, "nginx.conf must set Referrer-Policy"
    assert "Strict-Transport-Security" in text, (
        "nginx.conf must set Strict-Transport-Security (HSTS) on HTTPS vhost"
    )


def test_nginx_conf_client_max_body_size() -> None:
    text = _read_nginx_conf()
    assert "client_max_body_size" in text, (
        "nginx.conf must set client_max_body_size (for file + workflow uploads)"
    )
    assert "50M" in text, "client_max_body_size must be at least 50M"


def test_nginx_conf_websocket_timeout_1h() -> None:
    text = _read_nginx_conf()
    # The spec calls for 1h idle timeout on WebSocket endpoints.
    assert "3600s" in text, (
        "nginx.conf must set 1h (3600s) WebSocket idle timeout"
    )


# ---------------------------------------------------------------------------
# Makefile
# ---------------------------------------------------------------------------


def _read_makefile() -> str:
    path = REPO_ROOT / "Makefile"
    assert path.exists(), f"{path} does not exist"
    return path.read_text(encoding="utf-8")


def test_makefile_exists() -> None:
    assert (REPO_ROOT / "Makefile").exists(), "Makefile missing at repo root"


def test_makefile_has_targets() -> None:
    text = _read_makefile()
    # Each target must appear as a line starting with "<name>:".
    for required in ("install", "test", "docker-up", "docker-down"):
        assert f"\n{required}:" in text or text.startswith(f"{required}:"), (
            f"Makefile must define a '{required}' target"
        )


def test_makefile_has_docker_build_target() -> None:
    text = _read_makefile()
    assert "docker-build" in text, "Makefile must define a 'docker-build' target"


def test_makefile_has_docker_logs_target() -> None:
    text = _read_makefile()
    assert "docker-logs" in text, "Makefile must define a 'docker-logs' target"


def test_makefile_has_lint_target() -> None:
    text = _read_makefile()
    assert "lint" in text, "Makefile must define a 'lint' target"
    assert "ruff check" in text, "lint target must run ruff check"
    assert "tsc --noEmit" in text, "lint target must run tsc --noEmit"


def test_makefile_has_format_target() -> None:
    text = _read_makefile()
    assert "format" in text, "Makefile must define a 'format' target"
    assert "ruff format" in text, "format target must run ruff format"


def test_makefile_has_dev_target() -> None:
    text = _read_makefile()
    assert "dev" in text, "Makefile must define a 'dev' target"


def test_makefile_has_db_targets() -> None:
    text = _read_makefile()
    assert "db-init" in text, "Makefile must define a 'db-init' target"
    assert "db-migrate" in text, "Makefile must define a 'db-migrate' target"


def test_makefile_has_backup_target() -> None:
    text = _read_makefile()
    assert "backup" in text, "Makefile must define a 'backup' target"
    assert "system/backup" in text, (
        "backup target must POST to /system/backup endpoint"
    )


def test_makefile_has_clean_target() -> None:
    text = _read_makefile()
    assert "clean" in text, "Makefile must define a 'clean' target"


def test_makefile_install_runs_uv_sync_and_npm_ci() -> None:
    text = _read_makefile()
    assert "uv sync" in text or "uv_sync" in text.lower(), (
        "install target must run uv sync"
    )
    assert "npm ci" in text, "install target must run npm ci"


def test_makefile_test_runs_pytest() -> None:
    text = _read_makefile()
    assert "pytest" in text, "test target must run pytest"


# ---------------------------------------------------------------------------
# Healthcheck script
# ---------------------------------------------------------------------------


def test_healthcheck_script_exists() -> None:
    path = SCRIPTS_DIR / "healthcheck.py"
    assert path.exists(), f"{path} does not exist"


def test_healthcheck_script_uses_health_endpoint() -> None:
    path = SCRIPTS_DIR / "healthcheck.py"
    text = path.read_text(encoding="utf-8")
    assert "/health" in text, "healthcheck.py must hit the /health endpoint"
    # Must exit 0 on healthy, 1 otherwise.
    assert "return 0" in text, "healthcheck.py must exit 0 when healthy"
    assert "return 1" in text, "healthcheck.py must exit 1 when unhealthy"


def test_healthcheck_script_has_timeout() -> None:
    path = SCRIPTS_DIR / "healthcheck.py"
    text = path.read_text(encoding="utf-8")
    # Must have a 5-second timeout so a wedged service gets marked unhealthy
    # rather than hanging Docker's HEALTHCHECK polling loop.
    assert "5" in text and ("timeout" in text.lower() or "TIMEOUT" in text), (
        "healthcheck.py must enforce a 5-second timeout"
    )


def test_healthcheck_script_uses_stdlib_only() -> None:
    """healthcheck.py must use only stdlib so it works in slim images without pip install."""
    path = SCRIPTS_DIR / "healthcheck.py"
    text = path.read_text(encoding="utf-8")
    # Forbidden heavy deps (each requires its own install in a minimal image).
    for forbidden in ("requests", "httpx", "aiohttp"):
        assert f"import {forbidden}" not in text, (
            f"healthcheck.py must not import {forbidden} — use urllib.request only"
        )
    assert "urllib.request" in text, (
        "healthcheck.py must use stdlib urllib.request for HTTP"
    )


# ---------------------------------------------------------------------------
# README deployment section
# ---------------------------------------------------------------------------


def test_readme_has_deployment_section() -> None:
    path = REPO_ROOT / "README.md"
    assert path.exists(), "README.md missing"
    text = path.read_text(encoding="utf-8")
    assert "## Deployment" in text, (
        "README.md must have a '## Deployment' section"
    )
    # Must mention Docker compose as the recommended flow.
    assert "docker compose up -d" in text or "make docker-up" in text, (
        "Deployment section must mention docker compose up -d or make docker-up"
    )
    # Must reference port 8080 (the frontend's host port).
    assert "8080" in text, "Deployment section must mention port 8080"
    # Must reference the master prompt §93 one-command startup goal.
    assert "§93" in text, (
        "Deployment section must reference master prompt §93 (one-command startup)"
    )
