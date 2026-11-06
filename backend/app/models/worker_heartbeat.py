from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class WorkerHeartbeat(Base):
    """The worker's "I am alive" note: one row, rewritten on every pass of its loop.

    The web app cannot see the worker process (they are separate services), but both can see the
    database, so /health/worker reads this row.
    """

    __tablename__ = "worker_heartbeats"

    name: Mapped[str] = mapped_column(String(50), primary_key=True)
    beat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # The hosting platform's id for the deployment this worker runs in. During a release it lets
    # the pipeline tell the new worker's heartbeat from the old worker's last one.
    deployment_id: Mapped[str | None] = mapped_column(String(100))
