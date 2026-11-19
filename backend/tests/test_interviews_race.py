"""Two people acting at the same moment on an interview or its application.

Needs two real database sessions (like test_pipeline_race.py). The first does its work but does not
commit, so it holds the row lock; the second must wait for it, then find that things have changed
and be refused instead of overwriting anything.
"""

import threading
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.models import (
    Application,
    ApplicationStage,
    Interview,
    InterviewStatus,
    PostingStatus,
    RejectionReason,
    Role,
    User,
)
from app.services import interviews as interviews_service
from app.services import pipeline as pipeline_service
from app.services.errors import NotInInterviewStage, VersionConflict
from tests.factories import (
    make_application,
    make_candidate,
    make_company,
    make_department,
    make_interview,
    make_job,
    make_user,
)


def build(db: Session) -> tuple[Application, User, User]:
    company = make_company(db)
    admin = make_user(db, email="admin@acme.test", role=Role.COMPANY_ADMIN, company=company)
    recruiter = make_user(db, email="rec@acme.test", role=Role.RECRUITER, company=company)
    ivy = make_user(db, email="ivy@acme.test", role=Role.INTERVIEWER, company=company)
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
    db.commit()
    return application, recruiter, ivy


def test_two_cancellations_with_the_same_version_cancel_once(
    db: Session, scratch_engine: Engine
) -> None:
    application, recruiter, ivy = build(db)
    interview = make_interview(
        db, application=application, scheduled_by=recruiter, interviewers=[ivy]
    )
    db.commit()
    interview_id, recruiter_id = interview.id, recruiter.id
    outcome: dict[str, object] = {}

    first, second = Session(scratch_engine), Session(scratch_engine)
    try:
        person = first.get(User, recruiter_id)
        assert person is not None
        interviews_service.cancel_interview(first, person, interview_id, 1, datetime.now(UTC))

        def cancel_again() -> None:
            other = second.get(User, recruiter_id)
            assert other is not None
            try:
                interviews_service.cancel_interview(
                    second, other, interview_id, 1, datetime.now(UTC)
                )
                second.commit()
                outcome["result"] = "cancelled"
            except VersionConflict:
                second.rollback()
                outcome["result"] = "conflict"

        thread = threading.Thread(target=cancel_again)
        thread.start()
        time.sleep(1.0)
        assert thread.is_alive(), "the second cancellation did not wait for the first one"
        first.commit()
        thread.join(timeout=10)
        assert not thread.is_alive()
    finally:
        first.close()
        second.close()

    assert outcome["result"] == "conflict"
    with Session(scratch_engine) as check:
        stored = check.get(Interview, interview_id)
        assert stored is not None
        assert stored.status == InterviewStatus.CANCELLED and stored.version == 2


def test_scheduling_while_the_application_is_being_rejected_is_refused(
    db: Session, scratch_engine: Engine
) -> None:
    application, recruiter, ivy = build(db)
    application_id, recruiter_id, ivy_id = application.id, recruiter.id, ivy.id
    outcome: dict[str, object] = {}

    first, second = Session(scratch_engine), Session(scratch_engine)
    try:
        person = first.get(User, recruiter_id)
        assert person is not None
        pipeline_service.reject_application(
            first,
            person,
            application_id,
            1,
            RejectionReason.SKILLS_MISMATCH,
            None,
            datetime.now(UTC),
        )  # not committed yet: the application row is locked

        def schedule_meanwhile() -> None:
            other = second.get(User, recruiter_id)
            assert other is not None
            try:
                interviews_service.schedule_interview(
                    second,
                    other,
                    application_id,
                    round_name="Late round",
                    scheduled_at=datetime.now(UTC) + timedelta(days=2),
                    duration_minutes=30,
                    location="Room 1",
                    interviewer_ids=[ivy_id],
                    now=datetime.now(UTC),
                )
                second.commit()
                outcome["result"] = "scheduled"
            except NotInInterviewStage:
                second.rollback()
                outcome["result"] = "refused"

        thread = threading.Thread(target=schedule_meanwhile)
        thread.start()
        time.sleep(1.0)
        assert thread.is_alive(), "scheduling did not wait for the rejection"
        first.commit()
        thread.join(timeout=10)
        assert not thread.is_alive()
    finally:
        first.close()
        second.close()

    assert outcome["result"] == "refused"
    with Session(scratch_engine) as check:
        count = check.scalar(select(func.count()).select_from(Interview)) or 0
        assert count == 0
        stored = check.get(Application, application_id)
        assert stored is not None and stored.stage == ApplicationStage.REJECTED
