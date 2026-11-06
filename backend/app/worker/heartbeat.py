"""The worker's liveness note (see models/worker_heartbeat.py)."""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import WorkerHeartbeat

HEARTBEAT_NAME = "worker"
# The loop beats every couple of seconds; a job takes seconds. A minute of silence means trouble.
FRESH_FOR = timedelta(seconds=60)


def record_heartbeat(db: Session, now: datetime, deployment_id: str | None = None) -> None:
    """Write "alive at `now`" and commit (a worker-side step, like the queue's)."""
    db.execute(
        insert(WorkerHeartbeat)
        .values(name=HEARTBEAT_NAME, beat_at=now, deployment_id=deployment_id)
        .on_conflict_do_update(
            index_elements=["name"], set_={"beat_at": now, "deployment_id": deployment_id}
        )
    )
    db.commit()


def last_heartbeat(db: Session) -> datetime | None:
    return db.scalar(select(WorkerHeartbeat.beat_at).where(WorkerHeartbeat.name == HEARTBEAT_NAME))


def worker_is_alive(db: Session, now: datetime, deployment_id: str | None = None) -> bool:
    """Is there a fresh heartbeat? With `deployment_id`, one from that deployment's worker."""
    row = db.scalars(select(WorkerHeartbeat).where(WorkerHeartbeat.name == HEARTBEAT_NAME)).first()
    if row is None or now - row.beat_at > FRESH_FOR:
        return False
    return deployment_id is None or row.deployment_id == deployment_id
