"""The text behind `python -m app.worker status`."""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import BackgroundJob, JobStatus
from app.worker import heartbeat

RECENT_FAILURES_SHOWN = 10


def job_counts(db: Session) -> dict[str, int]:
    rows = db.execute(select(BackgroundJob.status, func.count()).group_by(BackgroundJob.status))
    found = {status: count for status, count in rows}
    return {status.value: found.get(status, 0) for status in JobStatus}


def format_status(db: Session, now: datetime) -> str:
    lines = [f"{status}: {count}" for status, count in job_counts(db).items()]

    beat = heartbeat.last_heartbeat(db)
    if beat is None:
        lines.append("worker: no worker has checked in yet")
    else:
        lines.append(f"worker: last checked in {int((now - beat).total_seconds())} seconds ago")

    failed = db.scalars(
        select(BackgroundJob)
        .where(BackgroundJob.status == JobStatus.FAILED)
        .order_by(BackgroundJob.finished_at.desc())
        .limit(RECENT_FAILURES_SHOWN)
    ).all()
    if failed:
        lines.append("")
        lines.append("Failed jobs (newest first):")
        lines += [f"  {job.type} {job.id}: {job.last_error}" for job in failed]
    return "\n".join(lines)
