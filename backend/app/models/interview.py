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
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

MIN_DURATION_MINUTES = 5
MAX_DURATION_MINUTES = 480
MAX_ROUND_NAME_LENGTH = 100
MAX_LOCATION_LENGTH = 300


class InterviewStatus(enum.StrEnum):
    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class CalendarSyncStatus(enum.StrEnum):
    NOT_REQUESTED = "not_requested"  # the recruiter has no calendar connected
    PENDING = "pending"  # the worker has not finished creating the event
    SYNCED = "synced"
    FAILED = "failed"  # the last retry failed; the interview itself is unaffected


def _text_enum(enum_class: type[enum.StrEnum], name: str, length: int) -> Enum:
    """An enum stored as text with a CHECK constraint, so the database rejects unknown values."""
    return Enum(
        enum_class,
        native_enum=False,
        length=length,
        create_constraint=True,
        name=name,
        values_callable=lambda members: [member.value for member in members],
    )


class Interview(Base):
    """One interview round for an application (data-model.md > Interview).

    Times are UTC. Never deleted: a cancelled interview stays, with its history.
    """

    __tablename__ = "interviews"
    __table_args__ = (
        CheckConstraint(
            f"duration_minutes BETWEEN {MIN_DURATION_MINUTES} AND {MAX_DURATION_MINUTES}",
            name="duration_in_range",
        ),
        CheckConstraint("version > 0", name="version_positive"),
        Index("ix_interviews_application_id", "application_id"),
        Index("ix_interviews_company_id_scheduled_at", "company_id", "scheduled_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    # Copied from the application, so a company's interviews can be filtered by one column.
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id"))
    round_name: Mapped[str] = mapped_column(String(MAX_ROUND_NAME_LENGTH))
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_minutes: Mapped[int] = mapped_column(Integer)
    location: Mapped[str] = mapped_column(String(MAX_LOCATION_LENGTH))
    status: Mapped[InterviewStatus] = mapped_column(
        _text_enum(InterviewStatus, "interview_status_is_known", 20),
        default=InterviewStatus.SCHEDULED,
        server_default=InterviewStatus.SCHEDULED.value,
    )
    scheduled_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    # Filled in by the worker once a Google Calendar event exists (a later step).
    google_event_id: Mapped[str | None] = mapped_column(String(200))
    calendar_sync_status: Mapped[CalendarSyncStatus] = mapped_column(
        _text_enum(CalendarSyncStatus, "interview_calendar_sync_status_is_known", 20),
        default=CalendarSyncStatus.NOT_REQUESTED,
        server_default=CalendarSyncStatus.NOT_REQUESTED.value,
    )
    # Goes up on every change; reschedule and cancel send the version they were looking at.
    version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InterviewParticipant(Base):
    """An interviewer assigned to an interview: the basis of "sees only their interviews"."""

    __tablename__ = "interview_participants"
    __table_args__ = (Index("ix_interview_participants_interviewer_id", "interviewer_id"),)

    interview_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("interviews.id"), primary_key=True)
    interviewer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
