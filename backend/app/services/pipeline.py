"""What recruiters do with an application: read it, move it forward, reject it.

(The candidate's own side, applying, withdrawing and reactivating, is `services/applications.py`.)

Every function takes the current user and only reaches applications on jobs that user may see
(`visible_jobs_filter`: an admin the company's, a recruiter the ones assigned to them), so anything
else is "not found". Moves and rejections lock the application's row and compare the version the
person was looking at, so two people (or a person and the candidate) never overwrite each other.
Each change writes its history row, its audit row and the candidate's email in the same transaction;
the caller commits.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ACTIVE_STAGES,
    Application,
    ApplicationStage,
    ApplicationStageHistory,
    CandidateProfile,
    Job,
    RejectionReason,
    User,
)
from app.services.applications import record_stage_change
from app.services.errors import ApplicationNotActive, ApplicationVersionConflict, NotFoundError
from app.services.interview_changes import cancel_scheduled_interviews
from app.services.jobs import visible_jobs_filter
from app.worker.queue import enqueue

# The only way forward, one stage at a time. A stage that is not a key has nowhere to go.
NEXT_STAGE: dict[ApplicationStage, ApplicationStage] = {
    ApplicationStage.APPLIED: ApplicationStage.SCREENING,
    ApplicationStage.SCREENING: ApplicationStage.INTERVIEW,
    ApplicationStage.INTERVIEW: ApplicationStage.OFFER,
    ApplicationStage.OFFER: ApplicationStage.HIRED,
}


@dataclass
class HistoryEntry:
    from_stage: ApplicationStage | None
    to_stage: ApplicationStage
    changed_by_name: str
    changed_at: datetime


@dataclass
class ApplicationDetail:
    application: Application
    job_title: str
    candidate_name: str
    candidate_email: str
    candidate_phone: str | None
    candidate_location: str | None
    history: list[HistoryEntry]


def reachable_application(
    db: Session, user: User, application_id: uuid.UUID, *, lock: bool
) -> Application:
    statement = (
        select(Application)
        .join(Job, Job.id == Application.job_id)
        .where(Application.id == application_id, *visible_jobs_filter(user))
    )
    if lock:
        # populate_existing: if the row was loaded earlier in this session, take the values the
        # other transaction has just committed, not the stale copy.
        statement = statement.with_for_update(of=Application).execution_options(
            populate_existing=True
        )
    application = db.scalar(statement)
    if application is None:
        raise NotFoundError
    return application


def get_application_detail(db: Session, user: User, application_id: uuid.UUID) -> ApplicationDetail:
    application = reachable_application(db, user, application_id, lock=False)
    job = db.get(Job, application.job_id)
    candidate = db.get(User, application.candidate_id)
    assert job is not None and candidate is not None  # foreign keys guarantee both
    profile = db.get(CandidateProfile, candidate.id)
    rows = db.execute(
        select(ApplicationStageHistory, User.full_name)
        .join(User, User.id == ApplicationStageHistory.changed_by)
        .where(ApplicationStageHistory.application_id == application.id)
        .order_by(ApplicationStageHistory.changed_at, ApplicationStageHistory.id)
    )
    history = [
        HistoryEntry(row.from_stage, row.to_stage, name, row.changed_at) for row, name in rows
    ]
    return ApplicationDetail(
        application=application,
        job_title=job.title,
        candidate_name=candidate.full_name,
        candidate_email=candidate.email,
        candidate_phone=profile.phone if profile else None,
        candidate_location=profile.location if profile else None,
        history=history,
    )


def _lock_for_decision(
    db: Session, user: User, application_id: uuid.UUID, version: int
) -> Application:
    """The application, locked, if the person is looking at its latest version and it is in play."""
    application = reachable_application(db, user, application_id, lock=True)
    if application.version != version:
        raise ApplicationVersionConflict
    if application.stage not in ACTIVE_STAGES:
        raise ApplicationNotActive
    return application


def advance_application(
    db: Session, user: User, application_id: uuid.UUID, version: int, now: datetime
) -> Application:
    """Move forward one stage. The request never names the stage: the rule above decides it."""
    application = _lock_for_decision(db, user, application_id, version)
    old_stage = application.stage
    application.stage = NEXT_STAGE[old_stage]
    application.version += 1
    application.updated_at = now
    record_stage_change(
        db, user, application, action="application.stage_changed", old_stage=old_stage, now=now
    )
    enqueue(
        db,
        type="send_email",
        payload={
            "template": "application_stage_changed",
            "application_id": str(application.id),
            "stage": application.stage.value,
        },
        # One email per change: the version is new with every change.
        idempotency_key=f"application_stage:{application.id}:{application.version}",
        now=now,
    )
    db.flush()
    return application


def reject_application(
    db: Session,
    user: User,
    application_id: uuid.UUID,
    version: int,
    reason: RejectionReason,
    comment: str | None,
    now: datetime,
) -> Application:
    """Reject from any stage still in play. The reason and comment stay internal."""
    application = _lock_for_decision(db, user, application_id, version)
    old_stage = application.stage
    application.rejected_from_stage = old_stage
    application.rejection_reason = reason
    application.rejection_comment = comment
    application.stage = ApplicationStage.REJECTED
    application.version += 1
    application.updated_at = now
    record_stage_change(
        db,
        user,
        application,
        action="application.rejected",
        old_stage=old_stage,
        now=now,
        # The category only. The comment is free text about a person: it lives on the application
        # and nowhere else.
        also_audit={"reason": reason.value},
    )
    cancel_scheduled_interviews(db, user, application, now)  # its interviews end with it
    enqueue(
        db,
        type="send_email",
        # No reason in the payload either: the email is the same kind message whatever it was.
        payload={"template": "application_rejected", "application_id": str(application.id)},
        idempotency_key=f"application_rejected:{application.id}",
        now=now,
    )
    db.flush()
    return application
