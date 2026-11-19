import uuid
from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import InterviewStatus, Recommendation
from app.models.scorecard import MAX_FEEDBACK_LENGTH

# A whole number from 1 to 5. Strict: "4" and 4.0 are not ratings, and neither is null.
Rating = Annotated[int, Field(ge=1, le=5, strict=True)]


class InterviewFilter(StrEnum):
    ALL = "all"
    UPCOMING = "upcoming"  # scheduled, still to come
    AWAITING = "awaiting"  # scheduled, already started, and I have not scored it


class SubmitScorecardRequest(BaseModel):
    """What an interviewer writes. Who they are and which interview come from the session and the
    address, never from the request."""

    model_config = ConfigDict(extra="forbid")

    overall_rating: Rating
    technical_rating: Rating
    communication_rating: Rating
    problem_solving_rating: Rating
    culture_fit_rating: Rating
    feedback: str = Field(max_length=MAX_FEEDBACK_LENGTH + 1000)
    recommendation: Recommendation

    @field_validator("feedback")
    @classmethod
    def feedback_is_words(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("the feedback cannot be empty")
        if len(trimmed) > MAX_FEEDBACK_LENGTH:
            raise ValueError(f"the feedback can have at most {MAX_FEEDBACK_LENGTH} characters")
        return trimmed


class ScorecardOut(BaseModel):
    id: uuid.UUID
    interviewer_name: str
    overall_rating: int
    technical_rating: int
    communication_rating: int
    problem_solving_rating: int
    culture_fit_rating: int
    feedback: str
    recommendation: Recommendation
    submitted_at: datetime


class MyInterviewOut(BaseModel):
    """One of an interviewer's own interviews, as listed."""

    id: uuid.UUID
    round_name: str
    scheduled_at: datetime
    duration_minutes: int
    location: str
    status: InterviewStatus
    job_title: str
    # Null once the interview is cancelled: the person may have been rejected or withdrawn, and an
    # interviewer has no reason to keep seeing who they are.
    candidate_name: str | None
    my_scorecard_submitted: bool


class CandidateInfoOut(BaseModel):
    name: str
    email: str
    phone: str | None
    location: str | None


class MyInterviewDetailOut(BaseModel):
    id: uuid.UUID
    round_name: str
    scheduled_at: datetime
    duration_minutes: int
    location: str
    status: InterviewStatus
    job_title: str
    candidate: CandidateInfoOut | None
    my_scorecard: ScorecardOut | None
    # Blind scoring: false until I have submitted, and `others` is empty until then.
    others_visible: bool
    others: list[ScorecardOut]
