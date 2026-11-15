"""Told to a candidate when their application reaches a new stage."""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_app_base_url
from app.emails.base import Email
from app.emails.invitation import one_line
from app.models import Application, ApplicationStage, Company, Job, User

# What each milestone means for the candidate, in words. "Applied" is not here: the confirmation
# email already covers it. A stage that is not here gets no email.
NEWS: dict[ApplicationStage, str] = {
    ApplicationStage.SCREENING: "Your application is being reviewed by the hiring team.",
    ApplicationStage.INTERVIEW: "You have moved on to the interview stage. The hiring team "
    "will be in touch about the details.",
    ApplicationStage.OFFER: "Good news: you have reached the offer stage. The hiring team will "
    "be in touch with the details.",
    ApplicationStage.HIRED: "Congratulations! The company has decided to hire you.",
}


def render_application_stage_changed(db: Session, payload: dict[str, Any]) -> Email | None:
    try:
        stage = ApplicationStage(payload["stage"])
    except ValueError:
        return None
    news = NEWS.get(stage)
    if news is None:
        return None
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
        f"An update on your application for {title} at {company_name}:\n\n"
        f"{news}\n\n"
        f"You can follow it at any time:\n{get_app_base_url()}/applications\n"
    )
    return Email(
        to=candidate.email,
        subject=f"Your application for {title} at {company_name}: update",
        body=body,
    )
