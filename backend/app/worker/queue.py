"""The job queue, kept in Postgres (operations.md > Background Jobs & Queues).

Two sides use it, and they differ on purpose about committing:

* The web app calls `enqueue` inside the request's own transaction and never commits here: the job
  is saved if and only if the business change it belongs to is saved.
* The worker calls `claim_next`, `complete` and `fail`, which each commit, because they are short
  steps of their own. In particular the slow work (sending an email) happens *between* claiming and
  completing, outside any database transaction.

Every function takes the current time as a parameter, so the tests never sleep.
"""

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import get_job_backoff_seconds
from app.models import BackgroundJob, JobStatus

__all__ = [
    "MAX_ERROR_LENGTH",
    "STUCK_AFTER",
    "JobStatus",
    "claim_next",
    "complete",
    "enqueue",
    "fail",
    "lock_next_due",
    "requeue_stuck",
]

# A job "running" for longer than this means its worker died. Mail has a 10 second timeout, so a
# healthy job finishes in seconds; this leaves a wide margin.
STUCK_AFTER = timedelta(minutes=10)
MAX_ERROR_LENGTH = 500


def enqueue(
    db: Session,
    *,
    type: str,
    payload: dict[str, Any],
    idempotency_key: str,
    now: datetime,
    run_at: datetime | None = None,
) -> BackgroundJob:
    """Queue a job, in the caller's transaction. Queueing the same key twice is a no-op.

    The payload carries ids only: never secrets, and never personal details the handler can load
    itself.
    """
    db.execute(
        insert(BackgroundJob)
        .values(
            type=type,
            payload=payload,
            idempotency_key=idempotency_key,
            run_at=run_at or now,
            created_at=now,
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
    )
    return db.scalars(
        select(BackgroundJob).where(BackgroundJob.idempotency_key == idempotency_key)
    ).one()


def lock_next_due(db: Session, now: datetime) -> BackgroundJob | None:
    """Lock the oldest due job, skipping any that another worker already holds.

    SKIP LOCKED is the whole trick: a worker never waits for a job someone else is handling, it
    just takes the next one, so any number of workers can share the queue without double work.
    """
    return db.scalars(
        select(BackgroundJob)
        .where(BackgroundJob.status == JobStatus.PENDING, BackgroundJob.run_at <= now)
        .order_by(BackgroundJob.run_at, BackgroundJob.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()


def claim_next(db: Session, now: datetime) -> BackgroundJob | None:
    """Take the next due job: mark it running, count the attempt, and commit straight away.

    Committing at once releases the database lock; from here on `status = running` is what keeps
    other workers away while this one does the slow part.
    """
    job = lock_next_due(db, now)
    if job is None:
        db.commit()  # always commits, like every worker-side step here, even with nothing to take
        return None
    job.status = JobStatus.RUNNING
    job.attempts += 1
    job.locked_at = now
    db.commit()
    return job


def complete(db: Session, job: BackgroundJob, now: datetime) -> None:
    job.status = JobStatus.SUCCEEDED
    job.finished_at = now
    job.locked_at = None
    db.commit()


def fail(db: Session, job: BackgroundJob, error: str, now: datetime) -> None:
    """Record a failed attempt: retry later with a growing delay, or give up after the last one."""
    _record_failure(job, error, now)
    db.commit()


def requeue_stuck(db: Session, now: datetime) -> int:
    """Rescue jobs whose worker vanished (crash, restart) while they were running.

    The lost attempt still counts, so a job that kills its worker every time cannot loop forever.
    """
    stuck = db.scalars(
        select(BackgroundJob)
        .where(
            BackgroundJob.status == JobStatus.RUNNING, BackgroundJob.locked_at < now - STUCK_AFTER
        )
        .with_for_update(skip_locked=True)
    ).all()
    for job in stuck:
        _record_failure(job, "Worker stopped responding while running this job.", now)
    db.commit()
    return len(stuck)


def _record_failure(job: BackgroundJob, error: str, now: datetime) -> None:
    # Read the setting first: a bad value must stop us before the job is half changed.
    delays = get_job_backoff_seconds()
    job.last_error = error[:MAX_ERROR_LENGTH]
    job.locked_at = None
    if job.attempts >= job.max_attempts:
        job.status = JobStatus.FAILED
        job.finished_at = now
        return
    # After attempt 1 use the first delay, after attempt 2 the second... and the last one if the
    # list runs out.
    delay = delays[min(job.attempts - 1, len(delays) - 1)]
    job.status = JobStatus.PENDING
    job.run_at = now + timedelta(seconds=delay)
