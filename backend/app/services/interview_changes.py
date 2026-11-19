"""What several services need when an interview changes: queue its emails, and cancel the
interviews of an application that has ended.

It sits below `interviews.py`, `pipeline.py` and `applications.py` (which all use it) and imports
none of them, so they can call it without importing each other in a circle.
"""

import uuid
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Application,
    Interview,
    InterviewParticipant,
    InterviewStatus,
    User,
)
from app.services.audit import record_audit
from app.worker.queue import enqueue


def participant_ids(db: Session, interview_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        db.scalars(
            select(InterviewParticipant.interviewer_id)
            .where(InterviewParticipant.interview_id == interview_id)
            .order_by(InterviewParticipant.assigned_at, InterviewParticipant.interviewer_id)
        )
    )


def active_among(db: Session, user_ids: Iterable[uuid.UUID]) -> list[uuid.UUID]:
    """Those of these users who can still act. A deactivated interviewer keeps their assignment
    but is not written to."""
    wanted = list(user_ids)
    if not wanted:
        return []
    active = set(db.scalars(select(User.id).where(User.id.in_(wanted), User.is_active.is_(True))))
    return [user_id for user_id in wanted if user_id in active]


def queue_interview_emails(
    db: Session,
    interview: Interview,
    template: str,
    *,
    interviewer_ids: Iterable[uuid.UUID],
    candidate_id: uuid.UUID | None,
    now: datetime,
) -> None:
    """One email to each of these interviewers who is still active, and one to the candidate if
    given, each with its own key."""
    recipients = active_among(db, interviewer_ids)
    if candidate_id is not None:
        recipients.append(candidate_id)
    for recipient_id in recipients:
        enqueue(
            db,
            type="send_email",
            payload={
                "template": template,
                "interview_id": str(interview.id),
                "recipient_id": str(recipient_id),
            },
            # The version is new with every change, so a later email is never mistaken for this one.
            idempotency_key=f"{template}:{interview.id}:{interview.version}:{recipient_id}",
            now=now,
        )


def cancel_scheduled_interviews(
    db: Session, actor: User, application: Application, now: datetime
) -> None:
    """Cancel every interview of this application that is still scheduled.

    Called inside the transaction that rejects or withdraws the application, with the application
    row already locked (the same order as scheduling: application first, then interviews). Only the
    interviewers are emailed: the candidate either did it themselves or already got the rejection.
    """
    interviews = db.scalars(
        select(Interview)
        .where(
            Interview.application_id == application.id,
            Interview.status == InterviewStatus.SCHEDULED,
        )
        .order_by(Interview.scheduled_at, Interview.id)
        .with_for_update()
    ).all()
    for interview in interviews:
        interview.status = InterviewStatus.CANCELLED
        interview.version += 1
        interview.updated_at = now
        record_audit(
            db,
            actor=actor,
            company_id=application.company_id,  # a candidate has none: file it under the job's
            action="interview.cancelled",
            entity_type="interview",
            entity_id=interview.id,
            old_value={"status": InterviewStatus.SCHEDULED.value},
            new_value={"status": InterviewStatus.CANCELLED.value},
            now=now,
        )
        queue_interview_emails(
            db,
            interview,
            "interview_cancelled",
            interviewer_ids=participant_ids(db, interview.id),
            candidate_id=None,
            now=now,
        )
