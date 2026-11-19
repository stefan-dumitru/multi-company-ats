"""Scorecards submitted at the same moment as something else.

Needs two real database sessions (like test_interviews_update_race.py). The first does its work but
does not commit, so it holds the interview's row lock; the second waits, then finds what the first
did and acts on it instead of on stale facts.
"""

import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.models import (
    ApplicationStage,
    AuditLog,
    Interview,
    InterviewStatus,
    PostingStatus,
    Role,
    Scorecard,
    User,
)
from app.services import interviews as interviews_service
from app.services import scorecards as scorecards_service
from app.services.errors import InterviewNotScheduled, ScorecardAlreadySubmitted
from tests.factories import (
    make_application,
    make_candidate,
    make_company,
    make_department,
    make_interview,
    make_job,
    make_user,
)

SUBMISSION = {
    "overall_rating": 4,
    "technical_rating": 4,
    "communication_rating": 4,
    "problem_solving_rating": 4,
    "culture_fit_rating": 4,
    "feedback": "Fine.",
    "recommendation": "yes",
}


def build(db: Session) -> tuple[Interview, User, User, User]:
    company = make_company(db)
    admin = make_user(db, email="admin@acme.test", role=Role.COMPANY_ADMIN, company=company)
    recruiter = make_user(db, email="rec@acme.test", role=Role.RECRUITER, company=company)
    ivy = make_user(db, email="ivy@acme.test", role=Role.INTERVIEWER, company=company)
    ian = make_user(db, email="ian@acme.test", role=Role.INTERVIEWER, company=company)
    job = make_job(
        db,
        company=company,
        department=make_department(db, company),
        created_by=admin,
        recruiters=[recruiter],
        status=PostingStatus.OPEN,
    )
    application = make_application(
        db,
        job=job,
        candidate=make_candidate(db, email="cara@example.test"),
        stage=ApplicationStage.INTERVIEW,
    )
    interview = make_interview(
        db, application=application, scheduled_by=recruiter, interviewers=[ivy, ian]
    )
    db.commit()
    return interview, recruiter, ivy, ian


def submit_as(session: Session, user_id: uuid.UUID, interview_id: uuid.UUID) -> None:
    person = session.get(User, user_id)
    assert person is not None
    scorecards_service.submit_scorecard(
        session,
        person,
        interview_id,
        dict(SUBMISSION),
        datetime.now(UTC),
    )


def hold_then_release(
    scratch_engine: Engine,
    first_does: Callable[[Session], None],
    second_does: Callable[[Session], None],
    refused: tuple[type[Exception], ...],
) -> str:
    """Run first_does without committing, start second_does in another session, check that it
    waits, commit the first, and say what became of the second."""
    outcome: dict[str, str] = {}
    first, second = Session(scratch_engine), Session(scratch_engine)
    try:
        first_does(first)

        def other() -> None:
            try:
                second_does(second)
                second.commit()
                outcome["result"] = "applied"
            except refused:
                second.rollback()
                outcome["result"] = "refused"

        thread = threading.Thread(target=other)
        thread.start()
        time.sleep(1.0)
        assert thread.is_alive(), "the second action did not wait for the first one"
        first.commit()
        thread.join(timeout=10)
        assert not thread.is_alive()
    finally:
        first.close()
        second.close()
    return outcome["result"]


def test_two_interviewers_submitting_together_complete_the_interview_exactly_once(
    db: Session, scratch_engine: Engine
) -> None:
    interview, _recruiter, ivy, ian = build(db)
    interview_id, ivy_id, ian_id = interview.id, ivy.id, ian.id

    result = hold_then_release(
        scratch_engine,
        lambda session: submit_as(session, ivy_id, interview_id),
        lambda session: submit_as(session, ian_id, interview_id),
        (ScorecardAlreadySubmitted,),
    )

    assert result == "applied"  # both go through: they are different people
    with Session(scratch_engine) as check:
        stored = check.get(Interview, interview_id)
        assert stored is not None and stored.status == InterviewStatus.COMPLETED
        assert (check.scalar(select(func.count()).select_from(Scorecard)) or 0) == 2
        completions = check.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "interview.completed")
        )
        assert completions == 1  # the second saw the first's scorecard, so only it completed


def test_the_same_interviewer_submitting_twice_at_once_scores_once(
    db: Session, scratch_engine: Engine
) -> None:
    interview, _recruiter, ivy, _ian = build(db)
    interview_id, ivy_id = interview.id, ivy.id

    result = hold_then_release(
        scratch_engine,
        lambda session: submit_as(session, ivy_id, interview_id),
        lambda session: submit_as(session, ivy_id, interview_id),
        (ScorecardAlreadySubmitted,),
    )

    assert result == "refused"
    with Session(scratch_engine) as check:
        assert (check.scalar(select(func.count()).select_from(Scorecard)) or 0) == 1


def test_a_scorecard_arriving_while_the_interview_is_being_cancelled_is_refused(
    db: Session, scratch_engine: Engine
) -> None:
    interview, recruiter, ivy, _ian = build(db)
    interview_id, recruiter_id, ivy_id = interview.id, recruiter.id, ivy.id

    def cancel(session: Session) -> None:
        person = session.get(User, recruiter_id)
        assert person is not None
        interviews_service.cancel_interview(session, person, interview_id, 1, datetime.now(UTC))

    result = hold_then_release(
        scratch_engine,
        cancel,
        lambda session: submit_as(session, ivy_id, interview_id),
        (InterviewNotScheduled,),
    )

    assert result == "refused"
    with Session(scratch_engine) as check:
        assert (check.scalar(select(func.count()).select_from(Scorecard)) or 0) == 0
        stored = check.get(Interview, interview_id)
        assert stored is not None and stored.status == InterviewStatus.CANCELLED
