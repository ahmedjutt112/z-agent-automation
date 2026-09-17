"""SQLAlchemy 2.x declarative base + session factory.

Supports both:
- Turso libSQL (primary, cloud) — `libsql://...` URLs
- Local SQLite (fallback, offline dev) — `sqlite:///...` URLs

The active backend is chosen via DATABASE_URL env var.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

# Load .env before any DB URL resolution
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(Path("/home/z/my-project/.env"), override=True)
except ImportError:  # pragma: no cover
    pass

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
    pass


# ---------------------------------------------------------------------------
# Resolve database URL + auth token
# ---------------------------------------------------------------------------

DB_PATH = Path("/home/z/my-project/db/custom.db")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def _resolve_db_url() -> tuple[str, dict]:
    """Return (sqlalchemy_url, connect_args) based on env vars."""
    raw_url = os.environ.get("DATABASE_URL", f"file:{DB_PATH}")

    # Turso libSQL — cloud distributed SQLite
    if raw_url.startswith("libsql://") or raw_url.startswith("libsql+ws://"):
        token = os.environ.get("TURSO_AUTH_TOKEN", "")
        if not token:
            # No token → fall back to local SQLite (offline dev mode)
            return f"sqlite:///{DB_PATH}", {"check_same_thread": False}
        # sqlalchemy-libsql registers the 'sqlite.libsql' dialect.
        # authToken must be passed via query string AND connect_args.auth_token
        # because the dialect builds the libsql URL from the host + query.
        host = raw_url.split("://", 1)[1].split("?")[0]
        url = f"sqlite+libsql://{host}?authToken={token}&secure=true"
        return url, {}

    # Local file SQLite (master prompt §27 — SQLite is the primary DB)
    if raw_url.startswith("file:"):
        return f"sqlite:///{raw_url[5:]}", {"check_same_thread": False}

    # Already a SQLAlchemy URL
    if "://" in raw_url:
        return raw_url, {}

    # Default fallback
    return f"sqlite:///{DB_PATH}", {"check_same_thread": False}


DB_URL, DB_CONNECT_ARGS = _resolve_db_url()


def _make_engine() -> Engine:
    """Create the SQLAlchemy engine based on the resolved URL."""
    # The sqlalchemy-libsql dialect needs authToken to be re-passed via
    # connect_args because the URL.query dict isn't propagated cleanly to
    # libsql_experimental.connect(auth_token=...). Workaround: extract it.
    if DB_URL.startswith("sqlite+libsql"):
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(DB_URL)
        qs = parse_qs(parsed.query)
        token = qs.get("authToken", [""])[0]
        # Re-build URL without authToken in query (it goes via connect_args)
        host = parsed.netloc
        clean_url = f"sqlite+libsql://{host}?secure=true"
        return create_engine(
            clean_url,
            echo=False,
            connect_args={"auth_token": token, "check_same_thread": False, "uri": True},
        )
    return create_engine(DB_URL, echo=False, connect_args=DB_CONNECT_ARGS)


engine = _make_engine()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency that yields a session and closes it after."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables. Idempotent — safe to call on every startup."""
    # Import all model modules so that Base.metadata sees them
    from .models import schema  # noqa: F401

    Base.metadata.create_all(bind=engine)


def db_backend_info() -> dict:
    """Return a dict describing the active DB backend (for /health endpoint)."""
    if DB_URL.startswith("libsql"):
        return {"backend": "turso", "url": DB_URL.split("?")[0], "cloud": True}
    if DB_URL.startswith("sqlite"):
        return {"backend": "sqlite", "url": DB_URL, "cloud": False}
    return {"backend": "other", "url": DB_URL, "cloud": True}
