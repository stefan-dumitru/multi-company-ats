"""Emails about an interview: to each interviewer and to the candidate.

The payload holds ids only: the interview and the person to write to. The template decides what that
person may be told. Times are always written in UTC and say so: the server does not know anyone's
time zone.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_app_base_url
from app.emails.base import Email
from app.emails.invitation import one_line
from app.models import (
    Application,
    Company,
    Interview,
    InterviewParticipant,
    Job,
    Role,
    User,
)


def _utc(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _render(db: Session, payload: dict[str, Any], *, kind: str) -> Email | None:
    """kind is 'scheduled', 'rescheduled' or 'cancelled'."""
    interview = db.get(Interview, uuid.UUID(payload["interview_id"]))
    if interview is None:
        return None
    application = db.get(Application, interview.application_id)
    if application is None:
        return None
    job = db.get(Job, application.job_id)
    company = db.get(Company, application.company_id)
    candidate = db.get(User, application.candidate_id)
    recipient = db.get(User, uuid.UUID(payload["recipient_id"]))
    if job is None or company is None or candidate is None or recipient is None:
        return None

    is_candidate = recipient.id == candidate.id
    if not is_candidate:
        # Only people actually assigned to the interview are written to.
        assigned = db.scalar(
            select(InterviewParticipant.interviewer_id).where(
                InterviewParticipant.interview_id == interview.id,
                InterviewParticipant.interviewer_id == recipient.id,
            )
        )
        if assigned is None:
            return None

    title = one_line(job.title)
    company_name = one_line(company.name)
    round_name = one_line(interview.round_name)
    candidate_name = one_line(candidate.full_name)
    details = (
        f"Round: {round_name}\n"
        f"When: {_utc(interview.scheduled_at)}\n"
        f"How long: {interview.duration_minutes} minutes\n"
        f"Where: {one_line(interview.location)}\n"
    )
    greeting = f"Hello {one_line(recipient.full_name)},\n\n"
    if is_candidate:
        intro = {
            "scheduled": f"An interview has been scheduled for your application for {title} at "
            f"{company_name}.\n\n",
            "rescheduled": f"Your interview for {title} at {company_name} has been "
            f"rescheduled. These are the new details.\n\n",
            "cancelled": f"Your interview for {title} at {company_name} has been cancelled.\n\n",
        }[kind]
        # Who the interviewers are stays internal: only when and where.
        closing = f"You can follow your applications here:\n{get_app_base_url()}/applications\n"
        subject = f"Interview {kind}: {title} at {company_name}"
    else:
        intro = {
            "scheduled": f"You have been asked to interview {candidate_name} for {title}.\n\n",
            "rescheduled": f"The interview with {candidate_name} for {title} has been "
            f"rescheduled. These are the new details.\n\n",
            "cancelled": f"The interview with {candidate_name} for {title} has been cancelled.\n\n",
        }[kind]
        closing = f"Your interviews are here:\n{get_app_base_url()}/interviews\n"
        subject = f"Interview {kind}: {candidate_name} for {title}"
    return Email(
        to=recipient.email, subject=subject, body=greeting + intro + details + "\n" + closing
    )


def render_interview_scheduled(db: Session, payload: dict[str, Any]) -> Email | None:
    return _render(db, payload, kind="scheduled")


def render_interview_rescheduled(db: Session, payload: dict[str, Any]) -> Email | None:
    return _render(db, payload, kind="rescheduled")


def render_interview_cancelled(db: Session, payload: dict[str, Any]) -> Email | None:
    return _render(db, payload, kind="cancelled")


def render_interview_unassigned(db: Session, payload: dict[str, Any]) -> Email | None:
    """Told to an interviewer who was taken off an interview. They are no longer a participant, so
    this is the one email that does not check for that: it checks they are an interviewer of the
    interview's company instead, and gives them nothing to open."""
    interview = db.get(Interview, uuid.UUID(payload["interview_id"]))
    if interview is None:
        return None
    application = db.get(Application, interview.application_id)
    recipient = db.get(User, uuid.UUID(payload["recipient_id"]))
    if application is None or recipient is None:
        return None
    if recipient.role != Role.INTERVIEWER or recipient.company_id != interview.company_id:
        return None
    job = db.get(Job, application.job_id)
    candidate = db.get(User, application.candidate_id)
    if job is None or candidate is None:
        return None

    title, candidate_name = one_line(job.title), one_line(candidate.full_name)
    body = (
        f"Hello {one_line(recipient.full_name)},\n\n"
        f"You are no longer assigned to the interview with {candidate_name} for {title} "
        f"({one_line(interview.round_name)}, {_utc(interview.scheduled_at)}). "
        f"Nothing more is needed from you for it.\n"
    )
    return Email(
        to=recipient.email,
        subject=f"Interview update: you are no longer assigned ({candidate_name}, {title})",
        body=body,
    )
