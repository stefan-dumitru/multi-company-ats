"""The interviewer's side: their interviews, the candidate, and blind scoring.

An interviewer reaches an interview only through their own `InterviewParticipant` row, so every
other interview is "not found". **Blind scoring is decided here, in the query**: other
interviewers' scorecards are fetched only after the caller has a scorecard of their own, whatever
the request says. Submitting locks the interview row, so it takes turns with a cancel, a
participant change and another interviewer's submit; the caller commits.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session, aliased

from app.integrations import storage
from app.models import (
    Application,
    CandidateProfile,
    File,
    Interview,
    InterviewParticipant,
    InterviewStatus,
    Job,
    Scorecard,
    User,
)
from app.pagination import PageRequest
from app.schemas.scorecards import InterviewFilter
from app.services.audit import record_audit
from app.services.errors import InterviewNotScheduled, NotFoundError, ScorecardAlreadySubmitted
from app.services.interviews import reachable_interview


@dataclass
class MyInterviewRow:
    interview: Interview
    job_title: str
    candidate_name: str | None
    my_scorecard_submitted: bool


@dataclass
class CandidateInfo:
    name: str
    email: str
    phone: str | None
    location: str | None


@dataclass
class MyInterviewDetail:
    interview: Interview
    job_title: str
    candidate: CandidateInfo | None
    my_scorecard: tuple[Scorecard, str] | None
    others: list[tuple[Scorecard, str]]


def _assigned_interview(
    db: Session, user: User, interview_id: uuid.UUID, *, lock: bool
) -> Interview:
    """The interview, if (and only if) this user is assigned to it."""
    statement = (
        select(Interview)
        .join(InterviewParticipant, InterviewParticipant.interview_id == Interview.id)
        .where(
            Interview.id == interview_id,
            InterviewParticipant.interviewer_id == user.id,
            Interview.company_id == user.company_id,
        )
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


def list_my_interviews(
    db: Session, user: User, page: PageRequest, which: InterviewFilter, now: datetime
) -> tuple[list[MyInterviewRow], int]:
    mine = exists().where(
        Scorecard.interview_id == Interview.id, Scorecard.interviewer_id == user.id
    )
    candidate = aliased(User)
    wanted = [InterviewParticipant.interviewer_id == user.id]
    if which == InterviewFilter.UPCOMING:
        wanted += [Interview.status == InterviewStatus.SCHEDULED, Interview.scheduled_at > now]
    elif which == InterviewFilter.AWAITING:
        wanted += [
            Interview.status == InterviewStatus.SCHEDULED,
            Interview.scheduled_at <= now,
            ~mine,
        ]
    base = (
        select(Interview, Job.title, candidate.full_name, mine)
        .join(InterviewParticipant, InterviewParticipant.interview_id == Interview.id)
        .join(Application, Application.id == Interview.application_id)
        .join(Job, Job.id == Application.job_id)
        .join(candidate, candidate.id == Application.candidate_id)
        .where(*wanted)
    )
    total = (
        db.scalar(
            select(func.count())
            .select_from(Interview)
            .join(InterviewParticipant, InterviewParticipant.interview_id == Interview.id)
            .where(*wanted)
        )
        or 0
    )
    # What is coming (or overdue) is read soonest-first; the full history newest-first.
    order = (
        (Interview.scheduled_at.desc(), Interview.id)
        if which == InterviewFilter.ALL
        else (Interview.scheduled_at, Interview.id)
    )
    rows = db.execute(base.order_by(*order).limit(page.page_size).offset(page.offset))
    return [
        MyInterviewRow(
            interview,
            title,
            None if interview.status == InterviewStatus.CANCELLED else name,
            bool(submitted),
        )
        for interview, title, name, submitted in rows
    ], total


def _scorecards_with_names(
    db: Session, interview_id: uuid.UUID, *, excluding: uuid.UUID | None = None
) -> list[tuple[Scorecard, str]]:
    statement = (
        select(Scorecard, User.full_name)
        .join(User, User.id == Scorecard.interviewer_id)
        .where(Scorecard.interview_id == interview_id)
        .order_by(Scorecard.submitted_at, Scorecard.id)
    )
    if excluding is not None:
        statement = statement.where(Scorecard.interviewer_id != excluding)
    return [(scorecard, name) for scorecard, name in db.execute(statement)]


def my_interview_detail(db: Session, user: User, interview_id: uuid.UUID) -> MyInterviewDetail:
    interview = _assigned_interview(db, user, interview_id, lock=False)
    application = db.get(Application, interview.application_id)
    job = db.get(Job, application.job_id) if application else None
    assert application is not None and job is not None  # foreign keys guarantee both

    candidate_info = None
    if interview.status != InterviewStatus.CANCELLED:
        candidate = db.get(User, application.candidate_id)
        profile = db.get(CandidateProfile, application.candidate_id)
        assert candidate is not None
        candidate_info = CandidateInfo(
            name=candidate.full_name,
            email=candidate.email,
            phone=profile.phone if profile else None,
            location=profile.location if profile else None,
        )

    own = db.execute(
        select(Scorecard, User.full_name)
        .join(User, User.id == Scorecard.interviewer_id)
        .where(Scorecard.interview_id == interview.id, Scorecard.interviewer_id == user.id)
    ).first()
    my_scorecard = (own[0], own[1]) if own is not None else None
    # BLIND SCORING: colleagues' scorecards are fetched only once the caller has submitted theirs.
    others = _scorecards_with_names(db, interview.id, excluding=user.id) if my_scorecard else []
    return MyInterviewDetail(interview, job.title, candidate_info, my_scorecard, others)


def open_my_interview_resume(
    db: Session, user: User, interview_id: uuid.UUID
) -> tuple[File, storage.StoredObject]:
    """The resume the candidate applied with, for an interview the caller is assigned to. Not once
    the interview is cancelled: the candidate may have been rejected or have withdrawn."""
    interview = _assigned_interview(db, user, interview_id, lock=False)
    if interview.status == InterviewStatus.CANCELLED:
        raise NotFoundError
    application = db.get(Application, interview.application_id)
    assert application is not None
    file = db.get(File, application.resume_file_id)
    if file is None:
        raise NotFoundError
    try:
        return file, storage.open_object(file.storage_key)
    except storage.ObjectNotFound as error:
        raise NotFoundError from error


def submit_scorecard(
    db: Session, user: User, interview_id: uuid.UUID, data: dict[str, Any], now: datetime
) -> tuple[Scorecard, str]:
    """Submit the caller's one scorecard for this interview. Final: there is no way to change it."""
    interview = _assigned_interview(db, user, interview_id, lock=True)
    already = db.scalar(
        select(Scorecard.id).where(
            Scorecard.interview_id == interview.id, Scorecard.interviewer_id == user.id
        )
    )
    if already is not None:
        raise ScorecardAlreadySubmitted
    if interview.status != InterviewStatus.SCHEDULED:
        raise InterviewNotScheduled

    scorecard = Scorecard(
        interview_id=interview.id, interviewer_id=user.id, submitted_at=now, **data
    )
    db.add(scorecard)
    db.flush()
    record_audit(
        db,
        actor=user,
        action="scorecard.submitted",
        entity_type="scorecard",
        entity_id=scorecard.id,
        old_value=None,
        # Which interview, never what was said or how it was rated.
        new_value={"interview_id": str(interview.id)},
        now=now,
    )
    _complete_if_everyone_has_scored(db, user, interview, now)
    return scorecard, user.full_name


def _complete_if_everyone_has_scored(
    db: Session, user: User, interview: Interview, now: datetime
) -> None:
    """Every active interviewer has submitted: the interview is done. A deactivated interviewer
    does not hold it open."""
    waiting = db.scalar(
        select(func.count())
        .select_from(InterviewParticipant)
        .join(User, User.id == InterviewParticipant.interviewer_id)
        .where(
            InterviewParticipant.interview_id == interview.id,
            User.is_active.is_(True),
            ~exists().where(
                Scorecard.interview_id == interview.id,
                Scorecard.interviewer_id == InterviewParticipant.interviewer_id,
            ),
        )
    )
    if waiting:
        return
    interview.status = InterviewStatus.COMPLETED
    interview.version += 1
    interview.updated_at = now
    record_audit(
        db,
        actor=user,
        action="interview.completed",
        entity_type="interview",
        entity_id=interview.id,
        old_value={"status": InterviewStatus.SCHEDULED.value},
        new_value={"status": InterviewStatus.COMPLETED.value},
        now=now,
    )
    db.flush()


def list_interview_scorecards(
    db: Session, user: User, interview_id: uuid.UUID
) -> list[tuple[Scorecard, str]]:
    """Every submitted scorecard of an interview, for staff who may see its application:
    recruiters and admins read each one as soon as it is submitted."""
    interview = reachable_interview(db, user, interview_id, lock=False)
    return _scorecards_with_names(db, interview.id)
