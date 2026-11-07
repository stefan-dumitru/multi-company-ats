"""Failed-job alerting (operations.md > Observability): the web app reports whether any job gave up
recently, so the scheduled monitor can turn red when one does."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import JobStatus
from app.worker import queue, status

NOW = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)


def _job(db: Session, key: str, job_status: JobStatus, finished_at: datetime | None) -> None:
    job = queue.enqueue(db, type="send_email", payload={}, idempotency_key=key, now=NOW)
    job.status = job_status
    job.finished_at = finished_at
    db.commit()


def test_no_jobs_means_no_recent_failures(db: Session) -> None:
    assert status.recent_failure_count(db, NOW, timedelta(hours=1)) == 0


def test_a_job_that_gave_up_inside_the_window_is_counted(db: Session) -> None:
    _job(db, "a", JobStatus.FAILED, NOW - timedelta(minutes=30))
    _job(db, "b", JobStatus.FAILED, NOW - timedelta(minutes=5))

    assert status.recent_failure_count(db, NOW, timedelta(hours=1)) == 2


def test_a_job_that_gave_up_before_the_window_is_not_counted(db: Session) -> None:
    # Failed jobs stay in the table for good; without a window one failure would alert forever.
    _job(db, "old", JobStatus.FAILED, NOW - timedelta(hours=2))

    assert status.recent_failure_count(db, NOW, timedelta(hours=1)) == 0


def test_jobs_that_are_still_retrying_or_succeeded_are_not_failures(db: Session) -> None:
    _job(db, "retrying", JobStatus.PENDING, None)
    _job(db, "running", JobStatus.RUNNING, None)
    _job(db, "done", JobStatus.SUCCEEDED, NOW - timedelta(minutes=1))

    assert status.recent_failure_count(db, NOW, timedelta(hours=1)) == 0


def test_the_endpoint_is_200_when_nothing_failed(client: TestClient) -> None:
    response = client.get("/health/jobs?since_minutes=65")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "failed": 0}


def test_the_endpoint_is_503_and_gives_only_a_count_when_a_job_failed(
    client: TestClient, db: Session
) -> None:
    _job(db, "a", JobStatus.FAILED, datetime.now(UTC) - timedelta(minutes=10))

    response = client.get("/health/jobs?since_minutes=65")

    assert response.status_code == 503
    # Counts only: no job ids, types, errors or addresses on a public route.
    assert response.json() == {"status": "failing", "failed": 1}


def test_the_endpoint_ignores_a_failure_older_than_the_window(
    client: TestClient, db: Session
) -> None:
    _job(db, "a", JobStatus.FAILED, datetime.now(UTC) - timedelta(minutes=90))

    assert client.get("/health/jobs?since_minutes=65").status_code == 200
    assert client.get("/health/jobs?since_minutes=120").status_code == 503


def test_the_endpoint_needs_a_sensible_window(client: TestClient) -> None:
    assert client.get("/health/jobs").status_code == 422
    assert client.get("/health/jobs?since_minutes=0").status_code == 422
    assert client.get("/health/jobs?since_minutes=-5").status_code == 422
    assert client.get("/health/jobs?since_minutes=abc").status_code == 422
    assert client.get("/health/jobs?since_minutes=100000").status_code == 422
