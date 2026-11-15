"""The confirmation sent to a candidate after they apply."""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_app_base_url
from app.emails.base import Email
from app.emails.invitation import one_line
from app.models import Application, Company, Job, User


def render_application_received(db: Session, payload: dict[str, Any]) -> Email | None:
    application = db.get(Application, uuid.UUID(payload["application_id"]))
    if application is None:
        return None
    job = db.get(Job, application.job_id)
    company = db.get(Company, application.company_id)
    candidate = db.get(User, application.candidate_id)
    if job is None or company is None or candidate is None:
        return None

    title, company_name = one_line(job.title), one_line(company.name)
    body = (
        f"Hello {one_line(candidate.full_name)},\n\n"
        f"We have received your application for {title} at {company_name}.\n\n"
        f"You can follow it, or withdraw it, at any time:\n{get_app_base_url()}/applications\n"
    )
    return Email(
        to=candidate.email,
        subject=f"Application received: {title} at {company_name}",
        body=body,
    )
