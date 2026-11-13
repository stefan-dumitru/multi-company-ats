import re
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.common import EmailAddress, PersonName

MAX_PHONE_LENGTH = 30
MAX_LOCATION_LENGTH = 200
# Digits and the usual separators: "+47 (0)12 345-678". Letters and markup are not phone numbers.
_PHONE_CHARACTERS = re.compile(r"[0-9 +().\-]+")


class RegisterCandidateRequest(BaseModel):
    # Unknown fields are an error, not ignored: nobody can sneak in a role or a company id.
    model_config = ConfigDict(extra="forbid")

    full_name: PersonName
    email: EmailAddress
    # The real rules (length) are in auth/passwords.py; this cap only stops absurd input early.
    password: str = Field(max_length=1024)


class UpdateProfileRequest(BaseModel):
    """The fields a candidate may change about themselves. Only what is sent is changed."""

    model_config = ConfigDict(extra="forbid")

    full_name: PersonName | None = None
    # Sending null (or only spaces) clears the field; leaving it out leaves it alone.
    phone: str | None = None
    location: str | None = None

    @model_validator(mode="after")
    def the_name_cannot_be_cleared(self) -> Self:
        if "full_name" in self.model_fields_set and self.full_name is None:
            raise ValueError("full_name cannot be null")
        return self

    @field_validator("phone")
    @classmethod
    def check_phone(cls, value: str | None) -> str | None:
        value = (value or "").strip()
        if not value:
            return None
        if len(value) > MAX_PHONE_LENGTH or not _PHONE_CHARACTERS.fullmatch(value):
            raise ValueError("Enter a phone number with digits, spaces and + ( ) - . only.")
        return value

    @field_validator("location")
    @classmethod
    def check_location(cls, value: str | None) -> str | None:
        value = (value or "").strip()
        if len(value) > MAX_LOCATION_LENGTH:
            raise ValueError("The location is too long.")
        return value or None

    def changes(self) -> dict[str, str | None]:
        return {name: getattr(self, name) for name in self.model_fields_set}


class ProfileOut(BaseModel):
    full_name: str
    email: str
    phone: str | None
    location: str | None
