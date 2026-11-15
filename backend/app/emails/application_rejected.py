"""Told to a candidate when their application is rejected.

Deliberately generic: the reason category and the recruiter's comment are internal and are never
read here, so they cannot leak into the email.
"""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_app_base_url
from app.emails.base import Email
from app.emails.invitation import one_line
from app.models import Application, Company, Job, User


def render_application_rejected(db: Session, payload: dict[str, Any]) -> Email | None:
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
        f"Thank you for your interest in {title} at {company_name} and for the time you put "
        f"into your application.\n\n"
        f"After careful consideration the hiring team has decided not to continue with your "
        f"application. We know this is not the news you hoped for, and we wish you the very best "
        f"in your search.\n\n"
        f"You can see your applications here:\n{get_app_base_url()}/applications\n"
    )
    return Email(
        to=candidate.email,
        subject=f"Your application for {title} at {company_name}",
        body=body,
    )
