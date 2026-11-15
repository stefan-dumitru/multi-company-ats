import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import ApplicationStage, RejectionReason
from app.models.note import MAX_NOTE_LENGTH

MAX_COMMENT_LENGTH = 2000


class ApplyRequest(BaseModel):
    """Only the job. Who applies comes from the session; the stage and company are never sent."""

    model_config = ConfigDict(extra="forbid")

    job_id: uuid.UUID


class MyApplicationOut(BaseModel):
    """An application as its own candidate sees it. Nothing recruiters write ever appears here."""

    id: uuid.UUID
    job_id: uuid.UUID
    job_title: str
    company_name: str
    stage: ApplicationStage
    applied_at: datetime
    # Whether the job still takes applications: a withdrawn application can only come back if so.
    job_is_open: bool


class ApplicantOut(BaseModel):
    """One application on a job, as staff see it. Never includes the resume itself."""

    id: uuid.UUID
    candidate_name: str
    candidate_email: str
    stage: ApplicationStage
    applied_at: datetime


class RejectRequest(BaseModel):
    """A rejection: the version looked at, a reason from the fixed list, an internal comment."""

    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    reason: RejectionReason
    comment: str | None = Field(default=None, max_length=MAX_COMMENT_LENGTH)

    @field_validator("comment")
    @classmethod
    def blank_comment_is_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None

    @model_validator(mode="after")
    def other_explains_itself(self) -> Self:
        if self.reason == RejectionReason.OTHER and self.comment is None:
            raise ValueError("a comment is required when the reason is 'other'")
        return self


class RejectionOut(BaseModel):
    from_stage: ApplicationStage
    reason: RejectionReason
    comment: str | None


class HistoryEntryOut(BaseModel):
    from_stage: ApplicationStage | None
    to_stage: ApplicationStage
    changed_by_name: str
    changed_at: datetime


class ApplicationDetailOut(BaseModel):
    """One application as staff see it. Never sent to a candidate: it holds internal fields."""

    id: uuid.UUID
    job_id: uuid.UUID
    job_title: str
    candidate_name: str
    candidate_email: str
    candidate_phone: str | None
    candidate_location: str | None
    stage: ApplicationStage
    # What "move forward" would do now; null once there is nowhere to go.
    next_stage: ApplicationStage | None
    version: int
    applied_at: datetime
    rejection: RejectionOut | None
    history: list[HistoryEntryOut]


class CreateNoteRequest(BaseModel):
    """Only the words. The author comes from the session, the application from the address."""

    model_config = ConfigDict(extra="forbid")

    body: str = Field(max_length=MAX_NOTE_LENGTH + 1000)

    @field_validator("body")
    @classmethod
    def not_blank_and_not_too_long(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("a note cannot be empty")
        if len(trimmed) > MAX_NOTE_LENGTH:
            raise ValueError(f"a note can have at most {MAX_NOTE_LENGTH} characters")
        return trimmed


class NoteOut(BaseModel):
    id: uuid.UUID
    author_name: str
    body: str
    created_at: datetime
