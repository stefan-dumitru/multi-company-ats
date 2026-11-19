import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

MAX_FEEDBACK_LENGTH = 4000
RATINGS = (
    "overall_rating",
    "technical_rating",
    "communication_rating",
    "problem_solving_rating",
    "culture_fit_rating",
)


class Recommendation(enum.StrEnum):
    STRONG_NO = "strong_no"
    NO = "no"
    YES = "yes"
    STRONG_YES = "strong_yes"


class Scorecard(Base):
    """One interviewer's evaluation of one interview (data-model.md > Scorecard).

    Final once submitted: no edit, no delete. Who may read it is decided by the query that fetches
    it (blind scoring), never by a flag stored here.
    """

    __tablename__ = "scorecards"
    __table_args__ = (
        UniqueConstraint(
            "interview_id", "interviewer_id", name="uq_scorecards_interview_interviewer"
        ),
        # The author must be assigned to the interview: the database refuses anyone else, whatever
        # the application code does. It also stops an assigned interviewer who has scored from being
        # removed from the interview.
        ForeignKeyConstraint(
            ["interview_id", "interviewer_id"],
            ["interview_participants.interview_id", "interview_participants.interviewer_id"],
            name="fk_scorecards_participant",
        ),
        *(
            CheckConstraint(f"{column} BETWEEN 1 AND 5", name=f"{column}_in_range")
            for column in RATINGS
        ),
        CheckConstraint("length(btrim(feedback)) > 0", name="feedback_not_blank"),
        CheckConstraint(f"length(feedback) <= {MAX_FEEDBACK_LENGTH}", name="feedback_not_too_long"),
        Index("ix_scorecards_interviewer_id", "interviewer_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    interview_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    interviewer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    overall_rating: Mapped[int] = mapped_column(SmallInteger)
    technical_rating: Mapped[int] = mapped_column(SmallInteger)
    communication_rating: Mapped[int] = mapped_column(SmallInteger)
    problem_solving_rating: Mapped[int] = mapped_column(SmallInteger)
    culture_fit_rating: Mapped[int] = mapped_column(SmallInteger)
    feedback: Mapped[str] = mapped_column(Text)
    recommendation: Mapped[Recommendation] = mapped_column(
        Enum(
            Recommendation,
            native_enum=False,
            length=20,
            create_constraint=True,
            name="scorecard_recommendation_is_known",
            values_callable=lambda members: [member.value for member in members],
        )
    )
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
