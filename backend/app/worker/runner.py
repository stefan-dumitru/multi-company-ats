"""The worker loop: take a due job, run its handler, record the outcome, repeat.

Handlers are plain functions `handler(db, job)`. They do their work and return; they never commit
(the runner commits their database changes together with marking the job done) and they raise to
signal failure. Their changes are rolled back on failure, so a retry starts clean.
"""

import logging
import threading
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import BackgroundJob, JobStatus
from app.worker import heartbeat, queue

logger = logging.getLogger("ats.worker")

Handler = Callable[[Session, BackgroundJob], None]
Clock = Callable[[], datetime]

POLL_SECONDS = 2.0


def utc_now() -> datetime:
    return datetime.now(UTC)


def run_one_job(db: Session, handlers: Mapping[str, Handler], clock: Clock = utc_now) -> bool:
    """Run the next due job, if any. Returns whether there was one."""
    job = queue.claim_next(db, clock())
    if job is None:
        return False

    # Read these now: after a commit or rollback the job object must be reloaded to be read.
    job_id, job_type, attempt = str(job.id), job.type, job.attempts
    handler = handlers.get(job_type)
    try:
        if handler is None:
            # Retried rather than dropped: during a deploy the web app can be newer than the worker.
            raise LookupError(f"No handler for job type {job_type!r}")
        handler(db, job)
    except Exception as error:  # noqa: BLE001 - any handler may fail in any way; it is recorded
        db.rollback()  # also repairs a transaction the handler broke
        queue.fail(db, job, f"{type(error).__name__}: {error}", clock())
        outcome = "failed" if job.status == JobStatus.FAILED else "retry"
        level = logging.ERROR if outcome == "failed" else logging.WARNING
        # Only the error's class is logged: its text may hold an address, and it is in the job row.
        logger.log(
            level,
            "job attempt failed",
            extra={
                "job_id": job_id,
                "job_type": job_type,
                "attempt": attempt,
                "outcome": outcome,
                "error_type": type(error).__name__,
            },
        )
    else:
        queue.complete(db, job, clock())
        logger.info(
            "job finished",
            extra={
                "job_id": job_id,
                "job_type": job_type,
                "attempt": attempt,
                "outcome": "succeeded",
            },
        )
    return True


def run_loop(
    db: Session,
    stop: threading.Event,
    handlers: Mapping[str, Handler],
    poll_seconds: float = POLL_SECONDS,
    clock: Clock = utc_now,
) -> None:
    """Work until `stop` is set. A job already running is finished first, never cut off."""
    while not stop.is_set():
        try:
            heartbeat.record_heartbeat(db, clock())
            queue.requeue_stuck(db, clock())
            did_work = run_one_job(db, handlers, clock)
        except SQLAlchemyError:
            # A database hiccup (restart, dropped connection) should not end the worker: Railway
            # would restart it anyway, but waiting and retrying is quicker and quieter.
            db.rollback()
            logger.exception("worker loop hit a database error")
            did_work = False
        if not did_work:
            stop.wait(poll_seconds)  # returns early when asked to stop
