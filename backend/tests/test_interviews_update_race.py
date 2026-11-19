"""Two people changing the same interview at the same moment.

Needs two real database sessions (like test_interviews_race.py). The first does its work but does
not commit, so it holds the row lock; the second waits, then finds the interview has changed and is
refused instead of overwriting it.
"""

import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.models import (
    ApplicationStage,
    Interview,
    InterviewStatus,
    PostingStatus,
    Role,
    User,
)
from app.services import interviews as interviews_service
from app.services.errors import InterviewNotScheduled, VersionConflict
from tests.factories import (
    make_application,
    make_candidate,
    make_company,
    make_department,
    make_interview,
    make_job,
    make_user,
)


def build(db: Session) -> tuple[Interview, User]:
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
    interview = make_interview(
        db, application=application, scheduled_by=recruiter, interviewers=[ivy]
    )
    db.commit()
    return interview, recruiter


def reschedule(session: Session, user: User, interview_id: uuid.UUID) -> None:
    interviews_service.update_interview(
        session, user, interview_id, 1, {"location": "Room 9"}, datetime.now(UTC)
    )


def cancel(session: Session, user: User, interview_id: uuid.UUID) -> None:
    interviews_service.cancel_interview(session, user, interview_id, 1, datetime.now(UTC))


@pytest.mark.parametrize(
    ("first_does", "second_does", "expected_status"),
    [
        (reschedule, reschedule, InterviewStatus.SCHEDULED),
        (reschedule, cancel, InterviewStatus.SCHEDULED),
        (cancel, reschedule, InterviewStatus.CANCELLED),
    ],
    ids=["two reschedules", "reschedule then cancel", "cancel then reschedule"],
)
def test_two_changes_with_the_same_version_apply_once(
    db: Session,
    scratch_engine: Engine,
    first_does: Callable[[Session, User, uuid.UUID], None],
    second_does: Callable[[Session, User, uuid.UUID], None],
    expected_status: InterviewStatus,
) -> None:
    interview, recruiter = build(db)
    interview_id, recruiter_id = interview.id, recruiter.id
    outcome: dict[str, str] = {}

    first, second = Session(scratch_engine), Session(scratch_engine)
    try:
        person = first.get(User, recruiter_id)
        assert person is not None
        first_does(first, person, interview_id)  # not committed yet: the row is locked

        def other() -> None:
            someone = second.get(User, recruiter_id)
            assert someone is not None
            try:
                second_does(second, someone, interview_id)
                second.commit()
                outcome["result"] = "applied"
            except VersionConflict, InterviewNotScheduled:
                second.rollback()
                outcome["result"] = "refused"

        thread = threading.Thread(target=other)
        thread.start()
        time.sleep(1.0)
        assert thread.is_alive(), "the second change did not wait for the first one"
        first.commit()
        thread.join(timeout=10)
        assert not thread.is_alive()
    finally:
        first.close()
        second.close()

    assert outcome["result"] == "refused"
    with Session(scratch_engine) as check:
        stored = check.get(Interview, interview_id)
        assert stored is not None
        assert stored.status == expected_status and stored.version == 2
