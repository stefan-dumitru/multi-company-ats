import uuid
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

DepartmentName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]


class DepartmentNameRequest(BaseModel):
    """Create or rename. Only the name: the company always comes from the session."""

    model_config = ConfigDict(extra="forbid")

    name: DepartmentName


class DepartmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    is_archived: bool
