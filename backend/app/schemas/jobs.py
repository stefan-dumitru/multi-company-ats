import uuid
from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.models import PostingStatus

JobTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
JobLocation = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
JobDescription = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20_000)
]


class CreateJobRequest(BaseModel):
    """What a person writes. The status, creator and company are never taken from the request."""

    model_config = ConfigDict(extra="forbid")

    title: JobTitle
    location: JobLocation
    description: JobDescription
    department_id: uuid.UUID


class UpdateJobRequest(BaseModel):
    """Only the fields that changed, plus the version the person was looking at."""

    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    title: JobTitle | None = None
    location: JobLocation | None = None
    description: JobDescription | None = None
    department_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def no_field_is_set_to_null(self) -> Self:
        # Leaving a field out means "unchanged"; sending null is a mistake, not "clear it".
        for name in self.model_fields_set - {"version"}:
            if getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self

    def changes(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.model_fields_set - {"version"}}


class VersionRequest(BaseModel):
    """For publish and close: the version the person was looking at."""

    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)


class AssignRecruiterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: uuid.UUID


class DepartmentRef(BaseModel):
    id: uuid.UUID
    name: str
    is_archived: bool


class RecruiterOut(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str
    is_active: bool


class JobSummaryOut(BaseModel):
    """A job as listed: no description, no recruiters."""

    id: uuid.UUID
    title: str
    location: str
    status: PostingStatus
    department_id: uuid.UUID
    department_name: str
    created_at: datetime
    opened_at: datetime | None
    closed_at: datetime | None
    version: int
    # A draft or open job with no active recruiter: an admin should assign someone.
    needs_reassignment: bool


class JobOut(BaseModel):
    id: uuid.UUID
    title: str
    location: str
    description: str
    status: PostingStatus
    department: DepartmentRef
    created_at: datetime
    opened_at: datetime | None
    closed_at: datetime | None
    version: int
    needs_reassignment: bool
    recruiters: list[RecruiterOut]
