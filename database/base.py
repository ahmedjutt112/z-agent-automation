"""SQLAlchemy 2.x declarative base + session factory."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
    pass


# DB lives at /home/z/my-project/db/custom.db (matches .env DATABASE_URL)
DB_PATH = Path("/home/z/my-project/db/custom.db")
DB_URL = f"sqlite:///{DB_PATH}"


# Ensure parent dir exists
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


engine = create_engine(
    DB_URL,
    echo=False,
    connect_args={"check_same_thread": False},  # needed for FastAPI + SQLAlchemy
)

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
