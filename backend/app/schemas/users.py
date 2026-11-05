import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models import Role
from app.schemas.invitations import InvitableRole


class ManagedUserOut(BaseModel):
    """A company member as an admin sees them. No password hash, no internal flags."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    role: Role
    is_active: bool
    deactivated_at: datetime | None
    last_login_at: datetime | None
    created_at: datetime


class ChangeRoleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Staff roles only: a company member can never be turned into a candidate.
    role: InvitableRole
