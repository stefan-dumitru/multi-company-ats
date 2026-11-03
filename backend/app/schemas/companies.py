from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import EmailAddress, PersonName


class RegisterCompanyRequest(BaseModel):
    # Unknown fields are an error, not ignored: nobody can sneak in a role or a company id.
    model_config = ConfigDict(extra="forbid")

    company_name: PersonName
    full_name: PersonName
    email: EmailAddress
    # The real rules (length) are in auth/passwords.py; this cap only stops absurd input early.
    password: str = Field(max_length=1024)
