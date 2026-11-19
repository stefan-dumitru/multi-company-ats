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
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    Application,
    ApplicationStage,
    Interview,
    InterviewParticipant,
    InterviewStatus,
    Job,
    Role,
    Scorecard,
    User,
)
from app.services.audit import record_audit
from app.services.errors import (
    InterviewerHasScored,
    InterviewInThePast,
    InterviewNotScheduled,
    InterviewVersionConflict,
    InvalidInterviewer,
    NotFoundError,
    NotInInterviewStage,
)
from app.services.interview_changes import participant_ids, queue_interview_emails
from app.services.jobs import visible_jobs_filter
from app.services.pipeline import reachable_application


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


def require_active_interviewers(
    db: Session, company_id: uuid.UUID, interviewer_ids: list[uuid.UUID]
) -> None:
    """Every one of these must be an active interviewer of this company: one answer otherwise."""
    found = db.scalars(
        select(User.id).where(
            User.id.in_(interviewer_ids),
            User.company_id == company_id,
            User.role == Role.INTERVIEWER,
            User.is_active.is_(True),
        )
    ).all()
    if len(found) != len(set(interviewer_ids)):
        raise InvalidInterviewer


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
    require_active_interviewers(db, application.company_id, interviewer_ids)

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
    queue_interview_emails(
        db,
        interview,
        "interview_scheduled",
        interviewer_ids=interviewer_ids,
        candidate_id=application.candidate_id,
        now=now,
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
    queue_interview_emails(
        db,
        interview,
        "interview_cancelled",
        interviewer_ids=participant_ids(db, interview.id),
        candidate_id=application.candidate_id,
        now=now,
    )
    db.flush()
    return interview


# The fields of an interview a recruiter may change, in the order they are reported.
EDITABLE_FIELDS = ("round_name", "scheduled_at", "duration_minutes", "location")


def update_interview(
    db: Session,
    user: User,
    interview_id: uuid.UUID,
    version: int,
    changes: dict[str, Any],
    now: datetime,
) -> Interview:
    """Reschedule an interview and/or change who interviews. Sending what it already has changes
    nothing (no new version, no audit row, no email).

    Interviewers already assigned may stay even if they were deactivated since; only people being
    added must be active interviewers of the company. (Removing an interviewer who has already
    submitted a scorecard is refused once scorecards exist: the next step.)
    """
    interview = reachable_interview(db, user, interview_id, lock=True)
    if interview.version != version:
        raise InterviewVersionConflict
    if interview.status != InterviewStatus.SCHEDULED:
        raise InterviewNotScheduled

    changed = [
        field
        for field in EDITABLE_FIELDS
        if field in changes and changes[field] != getattr(interview, field)
    ]
    if "scheduled_at" in changed and changes["scheduled_at"] <= now:
        raise InterviewInThePast

    current = participant_ids(db, interview.id)
    wanted = list(changes["interviewer_ids"]) if "interviewer_ids" in changes else current
    added = [person for person in wanted if person not in current]
    removed = [person for person in current if person not in wanted]
    if added:
        require_active_interviewers(db, interview.company_id, added)
    if not changed and not added and not removed:
        return interview
    if removed:
        scored = db.scalar(
            select(Scorecard.interviewer_id).where(
                Scorecard.interview_id == interview.id, Scorecard.interviewer_id.in_(removed)
            )
        )
        if scored is not None:
            raise InterviewerHasScored

    for field in changed:
        setattr(interview, field, changes[field])
    for person in added:
        db.add(
            InterviewParticipant(interview_id=interview.id, interviewer_id=person, assigned_at=now)
        )
    if removed:
        db.execute(
            delete(InterviewParticipant).where(
                InterviewParticipant.interview_id == interview.id,
                InterviewParticipant.interviewer_id.in_(removed),
            )
        )
    interview.version += 1
    interview.updated_at = now
    db.flush()
    record_audit(
        db,
        actor=user,
        action="interview.updated",
        entity_type="interview",
        entity_id=interview.id,
        old_value=None,
        # Which parts changed, never their values: a location or a name is about a person.
        new_value={"changed": [*changed, *(["interviewers"] if added or removed else [])]},
        now=now,
    )
    application = db.get(Application, interview.application_id)
    assert application is not None  # the foreign key guarantees it
    if changed:  # the time, place or round moved: everyone who stays is told
        queue_interview_emails(
            db,
            interview,
            "interview_rescheduled",
            interviewer_ids=[person for person in wanted if person in current],
            candidate_id=application.candidate_id,
            now=now,
        )
    if added:
        queue_interview_emails(
            db, interview, "interview_scheduled", interviewer_ids=added, candidate_id=None, now=now
        )
    if removed:
        queue_interview_emails(
            db,
            interview,
            "interview_unassigned",
            interviewer_ids=removed,
            candidate_id=None,
            now=now,
        )
    db.flush()
    return interview
