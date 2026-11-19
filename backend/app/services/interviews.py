"""Scheduling and cancelling interviews (functional.md > Schedule an interview).

Staff reach an interview only through its application, and an application only on a job they may
see (`visible_jobs_filter`), so anything else is "not found". Scheduling locks the application row
(so it cannot race a rejection) and changing an interview locks the interview row and compares the
version the person was looking at. Each change writes its audit row and queues its emails in the
same transaction; the caller commits and the worker sends.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Application,
    ApplicationStage,
    Interview,
    InterviewParticipant,
    InterviewStatus,
    Job,
    Role,
    User,
)
from app.services.audit import record_audit
from app.services.errors import (
    InterviewInThePast,
    InterviewNotScheduled,
    InterviewVersionConflict,
    InvalidInterviewer,
    NotFoundError,
    NotInInterviewStage,
)
from app.services.jobs import visible_jobs_filter
from app.services.pipeline import reachable_application
from app.worker.queue import enqueue


@dataclass
class InterviewView:
    interview: Interview
    # (user id, full name, still active), in the order they were assigned.
    participants: list[tuple[uuid.UUID, str, bool]]

    @property
    def needs_reassignment(self) -> bool:
        # Only a scheduled interview still needs its people: a cancelled one is over.
        return self.interview.status == InterviewStatus.SCHEDULED and any(
            not active for _id, _name, active in self.participants
        )


def reachable_interview(
    db: Session, user: User, interview_id: uuid.UUID, *, lock: bool
) -> Interview:
    statement = (
        select(Interview)
        .join(Application, Application.id == Interview.application_id)
        .join(Job, Job.id == Application.job_id)
        .where(Interview.id == interview_id, *visible_jobs_filter(user))
    )
    if lock:
        # populate_existing: take what another transaction has just committed, not a stale copy.
        statement = statement.with_for_update(of=Interview).execution_options(
            populate_existing=True
        )
    interview = db.scalar(statement)
    if interview is None:
        raise NotFoundError
    return interview


def interview_view(db: Session, interview: Interview) -> InterviewView:
    rows = db.execute(
        select(User.id, User.full_name, User.is_active)
        .join(InterviewParticipant, InterviewParticipant.interviewer_id == User.id)
        .where(InterviewParticipant.interview_id == interview.id)
        .order_by(InterviewParticipant.assigned_at, User.full_name, User.id)
    )
    return InterviewView(interview, [(row.id, row.full_name, row.is_active) for row in rows])


def list_interviews(db: Session, user: User, application_id: uuid.UUID) -> list[InterviewView]:
    """The interviews of an application the user may see, in time order."""
    application = reachable_application(db, user, application_id, lock=False)
    interviews = db.scalars(
        select(Interview)
        .where(Interview.application_id == application.id)
        .order_by(Interview.scheduled_at, Interview.id)
    )
    return [interview_view(db, interview) for interview in interviews]


def _queue_emails(
    db: Session,
    interview: Interview,
    template: str,
    *,
    candidate_id: uuid.UUID,
    now: datetime,
) -> None:
    """One email to each interviewer and one to the candidate, each with its own key."""
    interviewer_ids = db.scalars(
        select(InterviewParticipant.interviewer_id).where(
            InterviewParticipant.interview_id == interview.id
        )
    )
    for recipient_id in [*interviewer_ids, candidate_id]:
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


def schedule_interview(
    db: Session,
    user: User,
    application_id: uuid.UUID,
    *,
    round_name: str,
    scheduled_at: datetime,
    duration_minutes: int,
    location: str,
    interviewer_ids: list[uuid.UUID],
    now: datetime,
) -> Interview:
    application = reachable_application(db, user, application_id, lock=True)
    if application.stage != ApplicationStage.INTERVIEW:
        raise NotInInterviewStage
    if scheduled_at <= now:
        raise InterviewInThePast
    found = db.scalars(
        select(User.id).where(
            User.id.in_(interviewer_ids),
            User.company_id == application.company_id,
            User.role == Role.INTERVIEWER,
            User.is_active.is_(True),
        )
    ).all()
    if len(found) != len(interviewer_ids):
        raise InvalidInterviewer

    interview = Interview(
        company_id=application.company_id,
        application_id=application.id,
        round_name=round_name,
        scheduled_at=scheduled_at,
        duration_minutes=duration_minutes,
        location=location,
        scheduled_by=user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(interview)
    db.flush()
    for interviewer_id in interviewer_ids:
        db.add(
            InterviewParticipant(
                interview_id=interview.id, interviewer_id=interviewer_id, assigned_at=now
            )
        )
    db.flush()
    record_audit(
        db,
        actor=user,
        action="interview.scheduled",
        entity_type="interview",
        entity_id=interview.id,
        old_value=None,
        new_value={"application_id": str(application.id)},
        now=now,
    )
    _queue_emails(
        db, interview, "interview_scheduled", candidate_id=application.candidate_id, now=now
    )
    db.flush()
    return interview


def cancel_interview(
    db: Session, user: User, interview_id: uuid.UUID, version: int, now: datetime
) -> Interview:
    interview = reachable_interview(db, user, interview_id, lock=True)
    if interview.version != version:
        raise InterviewVersionConflict
    if interview.status != InterviewStatus.SCHEDULED:
        raise InterviewNotScheduled
    interview.status = InterviewStatus.CANCELLED
    interview.version += 1
    interview.updated_at = now
    record_audit(
        db,
        actor=user,
        action="interview.cancelled",
        entity_type="interview",
        entity_id=interview.id,
        old_value={"status": InterviewStatus.SCHEDULED.value},
        new_value={"status": InterviewStatus.CANCELLED.value},
        now=now,
    )
    application = db.get(Application, interview.application_id)
    assert application is not None  # the foreign key guarantees it
    _queue_emails(
        db, interview, "interview_cancelled", candidate_id=application.candidate_id, now=now
    )
    db.flush()
    return interview
