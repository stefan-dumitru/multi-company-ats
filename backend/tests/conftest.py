"""Shared fixtures. `db` gives a test a real Postgres built from the migrations.

Needs a reachable Postgres via DATABASE_URL (docker compose locally, a service container in CI).
A throwaway database is created once per test run, so the one you develop against is never touched.
"""

import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.config import get_database_url, get_storage_settings
from app.db import Base, get_db
from app.integrations import storage
from app.main import app

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


@pytest.fixture(autouse=True)
def signing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Links are signed with SECRET_KEY, which the web app requires at startup. Tests use a
    throwaway low-entropy value (not secret-looking, so the secret scan has nothing to flag)."""
    monkeypatch.setenv("SECRET_KEY", "k" * 40)


@pytest.fixture(scope="session")
def migrated_database_url() -> Iterator[str]:
    server_url = make_url(get_database_url())
    scratch_name = f"ats_test_{uuid.uuid4().hex[:8]}"
    # CREATE/DROP DATABASE cannot run inside a transaction, hence autocommit.
    admin_dsn = server_url.set(drivername="postgresql", database="postgres").render_as_string(
        hide_password=False
    )
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{scratch_name}"')
    scratch_url = server_url.set(database=scratch_name).render_as_string(hide_password=False)

    # Alembic reads DATABASE_URL itself (alembic/env.py), so point it at the scratch database for
    # the duration of the upgrade only; other tests keep seeing the real setting.
    patch = pytest.MonkeyPatch()
    patch.setenv("DATABASE_URL", scratch_url)
    try:
        command.upgrade(Config(str(ALEMBIC_INI)), "head")
    finally:
        patch.undo()
    try:
        yield scratch_url
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{scratch_name}" WITH (FORCE)')


@pytest.fixture(scope="session")
def scratch_engine(migrated_database_url: str) -> Iterator[Engine]:
    engine = create_engine(migrated_database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def db(scratch_engine: Engine) -> Iterator[Session]:
    """A session on the migrated database; every table is emptied again after each test."""
    with Session(scratch_engine) as session:
        yield session
    quote = scratch_engine.dialect.identifier_preparer.quote
    tables = ", ".join(quote(table.name) for table in Base.metadata.sorted_tables)
    with scratch_engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {tables} CASCADE"))


@pytest.fixture
def client(db: Session, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """The real app, talking to the test database, over https like a real browser would."""
    # The tests must not depend on the developer's shell (a local .env turns the Secure flag off).
    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    app.dependency_overrides[get_db] = lambda: db
    # https, because the session cookie is Secure and a client would not send it over plain http.
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def storage_bucket(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """A fresh, empty bucket on the S3-compatible test server, selected through S3_BUCKET.

    The server comes from docker compose locally (see .env.example) and from a step in the pull
    request pipeline. Without it these tests fail, loudly, instead of quietly not running.
    """
    settings = get_storage_settings()
    if settings is None:
        pytest.fail(
            "No storage settings. Start the test server with `docker compose up -d --wait` and "
            "load .env into your shell (the README shows how)."
        )
    bucket = f"ats-test-{uuid.uuid4().hex[:12]}"
    client = storage.client_for(settings)
    client.create_bucket(Bucket=bucket)
    monkeypatch.setenv("S3_BUCKET", bucket)
    yield bucket
    listing = client.list_objects_v2(Bucket=bucket)
    for item in listing.get("Contents", []):
        client.delete_object(Bucket=bucket, Key=item["Key"])
    client.delete_bucket(Bucket=bucket)
