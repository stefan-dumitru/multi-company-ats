"""The full migration chain must apply to an empty database (a CI gate, see operations.md).

Needs a reachable Postgres via DATABASE_URL (docker compose locally, a service container in CI).
It creates a throwaway database so it never touches the one you develop against.
"""

import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from app.config import get_database_url

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


@pytest.fixture
def empty_database_url(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    server_url = make_url(get_database_url())
    scratch_name = f"ats_migration_test_{uuid.uuid4().hex[:8]}"
    # CREATE/DROP DATABASE cannot run inside a transaction, hence autocommit.
    admin_dsn = server_url.set(drivername="postgresql", database="postgres").render_as_string(
        hide_password=False
    )
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{scratch_name}"')
    scratch_url = server_url.set(database=scratch_name).render_as_string(hide_password=False)
    monkeypatch.setenv("DATABASE_URL", scratch_url)
    try:
        yield scratch_url
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{scratch_name}" WITH (FORCE)')


def test_migrations_apply_to_an_empty_database(empty_database_url: str) -> None:
    config = Config(str(ALEMBIC_INI))

    command.upgrade(config, "head")

    head = ScriptDirectory.from_config(config).get_current_head()
    engine = create_engine(empty_database_url)
    with engine.connect() as connection:
        applied = MigrationContext.configure(connection).get_current_revision()
    engine.dispose()
    assert applied == head
    assert head is not None
