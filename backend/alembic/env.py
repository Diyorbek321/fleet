from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from logging.config import fileConfig
from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection

# Ensure the backend/ directory (the one containing `app/`) is on sys.path
# so `alembic upgrade head` works from any cwd.
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings
from app.core.database import Base
# Import the models package as a whole rather than naming modules one by one:
# a per-module list silently goes stale when a new model file is added, and a
# model missing from `target_metadata` is invisible to `--autogenerate`, which
# is exactly how a table drifts away from its migrations.
import app.models  # noqa: F401

config = context.config
fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Placeholder shipped in alembic.ini. Anything else means the caller supplied a
# real DSN programmatically (Config.set_main_option) and means it — the test
# suite relies on this to migrate its own throwaway database instead of
# whatever DATABASE_URL happens to point at.
_URL_PLACEHOLDER = "driver://user:pass@localhost/dbname"


def _database_url() -> str:
    """DSN for this migration run: explicit config override, else settings."""
    configured = (config.get_main_option("sqlalchemy.url") or "").strip()
    if configured and configured != _URL_PLACEHOLDER:
        return configured
    return settings.database_url

def run_migrations_offline():
    url = _database_url().replace("+asyncpg", "")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        transaction_per_migration=True,
    )
    with context.begin_transaction():
        context.run_migrations()

def do_run_migrations(connection: Connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        transaction_per_migration=True,
    )
    with context.begin_transaction():
        context.run_migrations()

async def run_migrations_online():
    from sqlalchemy.ext.asyncio import create_async_engine

    connectable = create_async_engine(_database_url(), poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()

if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
