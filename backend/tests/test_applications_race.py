"""A double click, or two tabs: the same candidate applying twice at the same moment.

Needs two real database sessions (like test_jobs_race.py). The first does its work but does not
commit yet, so it holds the (candidate, job) slot; the second must wait for it and then find the
application the first one made, instead of failing or making a second one.
"""

import threading
import time
from datetime import UTC, datetime

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
from tests.factories import (
    make_application,
    make_candidate,
    make_company,
    make_department,
    make_job,
    make_user,
)


def test_two_simultaneous_applications_make_exactly_one(
    db: Session, scratch_engine: Engine
) -> None:
    company = make_company(db)
    admin = make_user(db, email="admin@acme.test", role=Role.COMPANY_ADMIN, company=company)
    job = make_job(
        db,
        company=company,
        department=make_department(db, company),
        created_by=admin,
        status=PostingStatus.OPEN,
    )
    candidate = make_candidate(db, email="cara@example.test")
    db.commit()
    job_id, candidate_id = job.id, candidate.id
    outcome: dict[str, object] = {}

    first, second = Session(scratch_engine), Session(scratch_engine)
    try:
        first_candidate = first.get(User, candidate_id)
        assert first_candidate is not None
        made = applications_service.apply_to_job(first, first_candidate, job_id, datetime.now(UTC))
        assert made.created is True  # not committed yet: the slot is held

        def apply_again() -> None:
            second_candidate = second.get(User, candidate_id)
            assert second_candidate is not None
            result = applications_service.apply_to_job(
                second, second_candidate, job_id, datetime.now(UTC)
            )
            second.commit()
            outcome["created"] = result.created
            outcome["application_id"] = result.application.id

        thread = threading.Thread(target=apply_again)
        thread.start()
        time.sleep(1.0)
        assert thread.is_alive(), "the second application did not wait for the first one"

        first.commit()
        thread.join(timeout=10)
        assert not thread.is_alive()
        first_application_id = made.application.id
    finally:
        first.close()
        second.close()

    assert outcome["created"] is False  # it found the first one
    assert outcome["application_id"] == first_application_id
    with Session(scratch_engine) as check:
        assert check.scalar(select(func.count()).select_from(Application)) == 1
        assert check.scalar(select(func.count()).select_from(ApplicationStageHistory)) == 1


def test_two_simultaneous_withdrawals_withdraw_once(db: Session, scratch_engine: Engine) -> None:
    # Without the row lock both would read "interview", both write "withdrawn", and the history
    # and the audit log would record the withdrawal twice.
    company = make_company(db)
    admin = make_user(db, email="admin@acme.test", role=Role.COMPANY_ADMIN, company=company)
    job = make_job(
        db,
        company=company,
        department=make_department(db, company),
        created_by=admin,
        status=PostingStatus.OPEN,
    )
    candidate = make_candidate(db, email="cara@example.test")
    application = make_application(db, job=job, candidate=candidate)
    application.stage = ApplicationStage.INTERVIEW
    db.commit()
    application_id, candidate_id = application.id, candidate.id
    outcome: dict[str, object] = {}

    first, second = Session(scratch_engine), Session(scratch_engine)
    try:
        first_candidate = first.get(User, candidate_id)
        assert first_candidate is not None
        applications_service.withdraw_application(
            first, first_candidate, application_id, datetime.now(UTC)
        )  # not committed yet: the row is locked

        def withdraw_again() -> None:
            second_candidate = second.get(User, candidate_id)
            assert second_candidate is not None
            result = applications_service.withdraw_application(
                second, second_candidate, application_id, datetime.now(UTC)
            )
            second.commit()
            outcome["stage"] = result.stage

        thread = threading.Thread(target=withdraw_again)
        thread.start()
        time.sleep(1.0)
        assert thread.is_alive(), "the second withdrawal did not wait for the first one"

        first.commit()
        thread.join(timeout=10)
        assert not thread.is_alive()
    finally:
        first.close()
        second.close()

    assert outcome["stage"] == ApplicationStage.WITHDRAWN
    with Session(scratch_engine) as check:
        stored = check.get(Application, application_id)
        assert stored is not None
        assert stored.version == 2  # one change, not two
        assert stored.stage_before_withdrawal == ApplicationStage.INTERVIEW
        withdrawals = check.scalar(
            select(func.count())
            .select_from(ApplicationStageHistory)
            .where(ApplicationStageHistory.to_stage == ApplicationStage.WITHDRAWN)
        )
        assert withdrawals == 1
