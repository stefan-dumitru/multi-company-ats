"""Worker liveness (operations.md > Observability): the worker proves it is alive in the
database, and the web app's /health/worker reads that proof."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.worker import heartbeat

NOW = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)


def test_no_heartbeat_means_no_worker(db: Session) -> None:
    assert heartbeat.worker_is_alive(db, NOW) is False
    assert heartbeat.last_heartbeat(db) is None


def test_a_fresh_heartbeat_means_alive(db: Session) -> None:
    heartbeat.record_heartbeat(db, NOW)

    assert heartbeat.worker_is_alive(db, NOW + timedelta(seconds=59)) is True


def test_an_old_heartbeat_means_the_worker_is_gone(db: Session) -> None:
    heartbeat.record_heartbeat(db, NOW)

    assert heartbeat.worker_is_alive(db, NOW + timedelta(seconds=61)) is False


def test_beating_again_replaces_the_old_beat_instead_of_adding_rows(db: Session) -> None:
    heartbeat.record_heartbeat(db, NOW)
    heartbeat.record_heartbeat(db, NOW + timedelta(seconds=30))

    assert heartbeat.last_heartbeat(db) == NOW + timedelta(seconds=30)


def test_the_health_endpoint_is_503_without_a_worker(client: TestClient) -> None:
    response = client.get("/health/worker")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


def test_the_health_endpoint_is_200_with_a_fresh_beat(client: TestClient, db: Session) -> None:
    heartbeat.record_heartbeat(db, datetime.now(UTC))

    response = client.get("/health/worker")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_the_health_endpoint_is_503_when_the_beat_is_stale(client: TestClient, db: Session) -> None:
    heartbeat.record_heartbeat(db, datetime.now(UTC) - timedelta(minutes=5))

    assert client.get("/health/worker").status_code == 503
