"""The worker's liveness note (see models/worker_heartbeat.py)."""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import WorkerHeartbeat

HEARTBEAT_NAME = "worker"
# The loop beats every couple of seconds; a job takes seconds. A minute of silence means trouble.
FRESH_FOR = timedelta(seconds=60)


def record_heartbeat(db: Session, now: datetime) -> None:
    """Write "alive at `now`" and commit (a worker-side step, like the queue's)."""
    db.execute(
        insert(WorkerHeartbeat)
        .values(name=HEARTBEAT_NAME, beat_at=now)
        .on_conflict_do_update(index_elements=["name"], set_={"beat_at": now})
    )
    db.commit()


def last_heartbeat(db: Session) -> datetime | None:
    return db.scalar(select(WorkerHeartbeat.beat_at).where(WorkerHeartbeat.name == HEARTBEAT_NAME))


def worker_is_alive(db: Session, now: datetime) -> bool:
    beat = last_heartbeat(db)
    return beat is not None and now - beat <= FRESH_FOR
