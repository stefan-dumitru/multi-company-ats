import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class PostingStatus(enum.StrEnum):
    """Where a job is in its life. (Not `JobStatus`: that name belongs to background jobs.)"""

    DRAFT = "draft"
    OPEN = "open"
    CLOSED = "closed"


class Job(Base):
    """An open position that candidates can apply to (data-model.md > Job)."""

    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("version > 0", name="version_positive"),
        # The list screens filter a company's jobs by status.
        Index("ix_jobs_company_id_status", "company_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    department_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("departments.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    location: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[PostingStatus] = mapped_column(
        Enum(
            PostingStatus,
            native_enum=False,
            length=20,
            create_constraint=True,
            name="posting_status_is_known",
            values_callable=lambda statuses: [status.value for status in statuses],
        ),
        default=PostingStatus.DRAFT,
        server_default=PostingStatus.DRAFT.value,
    )
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Goes up on every change; an edit must quote the version it saw (optimistic locking).
    version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))


class JobRecruiter(Base):
    """Assigns a recruiter to a job: the table behind "a recruiter sees only their own jobs"."""

    __tablename__ = "job_recruiters"

    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True, index=True)
    added_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
