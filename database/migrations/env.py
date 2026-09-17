"""Alembic env.py — wires migrations to the project's Turso/libSQL engine.

Reuses database.base.Base.metadata and database.base.engine so migrations
target the same DB the app uses.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "apps" / "automation-service"))

# Load .env
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(PROJECT_ROOT / ".env", override=True)
except ImportError:
    pass

# Import the project's Base + engine
from database.base import Base, DB_URL, engine  # noqa: E402
import database.models.schema  # noqa: F401, E402  # registers all models with Base.metadata


config = context.config

# Override the sqlalchemy.url in alembic.ini with the resolved DB_URL
# (handles libsql:// Turso URLs)
config.set_main_option("sqlalchemy.url", DB_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL to stdout)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (connect to DB and execute)."""
    # For Turso libsql URLs, use the existing project engine (which handles
    # the auth_token workaround); for plain SQLite, use Alembic's default.
    if DB_URL.startswith("sqlite+libsql"):
        connectable = engine
    else:
        connectable = engine_from_config(
            config.get_section(config.config_ini_section, {}),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=True,  # SQLite-compatible
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
