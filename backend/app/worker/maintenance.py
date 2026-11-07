"""Housekeeping: delete old technical rows so the tables do not grow forever.

Runs as a queued job, once an hour (data-model.md > Data Retention). Only technical records are
purged. Anything that is history (the audit log, invitations, the data of real people) is never
touched here.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, Delete, and_, delete, or_
from sqlalchemy.orm import Session

from app.models import BackgroundJob, JobStatus, LoginAttempt, UserSession, UserToken
from app.worker.queue import enqueue

logger = logging.getLogger("ats.worker")

# The login lockout only looks back 15 minutes, so a day is generous.
LOGIN_ATTEMPT_RETENTION = timedelta(hours=24)
# A session is useless once it expired or was revoked; a week is kept in case someone is
# investigating a login.
SESSION_RETENTION_AFTER_END = timedelta(days=7)
# The longest idle timeout is a week (candidates), so a session untouched for a month is dead even
# if its absolute lifetime has not run out.
SESSION_IDLE_LIMIT = timedelta(days=30)
TOKEN_RETENTION_AFTER_END = timedelta(days=7)
SUCCEEDED_JOB_RETENTION = timedelta(days=30)
# Failed jobs stay longer: someone may still want to find out why.
FAILED_JOB_RETENTION = timedelta(days=90)


def hour_bucket(now: datetime) -> str:
    return now.astimezone(UTC).strftime("%Y-%m-%dT%H")


def schedule_maintenance(db: Session, now: datetime) -> None:
    """Queue this hour's maintenance job, unless it is already queued, and commit.

    The key names the hour, so any number of workers (or restarts) in the same hour queue exactly
    one job between them.
    """
    enqueue(
        db,
        type="maintenance",
        payload={},
        idempotency_key=f"maintenance:{hour_bucket(now)}",
        now=now,
    )
    db.commit()


def deleted(db: Session, statement: Delete) -> int:
    """Run a DELETE and say how many rows it removed."""
    return cast("CursorResult[Any]", db.execute(statement)).rowcount


def purge_old_rows(db: Session, now: datetime) -> dict[str, int]:
    """Delete rows past their retention window. Returns how many were deleted per table.

    One DELETE per table, in the caller's transaction. These tables stay small enough that no
    batching is needed; revisit if one ever grows into millions of rows.
    """
    login_attempts = deleted(
        db, delete(LoginAttempt).where(LoginAttempt.attempted_at < now - LOGIN_ATTEMPT_RETENTION)
    )
    sessions = deleted(
        db,
        delete(UserSession).where(
            or_(
                UserSession.expires_at < now - SESSION_RETENTION_AFTER_END,
                UserSession.revoked_at < now - SESSION_RETENTION_AFTER_END,
                UserSession.last_seen_at < now - SESSION_IDLE_LIMIT,
            )
        ),
    )
    user_tokens = deleted(
        db,
        delete(UserToken).where(
            or_(
                UserToken.used_at < now - TOKEN_RETENTION_AFTER_END,
                UserToken.expires_at < now - TOKEN_RETENTION_AFTER_END,
            )
        ),
    )
    background_jobs = deleted(
        db,
        delete(BackgroundJob).where(
            or_(
                and_(
                    BackgroundJob.status == JobStatus.SUCCEEDED,
                    BackgroundJob.finished_at < now - SUCCEEDED_JOB_RETENTION,
                ),
                and_(
                    BackgroundJob.status == JobStatus.FAILED,
                    BackgroundJob.finished_at < now - FAILED_JOB_RETENTION,
                ),
            )
        ),
    )
    return {
        "login_attempts": login_attempts,
        "sessions": sessions,
        "user_tokens": user_tokens,
        "background_jobs": background_jobs,
    }


def maintenance_job(db: Session, _job: BackgroundJob) -> None:
    """The handler for the hourly job. Logs only how many rows went, never what they held."""
    counts = purge_old_rows(db, datetime.now(UTC))
    logger.info("maintenance finished", extra=counts)
