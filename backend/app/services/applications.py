"""A candidate's applications: applying, withdrawing, reactivating, and the list they see.

Every function takes the candidate and only ever touches rows with their id on them, so another
candidate's application is "not found", never "forbidden". Each change writes its history row, its
audit row and (for applying) the queued email in the same transaction; the caller commits.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.integrations import storage
from app.models import (
    ACTIVE_STAGES,
    Application,
    ApplicationStage,
    ApplicationStageHistory,
    CandidateProfile,
    Company,
    File,
    Job,
    PostingStatus,
    User,
)
from app.pagination import PageRequest
from app.services.audit import record_audit
from app.services.errors import (
    ApplicationEnded,
    CannotReactivate,
    JobNotOpen,
    NotFoundError,
    ResumeRequired,
)
from app.services.interview_changes import cancel_scheduled_interviews
from app.services.jobs import get_job, visible_jobs_filter
from app.worker.queue import enqueue

logger = logging.getLogger(__name__)

# The unique constraint on (candidate_id, job_id): a clash on it means "already applied".
DUPLICATE_APPLICATION = "uq_applications_candidate_job"


@dataclass
class ApplyResult:
    application: Application
    created: bool  # False when the candidate had already applied and this is that application


@dataclass
class ApplicationView:
    """An application as the candidate sees it: with the job and company it is for."""

    application: Application
    job_title: str
    company_name: str
    job_is_open: bool


def _is_duplicate(error: IntegrityError) -> bool:
    diagnostics = getattr(error.orig, "diag", None)
    return getattr(diagnostics, "constraint_name", None) == DUPLICATE_APPLICATION


def _own_application_for_job(db: Session, candidate: User, job_id: uuid.UUID) -> Application | None:
    return db.scalar(
        select(Application).where(
            Application.candidate_id == candidate.id, Application.job_id == job_id
        )
    )


def _resume_to_apply_with(db: Session, candidate: User) -> uuid.UUID:
    """The id of the resume on file, which this application will snapshot."""
    profile = db.get(CandidateProfile, candidate.id)
    if profile is None or profile.current_resume_file_id is None:
        raise ResumeRequired
    file = db.get(File, profile.current_resume_file_id)
    if file is None or file.deleted_at is not None:
        raise ResumeRequired
    return file.id


def record_stage_change(
    db: Session,
    actor: User,
    application: Application,
    *,
    action: str,
    old_stage: ApplicationStage | None,
    now: datetime,
    also_audit: dict[str, str] | None = None,
) -> None:
    """The history row and the audit row for a change that has just been made.

    `actor` is whoever made it: the candidate, or a recruiter. `also_audit` adds fields to the audit
    row's new value (the rejection's reason category), never free text.
    """
    db.add(
        ApplicationStageHistory(
            application_id=application.id,
            from_stage=old_stage,
            to_stage=application.stage,
            changed_by=actor.id,
            changed_at=now,
        )
    )
    record_audit(
        db,
        actor=actor,
        company_id=application.company_id,  # a candidate has none: file it under the job's company
        action=action,
        entity_type="application",
        entity_id=application.id,
        old_value=None if old_stage is None else {"stage": old_stage.value},
        new_value={"stage": application.stage.value, **(also_audit or {})},
        now=now,
    )


def apply_to_job(db: Session, candidate: User, job_id: uuid.UUID, now: datetime) -> ApplyResult:
    """Apply to an open job with the resume on file.

    Applying again returns the existing application (a double click or a retry is not an error).
    A draft or unknown job is "not found"; a closed one is `JobNotOpen`; no resume is
    `ResumeRequired`.
    """
    existing = _own_application_for_job(db, candidate, job_id)
    if existing is not None:
        return ApplyResult(existing, created=False)

    job = db.get(Job, job_id)
    if job is None or job.status == PostingStatus.DRAFT:
        raise NotFoundError  # a draft must look exactly like a job that does not exist
    if job.status != PostingStatus.OPEN:
        raise JobNotOpen
    resume_id = _resume_to_apply_with(db, candidate)

    application = Application(
        job_id=job.id,
        company_id=job.company_id,
        candidate_id=candidate.id,
        resume_file_id=resume_id,
        stage=ApplicationStage.APPLIED,
        created_at=now,
        updated_at=now,
    )
    try:
        # A savepoint, so losing a race to the unique constraint does not poison the transaction.
        with db.begin_nested():
            db.add(application)
            db.flush()
    except IntegrityError as error:
        if not _is_duplicate(error):
            raise
        winner = _own_application_for_job(db, candidate, job_id)
        if winner is None:
            raise
        return ApplyResult(winner, created=False)

    record_stage_change(
        db, candidate, application, action="application.created", old_stage=None, now=now
    )
    enqueue(
        db,
        type="send_email",
        payload={"template": "application_received", "application_id": str(application.id)},
        idempotency_key=f"application_received:{application.id}",
        now=now,
    )
    db.flush()
    return ApplyResult(application, created=True)


def _own_application_locked(db: Session, candidate: User, application_id: uuid.UUID) -> Application:
    """The candidate's own application, row-locked so two changes to it take turns."""
    application = db.scalar(
        select(Application)
        .where(Application.id == application_id, Application.candidate_id == candidate.id)
        .with_for_update(of=Application)
        .execution_options(populate_existing=True)
    )
    if application is None:
        raise NotFoundError
    return application


def withdraw_application(
    db: Session, candidate: User, application_id: uuid.UUID, now: datetime
) -> Application:
    """Withdraw from any stage that has not ended. Withdrawing again changes nothing."""
    application = _own_application_locked(db, candidate, application_id)
    if application.stage == ApplicationStage.WITHDRAWN:
        return application
    if application.stage not in ACTIVE_STAGES:
        raise ApplicationEnded

    old_stage = application.stage
    application.stage_before_withdrawal = old_stage  # so reactivating can put it back
    application.stage = ApplicationStage.WITHDRAWN
    application.version += 1
    application.updated_at = now
    record_stage_change(
        db, candidate, application, action="application.withdrawn", old_stage=old_stage, now=now
    )
    cancel_scheduled_interviews(db, candidate, application, now)  # its interviews end with it
    db.flush()
    return application


def reactivate_application(
    db: Session, candidate: User, application_id: uuid.UUID, now: datetime
) -> Application:
    """Put a withdrawn application back where it was, while its job is still open."""
    application = _own_application_locked(db, candidate, application_id)
    if application.stage in (ApplicationStage.HIRED, ApplicationStage.REJECTED):
        raise CannotReactivate
    if application.stage != ApplicationStage.WITHDRAWN:
        return application  # already active: nothing to do
    job = db.get(Job, application.job_id)
    if job is None or job.status != PostingStatus.OPEN:
        raise JobNotOpen
    restored = application.stage_before_withdrawal
    assert restored is not None  # the database guarantees it while an application is withdrawn

    application.stage = restored
    application.stage_before_withdrawal = None
    application.version += 1
    application.updated_at = now
    record_stage_change(
        db,
        candidate,
        application,
        action="application.reactivated",
        old_stage=ApplicationStage.WITHDRAWN,
        now=now,
    )
    db.flush()
    return application


def _view_query() -> Select[Application, str, str, PostingStatus]:
    return (
        select(Application, Job.title, Company.name, Job.status)
        .join(Job, Job.id == Application.job_id)
        .join(Company, Company.id == Application.company_id)
    )


def application_view(db: Session, candidate: User, application_id: uuid.UUID) -> ApplicationView:
    """One of the candidate's own applications, with its job and company."""
    row = db.execute(
        _view_query().where(
            Application.id == application_id, Application.candidate_id == candidate.id
        )
    ).first()
    if row is None:
        raise NotFoundError
    application, title, company_name, job_status = row
    return ApplicationView(application, title, company_name, job_status == PostingStatus.OPEN)


def list_my_applications(
    db: Session, candidate: User, page: PageRequest, *, job_id: uuid.UUID | None = None
) -> tuple[list[ApplicationView], int]:
    """One page of the candidate's own applications, newest first, and how many there are.

    With `job_id`, only the application to that job (the job page asks whether you applied).
    """
    wanted = [Application.candidate_id == candidate.id]
    if job_id is not None:
        wanted.append(Application.job_id == job_id)
    total = db.scalar(select(func.count()).select_from(Application).where(*wanted)) or 0
    rows = db.execute(
        _view_query()
        .where(*wanted)
        # The id breaks ties, so a page never repeats or skips a row between requests.
        .order_by(Application.created_at.desc(), Application.id)
        .limit(page.page_size)
        .offset(page.offset)
    )
    views = [
        ApplicationView(application, title, company_name, job_status == PostingStatus.OPEN)
        for application, title, company_name, job_status in rows
    ]
    return views, total


# ---- what staff see ------------------------------------------------------------------------


@dataclass
class Applicant:
    """One application on a job, with who made it. For staff; a candidate never gets this."""

    application: Application
    candidate_name: str
    candidate_email: str


def list_job_applications(
    db: Session, user: User, job_id: uuid.UUID, page: PageRequest
) -> tuple[list[Applicant], int]:
    """One page of the applications on a job this user may see, newest first, and the total.

    A job outside the user's reach (another company's, or a recruiter's unassigned one) is
    "not found", the same as a job that does not exist.
    """
    job = get_job(db, user, job_id)
    total = (
        db.scalar(select(func.count()).select_from(Application).where(Application.job_id == job.id))
        or 0
    )
    rows = db.execute(
        select(Application, User.full_name, User.email)
        .join(User, User.id == Application.candidate_id)
        .where(Application.job_id == job.id)
        # The id breaks ties, so a page never repeats or skips a row between requests.
        .order_by(Application.created_at.desc(), Application.id)
        .limit(page.page_size)
        .offset(page.offset)
    )
    applicants = [Applicant(application, name, email) for application, name, email in rows]
    return applicants, total


def open_application_resume(
    db: Session, user: User, application_id: uuid.UUID
) -> tuple[File, storage.StoredObject]:
    """The record and the bytes of the resume an application was made with.

    That is the snapshot taken when the candidate applied, not their current resume. The
    application must be on a job this user may see: the same job rule as the list above.
    """
    application = db.scalar(
        select(Application)
        .join(Job, Job.id == Application.job_id)
        .where(Application.id == application_id, *visible_jobs_filter(user))
    )
    if application is None:
        raise NotFoundError
    file = db.get(File, application.resume_file_id)
    if file is None:
        raise NotFoundError
    try:
        return file, storage.open_object(file.storage_key)
    except storage.ObjectNotFound as error:
        logger.error("An application's resume record points at an object that is not in storage")
        raise NotFoundError from error
