import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.models import Role


class LoginRequest(BaseModel):
    email: str = Field(max_length=320)
    # Generous cap, only so nobody can make the server hash megabytes of text.
    password: str = Field(max_length=1024)


class UserOut(BaseModel):
    """What the API says about a user. Deliberately has no password hash or internal flags."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    role: Role
    company_id: uuid.UUID | None


class SessionInfo(BaseModel):
    user: UserOut
    # The SPA keeps this in memory and sends it back in the X-CSRF-Token header.
    csrf_token: str
