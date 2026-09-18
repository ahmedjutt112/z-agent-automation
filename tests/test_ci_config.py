"""Tests that the production-packaging + CI configuration is wired up correctly.

These tests are intentionally lightweight — they verify that the right files
exist, parse as the format they claim to be (JSON / YAML / TOML), and contain
the key sections / scripts / jobs we expect. They do NOT invoke electron-builder
or npm (both require native GUI + a populated node_modules, which the CI host
may not have).

The tests live under tests/ (rather than apps/automation-service/tests/)
because they cover cross-cutting repo config — not the automation service.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import tomllib
import yaml

REPO_ROOT = Path("/home/z/my-project")
PYPROJECT = Path("/home/z/pyproject.toml")
DESKTOP = REPO_ROOT / "apps" / "desktop"


# ---------------------------------------------------------------------------
# pyproject.toml (Python project at /home/z)
# ---------------------------------------------------------------------------


def _load_pyproject() -> dict:
    with PYPROJECT.open("rb") as f:
        return tomllib.load(f)


def test_pyproject_has_ruff_config() -> None:
    data = _load_pyproject()
    assert "tool" in data, "pyproject.toml missing [tool] section entirely"
    assert "ruff" in data["tool"], "pyproject.toml missing [tool.ruff] section"
    ruff = data["tool"]["ruff"]
    assert "line-length" in ruff, "[tool.ruff] missing line-length"
    assert "target-version" in ruff, "[tool.ruff] missing target-version"
    assert ruff["target-version"] == "py312"
    assert "exclude" in ruff, "[tool.ruff] missing exclude list"


def test_pyproject_has_ruff_lint_select() -> None:
    data = _load_pyproject()
    ruff = data["tool"]["ruff"]
    assert "lint" in ruff, "[tool.ruff.lint] section missing"
    lint = ruff["lint"]
    assert "select" in lint and "ignore" in lint
    # Sanity: we want at least the core rule families enabled.
    selected = set(lint["select"])
    for required in ("E", "F", "W", "I", "N", "B", "UP"):
        assert required in selected, f"[tool.ruff.lint] select missing {required!r}"


def test_pyproject_has_ruff_format() -> None:
    data = _load_pyproject()
    ruff = data["tool"]["ruff"]
    assert "format" in ruff, "[tool.ruff.format] section missing"
    fmt = ruff["format"]
    assert fmt.get("quote-style") == "double"
    assert fmt.get("indent-style") == "space"


def test_pyproject_has_black_config() -> None:
    data = _load_pyproject()
    assert "black" in data["tool"], "pyproject.toml missing [tool.black] section"
    black = data["tool"]["black"]
    assert black.get("line-length") == 100
    assert "py312" in black.get("target-version", [])


def test_pyproject_has_pytest_config() -> None:
    """Existing pytest config must still be present (we appended, not replaced)."""
    data = _load_pyproject()
    assert "pytest" in data["tool"], "pyproject.toml missing [tool.pytest.ini_options]"
    pytest_cfg = data["tool"]["pytest"]
    # TOML parses [tool.pytest.ini_options] as tool.pytest.ini_options.
    ini = pytest_cfg.get("ini_options", {})
    assert ini.get("asyncio_mode") == "auto", (
        "asyncio_mode should be 'auto' — did the existing pytest config get clobbered?"
    )
    assert "testpaths" in ini
    paths = ini["testpaths"]
    assert "apps/automation-service/tests" in paths
    assert "tests" in paths


# ---------------------------------------------------------------------------
# ESLint + Prettier
# ---------------------------------------------------------------------------


def test_eslintrc_exists() -> None:
    path = DESKTOP / ".eslintrc.json"
    assert path.exists(), f"{path} does not exist"
    data = json.loads(path.read_text())
    assert data.get("root") is True
    assert data.get("parser") == "@typescript-eslint/parser"
    plugins = data.get("plugins", [])
    for required in ("@typescript-eslint", "react", "react-hooks"):
        assert required in plugins, f".eslintrc.json missing plugin {required!r}"
    extends = data.get("extends", [])
    assert "plugin:@typescript-eslint/recommended" in extends
    assert "plugin:react/recommended" in extends
    assert "plugin:react-hooks/recommended" in extends


def test_prettierrc_exists() -> None:
    path = DESKTOP / ".prettierrc"
    assert path.exists(), f"{path} does not exist"
    data = json.loads(path.read_text())
    assert data.get("semi") is True
    assert data.get("singleQuote") is True
    assert data.get("trailingComma") == "all"
    assert data.get("printWidth") == 100
    assert data.get("tabWidth") == 2


# ---------------------------------------------------------------------------
# TypeScript
# ---------------------------------------------------------------------------


def test_tsconfig_strict() -> None:
    path = DESKTOP / "tsconfig.json"
    assert path.exists(), f"{path} does not exist"
    data = json.loads(path.read_text())
    opts = data.get("compilerOptions", {})
    assert opts.get("strict") is True, "tsconfig.json must have strict: true"
    assert opts.get("target") == "ES2022"
    assert opts.get("noUnusedLocals") is True
    assert opts.get("noUnusedParameters") is True
    assert opts.get("noImplicitReturns") is True
    # Path alias for `@/` must match Vite's alias.
    assert opts.get("paths", {}).get("@/*") == ["renderer/src/*"]


def test_electron_tsconfig_extends_root() -> None:
    path = DESKTOP / "electron" / "tsconfig.json"
    assert path.exists(), f"{path} does not exist"
    data = json.loads(path.read_text())
    assert data.get("extends") == "../tsconfig.json"
    opts = data.get("compilerOptions", {})
    # Electron main process compiles to CommonJS so it can be required
    # directly by Electron's main entry (no bundler at runtime).
    assert opts.get("module") == "CommonJS"
    assert opts.get("outDir") == "../dist-electron"


# ---------------------------------------------------------------------------
# Vite + Electron Builder
# ---------------------------------------------------------------------------


def test_vite_config_exists() -> None:
    path = DESKTOP / "vite.config.ts"
    assert path.exists(), f"{path} does not exist"
    text = path.read_text()
    # The base path MUST be relative so Electron's file:// loader can resolve
    # assets next to index.html instead of at the filesystem root.
    assert "base: './'" in text or 'base: "./"' in text
    # The `@` alias must match the tsconfig paths so dev + typecheck agree.
    assert "'@'" in text or '"@"' in text
    assert "renderer/src" in text
    # strictPort so the Electron dev loop never drifts off 5173.
    assert "strictPort: true" in text or "strictPort:true" in text


def test_electron_builder_exists() -> None:
    path = DESKTOP / "electron-builder.yml"
    assert path.exists(), f"{path} does not exist"
    data = yaml.safe_load(path.read_text())
    assert data["appId"] == "com.z-agent.automation"
    assert data["productName"] == "AI Automation Agent"
    assert "directories" in data
    assert data["directories"]["output"] == "release"
    # Cross-platform targets must cover both x64 and arm64.
    for platform in ("win", "mac", "linux"):
        assert platform in data, f"electron-builder.yml missing {platform!r} target"
        targets = data[platform]["target"]
        # targets is a list of {target: <name>, arch: [...]} dicts.
        archs = []
        for entry in targets:
            archs.extend(entry.get("arch", []))
        assert "x64" in archs, f"{platform} target missing x64 arch"
        assert "arm64" in archs, f"{platform} target missing arm64 arch"
    # extraResources must bundle the automation-service so the packaged app
    # ships with the Python backend.
    extras = data.get("extraResources", [])
    assert any(e["to"] == "automation-service" for e in extras), (
        "electron-builder.yml must include automation-service as extraResource"
    )
    assert any(e["to"] == "database" for e in extras)
    # GitHub Releases publisher (consumed by the backend UpdateManager).
    pub = data.get("publish", {})
    assert pub.get("provider") == "github"
    assert pub.get("owner") == "babyline00"
    assert pub.get("repo") == "z-agent-automation"


def test_package_json_has_packaging_scripts() -> None:
    path = DESKTOP / "package.json"
    data = json.loads(path.read_text())
    scripts = data.get("scripts", {})
    for required in (
        "build",
        "build:all",
        "build:electron",
        "pack",
        "dist",
        "dist:win",
        "dist:mac",
        "dist:linux",
        "release",
        "typecheck",
        "test",
    ):
        assert required in scripts, f"package.json missing script {required!r}"
    # build:all must compile renderer AND electron in one shot.
    assert "tsc -p electron/tsconfig.json" in scripts["build:all"]
    assert "vite build" in scripts["build:all"]
    # dist scripts must call electron-builder with the right platform flag.
    assert "electron-builder --win" in scripts["dist:win"]
    assert "electron-builder --mac" in scripts["dist:mac"]
    assert "electron-builder --linux" in scripts["dist:linux"]
    assert "electron-builder --publish always" in scripts["release"]
    # devDependencies must include electron-builder.
    dev_deps = data.get("devDependencies", {})
    assert "electron-builder" in dev_deps, (
        "package.json devDependencies missing electron-builder"
    )
    # The build block must point at the standalone yml so `electron-builder`
    # picks it up without us re-declaring every option inline.
    build_block = data.get("build", {})
    assert build_block.get("extends") == "./electron-builder.yml"


# ---------------------------------------------------------------------------
# GitHub Actions CI
# ---------------------------------------------------------------------------


def test_ci_workflow_exists() -> None:
    path = REPO_ROOT / ".github" / "workflows" / "ci.yml"
    assert path.exists(), f"{path} does not exist"
    data = yaml.safe_load(path.read_text())
    assert data.get("name") == "CI"
    # Triggers: push to main/develop, PRs to main.
    on_block = data.get(True, data.get("on"))  # yaml parses `on:` as True sometimes
    assert "push" in on_block
    push_branches = on_block["push"].get("branches", [])
    assert "main" in push_branches
    assert "develop" in push_branches
    assert "pull_request" in on_block


def test_ci_workflow_has_jobs() -> None:
    path = REPO_ROOT / ".github" / "workflows" / "ci.yml"
    data = yaml.safe_load(path.read_text())
    jobs = data.get("jobs", {})
    for required in ("python-tests", "python-lint", "frontend-build", "release"):
        assert required in jobs, f"ci.yml missing job {required!r}"

    # python-tests must run the full pytest suite under mock mode.
    py_steps = jobs["python-tests"]["steps"]
    py_step_runs = [s.get("run", "") for s in py_steps]
    assert any("uv run pytest" in r for r in py_step_runs), (
        "python-tests job must run pytest"
    )
    assert any("uv sync" in r for r in py_step_runs), (
        "python-tests job must run uv sync to install deps"
    )
    # mock mode must be on for the test step.
    test_step = next(s for s in py_steps if "uv run pytest" in s.get("run", ""))
    assert test_step.get("env", {}).get("AUTOMATION_MOCK_MODE") == "true"

    # python-lint must run ruff check + ruff format --check.
    lint_runs = [s.get("run", "") for s in jobs["python-lint"]["steps"]]
    assert any("ruff check" in r for r in lint_runs)
    assert any("ruff format --check" in r for r in lint_runs)

    # frontend-build must typecheck + build renderer + build electron.
    fe_steps = jobs["frontend-build"]["steps"]
    fe_runs = [s.get("run", "") for s in fe_steps]
    assert any("tsc --noEmit" in r for r in fe_runs), (
        "frontend-build job must run tsc --noEmit"
    )
    assert any("npm run build" in r for r in fe_runs), (
        "frontend-build job must run npm run build (Vite)"
    )
    assert any("npm run build:electron" in r for r in fe_runs), (
        "frontend-build job must run npm run build:electron"
    )
    assert any("setup-uv" in json.dumps(s) for s in fe_steps) or any(
        "setup-node" in json.dumps(s) for s in fe_steps
    )

    # release must depend on the three upstream jobs + only fire on tags.
    release = jobs["release"]
    needs = release.get("needs", [])
    for required in ("python-tests", "python-lint", "frontend-build"):
        assert required in needs, f"release job missing dependency {required!r}"
    # `if: startsWith(github.ref, 'refs/tags/v')` gates the release.
    if_expr = release.get("if", "")
    assert "refs/tags/v" in if_expr, (
        "release job must be gated on tag push (refs/tags/v*)"
    )
    # Matrix must cover the three desktop platforms.
    matrix = release.get("strategy", {}).get("matrix", {})
    assert "ubuntu-latest" in matrix.get("os", [])
    assert "windows-latest" in matrix.get("os", [])
    assert "macos-latest" in matrix.get("os", [])
    # Release must publish via GH_TOKEN.
    release_runs = [s.get("run", "") for s in release["steps"]]
    assert any("npm run dist" in r for r in release_runs)
    assert any("GH_TOKEN" in json.dumps(s) for s in release["steps"]), (
        "release job must inject GH_TOKEN for electron-builder --publish"
    )


# ---------------------------------------------------------------------------
# Docs
# ---------------------------------------------------------------------------


def test_contributing_exists() -> None:
    path = REPO_ROOT / "CONTRIBUTING.md"
    assert path.exists(), f"{path} does not exist"
    text = path.read_text()
    # Must cover the core topics.
    assert "uv sync" in text, "CONTRIBUTING.md must document uv sync setup"
    assert "npm ci" in text or "npm install" in text
    assert ".env" in text
    # Must reference the worklog protocol per AGENTS.md.
    assert "worklog" in text.lower()
    # Must mention the master prompt compliance checklist.
    assert "master prompt" in text.lower() or "§" in text


def test_license_exists() -> None:
    path = REPO_ROOT / "LICENSE"
    assert path.exists(), f"{path} does not exist"
    text = path.read_text()
    assert "MIT License" in text
    assert "2026 Z User" in text
    # Sanity: the standard MIT permission clause must be present.
    assert "Permission is hereby granted, free of charge" in text
