import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models import ApplicationStage


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
