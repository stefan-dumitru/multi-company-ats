"""Behavior of the unauthenticated /health and /ready endpoints (operations.md > Observability)."""

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.db import get_db
from app.main import app, get_applied_revision, get_head_revision


@pytest.fixture
def db_session() -> MagicMock:
    return MagicMock()


@pytest.fixture
def client(db_session: MagicMock) -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_health_is_ok_when_database_answers(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_is_503_when_database_is_down(client: TestClient, db_session: MagicMock) -> None:
    db_session.execute.side_effect = OperationalError(
        "SELECT 1", {}, Exception("connection refused")
    )

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


def test_health_does_not_leak_internal_error_details(
    client: TestClient, db_session: MagicMock
) -> None:
    db_session.execute.side_effect = OperationalError(
        "SELECT 1", {}, Exception("password authentication failed for user ats")
    )

    response = client.get("/health")

    assert "password" not in response.text
    assert "ats" not in response.text


def test_ready_is_ok_when_migrations_are_at_head(client: TestClient) -> None:
    app.dependency_overrides[get_head_revision] = lambda: "0001"
    app.dependency_overrides[get_applied_revision] = lambda: "0001"

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_ready_is_503_when_migrations_are_behind(client: TestClient) -> None:
    app.dependency_overrides[get_head_revision] = lambda: "0002"
    app.dependency_overrides[get_applied_revision] = lambda: "0001"

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not ready"}


def test_ready_is_503_when_database_has_no_migrations_applied(client: TestClient) -> None:
    app.dependency_overrides[get_head_revision] = lambda: "0001"
    app.dependency_overrides[get_applied_revision] = lambda: None

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not ready"}


def test_ready_is_503_when_database_is_down(client: TestClient, db_session: MagicMock) -> None:
    # Only the head revision is faked: the real get_applied_revision must turn a database error
    # into "not ready" instead of a 500.
    db_session.connection.side_effect = OperationalError(
        "connect", {}, Exception("connection refused")
    )
    app.dependency_overrides[get_head_revision] = lambda: "0001"

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not ready"}
