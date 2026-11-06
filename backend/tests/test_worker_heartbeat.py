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


def test_a_heartbeat_can_be_checked_against_the_deployment_that_wrote_it(db: Session) -> None:
    # Lets the release pipeline ask "is the NEW worker alive?", not just "is some worker alive?"
    heartbeat.record_heartbeat(db, NOW, deployment_id="dep-new")

    assert heartbeat.worker_is_alive(db, NOW, deployment_id="dep-new") is True
    assert heartbeat.worker_is_alive(db, NOW, deployment_id="dep-old") is False


def test_without_a_deployment_any_fresh_heartbeat_counts(db: Session) -> None:
    heartbeat.record_heartbeat(db, NOW, deployment_id="dep-new")

    assert heartbeat.worker_is_alive(db, NOW) is True


def test_a_heartbeat_from_a_matching_deployment_still_has_to_be_fresh(db: Session) -> None:
    heartbeat.record_heartbeat(db, NOW, deployment_id="dep-new")

    assert (
        heartbeat.worker_is_alive(db, NOW + timedelta(minutes=5), deployment_id="dep-new") is False
    )


def test_a_worker_that_does_not_know_its_deployment_never_matches_one(db: Session) -> None:
    heartbeat.record_heartbeat(db, NOW)  # local development: no deployment id

    assert heartbeat.worker_is_alive(db, NOW, deployment_id="dep-new") is False


def test_the_health_endpoint_can_be_asked_about_one_deployment(
    client: TestClient, db: Session
) -> None:
    heartbeat.record_heartbeat(db, datetime.now(UTC), deployment_id="dep-new")

    assert client.get("/health/worker?deployment=dep-new").status_code == 200
    assert client.get("/health/worker?deployment=dep-old").status_code == 503
    assert client.get("/health/worker").status_code == 200


def test_the_health_endpoint_refuses_an_absurdly_long_deployment_id(client: TestClient) -> None:
    assert client.get("/health/worker?deployment=" + "x" * 500).status_code == 422


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
