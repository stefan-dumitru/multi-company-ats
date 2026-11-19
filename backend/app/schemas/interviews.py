import uuid
from datetime import datetime
from typing import Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import CalendarSyncStatus, InterviewStatus
from app.models.interview import (
    MAX_DURATION_MINUTES,
    MAX_LOCATION_LENGTH,
    MAX_ROUND_NAME_LENGTH,
    MIN_DURATION_MINUTES,
)

MAX_INTERVIEWERS = 10


def _trimmed(value: str, *, name: str, longest: int) -> str:
    trimmed = value.strip()
    if not trimmed:
        raise ValueError(f"{name} cannot be empty")
    if len(trimmed) > longest:
        raise ValueError(f"{name} can have at most {longest} characters")
    return trimmed


class ScheduleInterviewRequest(BaseModel):
    """What a recruiter writes. The company, the status and who scheduled it are never taken from
    the request."""

    model_config = ConfigDict(extra="forbid")

    round_name: str = Field(max_length=MAX_ROUND_NAME_LENGTH + 100)
    # A time with its zone: "3 pm" means nothing without knowing where. Stored as UTC.
    scheduled_at: AwareDatetime
    duration_minutes: int = Field(ge=MIN_DURATION_MINUTES, le=MAX_DURATION_MINUTES)
    location: str = Field(max_length=MAX_LOCATION_LENGTH + 100)
    interviewer_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_INTERVIEWERS)

    @field_validator("round_name")
    @classmethod
    def round_name_is_words(cls, value: str) -> str:
        return _trimmed(value, name="the round name", longest=MAX_ROUND_NAME_LENGTH)

    @field_validator("location")
    @classmethod
    def location_is_words(cls, value: str) -> str:
        return _trimmed(value, name="the location", longest=MAX_LOCATION_LENGTH)

    @model_validator(mode="after")
    def interviewers_are_listed_once(self) -> Self:
        if len(set(self.interviewer_ids)) != len(self.interviewer_ids):
            raise ValueError("an interviewer can only be listed once")
        return self


class ParticipantOut(BaseModel):
    user_id: uuid.UUID
    full_name: str
    # False once the person was deactivated: the interview then needs a new interviewer.
    is_active: bool


class InterviewOut(BaseModel):
    id: uuid.UUID
    application_id: uuid.UUID
    round_name: str
    scheduled_at: datetime
    duration_minutes: int
    location: str
    status: InterviewStatus
    version: int
    calendar_sync_status: CalendarSyncStatus
    needs_reassignment: bool
    participants: list[ParticipantOut]
    created_at: datetime


class UpdateInterviewRequest(BaseModel):
    """The version the recruiter was looking at, and only the fields they want to change."""

    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    round_name: str | None = Field(default=None, max_length=MAX_ROUND_NAME_LENGTH + 100)
    scheduled_at: AwareDatetime | None = None
    duration_minutes: int | None = Field(
        default=None, ge=MIN_DURATION_MINUTES, le=MAX_DURATION_MINUTES
    )
    location: str | None = Field(default=None, max_length=MAX_LOCATION_LENGTH + 100)
    interviewer_ids: list[uuid.UUID] | None = Field(
        default=None, min_length=1, max_length=MAX_INTERVIEWERS
    )

    @field_validator("round_name")
    @classmethod
    def round_name_is_words(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("the round name cannot be null")
        return _trimmed(value, name="the round name", longest=MAX_ROUND_NAME_LENGTH)

    @field_validator("location")
    @classmethod
    def location_is_words(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("the location cannot be null")
        return _trimmed(value, name="the location", longest=MAX_LOCATION_LENGTH)

    @model_validator(mode="after")
    def something_to_change_and_no_nulls(self) -> Self:
        sent = self.model_fields_set - {"version"}
        if not sent:
            raise ValueError("nothing to change")
        for name in sent:
            if getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        if self.interviewer_ids is not None and len(set(self.interviewer_ids)) != len(
            self.interviewer_ids
        ):
            raise ValueError("an interviewer can only be listed once")
        return self

    def changes(self) -> dict[str, object]:
        """Just the fields that were sent."""
        return {name: getattr(self, name) for name in self.model_fields_set - {"version"}}


class InterviewerOut(BaseModel):
    """What a picker shows: nothing else about the person."""

    id: uuid.UUID
    full_name: str
    email: str
