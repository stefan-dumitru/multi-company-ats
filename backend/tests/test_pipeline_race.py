"""Two people acting on one application at the same moment (functional.md > Move an application).

Needs two real database sessions (like test_applications_race.py). The first does its work but does
not commit, so it holds the application's row lock; the second must wait for it, then find that the
application has changed and be refused instead of overwriting it.
"""

import threading
import time
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.models import (
    Application,
    ApplicationStage,
    ApplicationStageHistory,
    PostingStatus,
    Role,
    User,
)
from app.services import applications as applications_service
from app.services import pipeline as pipeline_service
from app.services.errors import VersionConflict
from tests.factories import (
    make_application,
    make_candidate,
    make_company,
    make_department,
    make_job,
    make_user,
)


def build(db: Session) -> tuple[Application, User, User]:
    company = make_company(db)
    admin = make_user(db, email="admin@acme.test", role=Role.COMPANY_ADMIN, company=company)
    recruiter = make_user(db, email="rec@acme.test", role=Role.RECRUITER, company=company)
    job = make_job(
        db,
        company=company,
        department=make_department(db, company),
        created_by=admin,
        recruiters=[recruiter],
        status=PostingStatus.OPEN,
    )
    candidate = make_candidate(db, email="cara@example.test")
    application = make_application(db, job=job, candidate=candidate)
    db.commit()
    return application, recruiter, candidate


def test_two_moves_with_the_same_version_move_it_once(db: Session, scratch_engine: Engine) -> None:
    application, recruiter, _ = build(db)
    application_id, recruiter_id = application.id, recruiter.id
    outcome: dict[str, object] = {}

    first, second = Session(scratch_engine), Session(scratch_engine)
    try:
        first_user = first.get(User, recruiter_id)
        assert first_user is not None
        pipeline_service.advance_application(
            first, first_user, application_id, 1, datetime.now(UTC)
        )  # not committed yet: the row is locked

        def move_again() -> None:
            second_user = second.get(User, recruiter_id)
            assert second_user is not None
            try:
                pipeline_service.advance_application(
                    second, second_user, application_id, 1, datetime.now(UTC)
                )
                second.commit()
                outcome["result"] = "moved"
            except VersionConflict:
                second.rollback()
                outcome["result"] = "conflict"

        thread = threading.Thread(target=move_again)
        thread.start()
        time.sleep(1.0)
        assert thread.is_alive(), "the second move did not wait for the first one"

        first.commit()
        thread.join(timeout=10)
        assert not thread.is_alive()
    finally:
        first.close()
        second.close()

    assert outcome["result"] == "conflict"
    with Session(scratch_engine) as check:
        stored = check.get(Application, application_id)
        assert stored is not None
        assert stored.stage == ApplicationStage.SCREENING and stored.version == 2
        moves = check.scalar(select(func.count()).select_from(ApplicationStageHistory)) or 0
        assert moves == 2  # created, then one move


@pytest.mark.parametrize("candidate_goes_first", [True, False])
def test_a_move_and_a_withdrawal_at_the_same_time_take_turns(
    db: Session, scratch_engine: Engine, candidate_goes_first: bool
) -> None:
    application, recruiter, candidate = build(db)
    application_id, recruiter_id, candidate_id = application.id, recruiter.id, candidate.id
    outcome: dict[str, object] = {}

    def candidate_withdraws(session: Session) -> None:
        person = session.get(User, candidate_id)
        assert person is not None
        applications_service.withdraw_application(
            session, person, application_id, datetime.now(UTC)
        )

    def recruiter_advances(session: Session) -> None:
        person = session.get(User, recruiter_id)
        assert person is not None
        pipeline_service.advance_application(session, person, application_id, 1, datetime.now(UTC))

    first, second = Session(scratch_engine), Session(scratch_engine)
    try:
        (candidate_withdraws if candidate_goes_first else recruiter_advances)(first)

        def other_side() -> None:
            try:
                (recruiter_advances if candidate_goes_first else candidate_withdraws)(second)
                second.commit()
                outcome["result"] = "done"
            except VersionConflict:
                second.rollback()
                outcome["result"] = "conflict"

        thread = threading.Thread(target=other_side)
        thread.start()
        time.sleep(1.0)
        assert thread.is_alive(), "the second change did not wait for the first one"
        first.commit()
        thread.join(timeout=10)
        assert not thread.is_alive()
    finally:
        first.close()
        second.close()

    with Session(scratch_engine) as check:
        stored = check.get(Application, application_id)
        assert stored is not None
        assert stored.stage == ApplicationStage.WITHDRAWN
        if candidate_goes_first:
            # The recruiter was looking at version 1 of an application that has since been
            # withdrawn: refused, and the withdrawal stands.
            assert outcome["result"] == "conflict" and stored.version == 2
            assert stored.stage_before_withdrawal == ApplicationStage.APPLIED
        else:
            # The candidate sends no version: they withdraw from wherever it has got to.
            assert outcome["result"] == "done" and stored.version == 3
            assert stored.stage_before_withdrawal == ApplicationStage.SCREENING
