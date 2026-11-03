import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import Role
from app.schemas.common import EmailAddress, PersonName

# Candidates register themselves, so they are not an option here.
InvitableRole = Literal[Role.COMPANY_ADMIN, Role.RECRUITER, Role.INTERVIEWER]
InvitationStatus = Literal["pending", "accepted", "expired", "revoked"]


class CreateInvitationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailAddress
    role: InvitableRole


class InvitationOut(BaseModel):
    """An invitation as listed. Never includes the token: that is shown once, at creation."""

    id: uuid.UUID
    email: str
    role: Role
    status: InvitationStatus
    created_at: datetime
    expires_at: datetime


class InvitationCreated(BaseModel):
    invitation: InvitationOut
    token: str
    # Relative on purpose: the page lives on the same origin as the API.
    accept_path: str


class AcceptInvitationRequest(BaseModel):
    # No role or company here: both come from the invitation, never from the invitee.
    model_config = ConfigDict(extra="forbid")

    token: str = Field(max_length=200)
    full_name: PersonName
    password: str = Field(max_length=1024)
