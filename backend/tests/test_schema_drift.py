"""Guard against model-vs-migration drift.

A SQLAlchemy model column only exists in production if some Alembic migration
created it. Nothing enforces that link: adding ``updated_at`` to a model and
forgetting the ``op.add_column`` leaves the codebase looking healthy —
``alembic current`` reports head, the models import fine — while every SELECT
against that table raises ``UndefinedColumnError`` in production. Features
whose errors are deliberately swallowed (best-effort Telegram pushes, for
instance) then fail silently for as long as nobody reads the logs.

These tests close that hole. ``conftest.py`` builds the test database by
running the migration chain, so reflecting it here and comparing against
``Base.metadata`` compares *migrations* against *models* — the two artefacts
that must agree. A column added to a model without a migration fails here, and
so does a migration that creates a column no model knows about.
"""
from __future__ import annotations

import pathlib

import pytest
from sqlalchemy import inspect
from sqlalchemy.engine import Connection

from app.core.database import Base, engine as app_engine


# Bookkeeping table owned by Alembic itself — never present in Base.metadata.
_ALEMBIC_TABLES = {"alembic_version"}


def _reflect(conn: Connection) -> dict[str, set[str]]:
    """Table name -> column names, as the migrated database actually is."""
    inspector = inspect(conn)
    return {
        table: {col["name"] for col in inspector.get_columns(table)}
        for table in inspector.get_table_names()
        if table not in _ALEMBIC_TABLES
    }


@pytest.fixture
async def live_schema() -> dict[str, set[str]]:
    async with app_engine.connect() as conn:
        return await conn.run_sync(_reflect)


async def test_every_model_table_exists_in_the_migrated_database(live_schema):
    """A model with no CREATE TABLE migration would break every query on it."""
    missing = sorted(set(Base.metadata.tables) - set(live_schema))
    assert not missing, (
        "Tables declared by models but never created by a migration: "
        f"{missing}. Add an Alembic revision with op.create_table()."
    )


async def test_migrated_database_has_no_tables_the_models_dropped(live_schema):
    """A leftover table means a model was deleted without a drop migration."""
    orphaned = sorted(set(live_schema) - set(Base.metadata.tables))
    assert not orphaned, (
        "Tables created by migrations with no matching model: "
        f"{orphaned}. Drop them in a migration or restore the model."
    )


async def test_every_model_column_exists_in_the_migrated_database(live_schema):
    """The outage guard: a model column with no op.add_column behind it.

    This is what breaks production while the suite stays green — under
    ``Base.metadata.create_all`` the column is conjured from the model itself,
    so the drift is unobservable.
    """
    missing: dict[str, list[str]] = {}
    for name, table in Base.metadata.tables.items():
        db_columns = live_schema.get(name)
        if db_columns is None:
            continue  # reported by the missing-table test
        gap = {col.name for col in table.columns} - db_columns
        if gap:
            missing[name] = sorted(gap)

    assert not missing, (
        "Model columns missing from the migrated schema (every query touching "
        f"them raises UndefinedColumnError in production): {missing}"
    )


async def test_migrated_database_has_no_columns_the_models_dropped(live_schema):
    """An extra column is milder but still drift — usually a forgotten cleanup,
    and it hides NOT NULL columns that inserts from the ORM never populate."""
    extra: dict[str, list[str]] = {}
    for name, db_columns in live_schema.items():
        table = Base.metadata.tables.get(name)
        if table is None:
            continue  # reported by the orphaned-table test
        gap = db_columns - {col.name for col in table.columns}
        if gap:
            extra[name] = sorted(gap)

    assert not extra, (
        f"Columns present in the migrated schema but absent from the models: {extra}"
    )


async def test_importing_the_models_package_alone_registers_every_table():
    """``alembic/env.py`` sees only what ``import app.models`` registers.

    Inside pytest this is invisible: ``conftest.py`` imports ``app.main``, which
    pulls in the routers, and a router importing a model is enough to attach it
    to ``Base.metadata``. Alembic imports no routers. A model file missing from
    ``app/models/__init__.py`` is therefore absent from ``target_metadata``, and
    the next ``alembic revision --autogenerate`` writes ``op.drop_table()`` for
    it into an otherwise innocuous migration. Run in a subprocess so the check
    is against a clean interpreter, not this process's already-loaded modules.
    """
    import subprocess
    import sys

    probe = (
        "import app.models\n"
        "from app.core.database import Base\n"
        "print(','.join(sorted(Base.metadata.tables)))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=str(pathlib.Path(__file__).resolve().parent.parent),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    alembic_sees = set(result.stdout.strip().split(","))

    missing = sorted(set(Base.metadata.tables) - alembic_sees)
    assert not missing, (
        "Tables invisible to alembic/env.py because no module in app/models/"
        f"__init__.py imports them: {missing}. Add the import there."
    )
