"""What the public sees of a job. A short, fixed list of fields: nothing about who works on it."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class PublicJobSummaryOut(BaseModel):
    id: uuid.UUID
    title: str
    location: str
    excerpt: str
    department_name: str
    company_id: uuid.UUID
    company_name: str
    opened_at: datetime | None


class PublicJobOut(BaseModel):
    id: uuid.UUID
    title: str
    location: str
    description: str
    department_name: str
    company_id: uuid.UUID
    company_name: str
    opened_at: datetime | None
