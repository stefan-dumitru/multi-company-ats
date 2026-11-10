"""Two people changing the same job at the same moment (data-model.md > Job).

Each test needs two real database sessions, like test_admin_race.py: the first does its work but
does not commit, so it still holds the job's row lock; the second must wait for that lock instead
of acting on stale information, and then see what the first one did.
"""

import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.models import AuditLog, Job, PostingStatus, Role, User
from app.services import jobs as jobs_service
from app.services.errors import LastRecruiterError, VersionConflict
from tests.factories import make_company, make_department, make_job, make_user


def setup_job(db: Session) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A draft job with one recruiter. Returns the job, recruiter and admin ids."""
    company = make_company(db)
    admin = make_user(db, email="admin@acme.test", role=Role.COMPANY_ADMIN, company=company)
    recruiter = make_user(db, email="rec@acme.test", role=Role.RECRUITER, company=company)
    job = make_job(
        db,
        company=company,
        department=make_department(db, company),
        created_by=admin,
        recruiters=[recruiter],
    )
    db.commit()
    return job.id, recruiter.id, admin.id


def run_second_while_first_holds_the_lock(
    engine: Engine,
    admin_id: uuid.UUID,
    first_action: Callable[[Session, User], Any],
    second_action: Callable[[Session, User], Any],
) -> dict[str, object]:
    """Run the first action (uncommitted), start the second in a thread, check it is waiting,
    then commit the first. Returns what the second one did."""
    outcome: dict[str, object] = {}
    first, second = Session(engine), Session(engine)
    try:
        first_admin = first.get(User, admin_id)
        assert first_admin is not None
        first_action(first, first_admin)

        def second_does_its_thing() -> None:
            second_admin = second.get(User, admin_id)
            assert second_admin is not None
            try:
                outcome["result"] = second_action(second, second_admin)
                second.commit()
            except (VersionConflict, LastRecruiterError) as refusal:
                second.rollback()
                outcome["refused"] = type(refusal).__name__

        thread = threading.Thread(target=second_does_its_thing)
        thread.start()
        time.sleep(1.0)
        assert thread.is_alive(), "the second request did not wait for the job's lock"

        first.commit()
        thread.join(timeout=10)
        assert not thread.is_alive()
    finally:
        first.close()
        second.close()
    return outcome


def test_two_simultaneous_publishes_open_the_job_once(db: Session, scratch_engine: Engine) -> None:
    job_id, _, admin_id = setup_job(db)

    outcome = run_second_while_first_holds_the_lock(
        scratch_engine,
        admin_id,
        lambda s, who: jobs_service.publish_job(s, who, job_id, 1, datetime.now(UTC)),
        lambda s, who: jobs_service.publish_job(s, who, job_id, 1, datetime.now(UTC)),
    )

    # The second one finds the job already open: nothing to do, and no error.
    assert "refused" not in outcome
    with Session(scratch_engine) as check:
        job = check.get(Job, job_id)
        assert job is not None and job.status == PostingStatus.OPEN and job.version == 2
        published = check.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "job.published")
        )
        assert published == 1


def test_two_simultaneous_edits_of_the_same_version_do_not_both_win(
    db: Session, scratch_engine: Engine
) -> None:
    job_id, _, admin_id = setup_job(db)

    outcome = run_second_while_first_holds_the_lock(
        scratch_engine,
        admin_id,
        lambda s, who: jobs_service.update_job(
            s, who, job_id, 1, {"title": "First writer"}, datetime.now(UTC)
        ),
        lambda s, who: jobs_service.update_job(
            s, who, job_id, 1, {"title": "Second writer"}, datetime.now(UTC)
        ),
    )

    assert outcome == {"refused": "VersionConflict"}
    with Session(scratch_engine) as check:
        job = check.get(Job, job_id)
        assert job is not None and job.title == "First writer" and job.version == 2


def test_removing_the_only_recruiter_while_the_job_is_being_published_is_refused(
    db: Session, scratch_engine: Engine
) -> None:
    # Without the job lock, both would pass their own check (publish: "one recruiter exists";
    # remove: "the job is still a draft") and an open job would end up with nobody.
    job_id, recruiter_id, admin_id = setup_job(db)

    outcome = run_second_while_first_holds_the_lock(
        scratch_engine,
        admin_id,
        lambda s, who: jobs_service.publish_job(s, who, job_id, 1, datetime.now(UTC)),
        lambda s, who: jobs_service.unassign_recruiter(
            s, who, job_id, recruiter_id, datetime.now(UTC)
        ),
    )

    assert outcome == {"refused": "LastRecruiterError"}
    with Session(scratch_engine) as check:
        job = check.get(Job, job_id)
        assert job is not None and job.status == PostingStatus.OPEN
