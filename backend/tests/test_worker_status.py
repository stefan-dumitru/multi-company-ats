"""`python -m app.worker status`: how an operator sees the queue, including failed jobs."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.worker import heartbeat, queue
from app.worker.status import format_status, job_counts

NOW = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)


def test_every_status_is_listed_even_when_empty(db: Session) -> None:
    assert job_counts(db) == {"pending": 0, "running": 0, "succeeded": 0, "failed": 0}


def test_jobs_are_counted_by_status(db: Session) -> None:
    for key in ("a", "b", "c"):
        queue.enqueue(db, type="t", payload={}, idempotency_key=key, now=NOW)
    taken = queue.claim_next(db, NOW)
    assert taken is not None

    counts = job_counts(db)

    assert counts == {"pending": 2, "running": 1, "succeeded": 0, "failed": 0}


def test_the_report_shows_failed_jobs_with_their_reason(db: Session) -> None:
    queue.enqueue(db, type="send_email", payload={}, idempotency_key="a", now=NOW)
    for _ in range(5):
        job = queue.claim_next(db, NOW + timedelta(days=30))
        assert job is not None
        queue.fail(db, job, "SMTP refused the message", NOW)

    report = format_status(db, NOW)

    assert "failed: 1" in report
    assert "send_email" in report
    assert "SMTP refused the message" in report


def test_the_report_says_when_the_worker_last_checked_in(db: Session) -> None:
    heartbeat.record_heartbeat(db, NOW - timedelta(seconds=7))

    assert "7 seconds ago" in format_status(db, NOW)


def test_the_report_says_when_no_worker_has_ever_run(db: Session) -> None:
    assert "no worker has checked in" in format_status(db, NOW)
