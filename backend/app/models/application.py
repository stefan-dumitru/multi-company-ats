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
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ApplicationStage(enum.StrEnum):
    APPLIED = "applied"
    SCREENING = "screening"
    INTERVIEW = "interview"
    OFFER = "offer"
    HIRED = "hired"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


# Where an application can still be withdrawn from: not once it ended in a hire or a rejection.
ACTIVE_STAGES = (
    ApplicationStage.APPLIED,
    ApplicationStage.SCREENING,
    ApplicationStage.INTERVIEW,
    ApplicationStage.OFFER,
)


def stage_column(name: str, *, nullable: bool = False) -> Enum:
    """A stage stored as text with a CHECK constraint, so the database rejects unknown values."""
    return Enum(
        ApplicationStage,
        native_enum=False,
        length=20,
        create_constraint=True,
        name=name,
        values_callable=lambda stages: [stage.value for stage in stages],
    )


class Application(Base):
    """One candidate's application to one job, and where it stands (data-model.md).

    Created by the candidate; the stage changes by withdrawing and reactivating (and, from the next
    phase, by recruiters). Never deleted.
    """

    __tablename__ = "applications"
    __table_args__ = (
        # One application per candidate per job, for good: a retry or a double click finds it.
        UniqueConstraint("candidate_id", "job_id", name="uq_applications_candidate_job"),
        CheckConstraint("version > 0", name="version_positive"),
        # A remembered stage exists exactly while the application is withdrawn...
        CheckConstraint(
            "(stage = 'withdrawn') = (stage_before_withdrawal IS NOT NULL)",
            name="withdrawal_stage_matches",
        ),
        # ...and it is always one the candidate could have withdrawn from.
        CheckConstraint(
            "stage_before_withdrawal IS NULL OR "
            "stage_before_withdrawal IN ('applied', 'screening', 'interview', 'offer')",
            name="withdrawal_from_active_stage",
        ),
        Index("ix_applications_company_id_job_id", "company_id", "job_id"),
        Index("ix_applications_candidate_id_created_at", "candidate_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id"))
    # Copied from the job, so a company's applications can be filtered by one column.
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    # The resume on file when the candidate applied. Replacing the resume later does not change it.
    resume_file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("files.id"))
    stage: Mapped[ApplicationStage] = mapped_column(
        stage_column("application_stage_is_known"),
        default=ApplicationStage.APPLIED,
        server_default=ApplicationStage.APPLIED.value,
    )
    stage_before_withdrawal: Mapped[ApplicationStage | None] = mapped_column(
        stage_column("application_withdrawal_stage_is_known")
    )
    # Goes up on every change; the recruiters' screens (a later phase) quote it.
    version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ApplicationStageHistory(Base):
    """One row per stage change: the record of how an application moved (never edited)."""

    __tablename__ = "application_stage_history"
    __table_args__ = (Index("ix_application_stage_history_application_id", "application_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id"))
    # Null for the first row: the application did not exist before it was made.
    from_stage: Mapped[ApplicationStage | None] = mapped_column(
        stage_column("history_from_stage_is_known")
    )
    to_stage: Mapped[ApplicationStage] = mapped_column(stage_column("history_to_stage_is_known"))
    changed_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
