"""When an application ends, its interviews end with it (functional.md > Schedule an interview).

Rejecting an application, or the candidate withdrawing it, cancels the interviews that are still
scheduled, in the same transaction, and tells the interviewers. The candidate is not emailed about
it: they either did it themselves or already got the rejection.
"""

from collections.abc import Callable
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Application,
    ApplicationStage,
    AuditLog,
    BackgroundJob,
    Interview,
    InterviewStatus,
    PostingStatus,
    Role,
    User,
)
from tests.browser import Browser
from tests.factories import (
    make_application,
    make_candidate,
    make_company,
    make_department,
    make_interview,
    make_job,
    make_user,
)

Ending = Callable[[TestClient, Session, "World"], None]


@dataclass
class World:
    admin: User
    recruiter: User
    ivy: User
    ian: User
    cara: User
    application: Application
    first: Interview  # scheduled
    second: Interview  # scheduled
    done: Interview  # completed: stays as it is
    called_off: Interview  # already cancelled: stays as it is
    bystander: Interview  # scheduled, on somebody else's application


@pytest.fixture
def world(db: Session) -> World:
    company = make_company(db, "Acme")
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
    cara = make_candidate(db, email="cara@example.test")
    application = make_application(db, job=job, candidate=cara, stage=ApplicationStage.INTERVIEW)
    other = make_application(
        db,
        job=job,
        candidate=make_candidate(db, email="dan@example.test"),
        stage=ApplicationStage.INTERVIEW,
    )

    def interview(app: Application, status: InterviewStatus, who: list[User]) -> Interview:
        return make_interview(
            db, application=app, scheduled_by=recruiter, interviewers=who, status=status
        )

    world = World(
        admin,
        recruiter,
        ivy,
        ian,
        cara,
        application,
        interview(application, InterviewStatus.SCHEDULED, [ivy]),
        interview(application, InterviewStatus.SCHEDULED, [ivy, ian]),
        interview(application, InterviewStatus.COMPLETED, [ivy]),
        interview(application, InterviewStatus.CANCELLED, [ian]),
        interview(other, InterviewStatus.SCHEDULED, [ivy]),
    )
    db.commit()
    return world


def stored(db: Session, interview: Interview) -> Interview:
    db.expire_all()
    fresh = db.get(Interview, interview.id)
    assert fresh is not None
    return fresh


def statuses(db: Session, world: World) -> dict[str, InterviewStatus]:
    names = ("first", "second", "done", "called_off", "bystander")
    return {name: stored(db, getattr(world, name)).status for name in names}


def emailed(db: Session, template: str) -> set[tuple[str, str]]:
    """(interview id, recipient id) of every queued email of one kind."""
    db.expire_all()
    return {
        (job.payload["interview_id"], job.payload["recipient_id"])
        for job in db.scalars(select(BackgroundJob))
        if job.payload.get("template") == template
    }


def reject(client: TestClient, db: Session, world: World) -> None:
    response = Browser(client, db, world.recruiter).send(
        "POST",
        f"/api/applications/{world.application.id}/reject",
        json={"version": 1, "reason": "skills_mismatch"},
    )
    assert response.status_code == 200


def withdraw(client: TestClient, db: Session, world: World) -> None:
    response = Browser(client, db, world.cara).send(
        "POST", f"/api/applications/{world.application.id}/withdraw"
    )
    assert response.status_code == 200


@pytest.mark.parametrize("how", [reject, withdraw])
def test_ending_an_application_cancels_its_scheduled_interviews_and_only_those(
    client: TestClient, db: Session, world: World, how: Ending
) -> None:
    how(client, db, world)

    assert statuses(db, world) == {
        "first": InterviewStatus.CANCELLED,
        "second": InterviewStatus.CANCELLED,
        "done": InterviewStatus.COMPLETED,  # kept as it was
        "called_off": InterviewStatus.CANCELLED,  # was already cancelled
        "bystander": InterviewStatus.SCHEDULED,  # somebody else's application
    }
    assert stored(db, world.first).version == 2
    assert stored(db, world.done).version == 1


@pytest.mark.parametrize("how", [reject, withdraw])
def test_the_interviewers_are_told_and_the_candidate_is_not(
    client: TestClient, db: Session, world: World, how: Ending
) -> None:
    how(client, db, world)

    assert emailed(db, "interview_cancelled") == {
        (str(world.first.id), str(world.ivy.id)),
        (str(world.second.id), str(world.ivy.id)),
        (str(world.second.id), str(world.ian.id)),
    }


def test_a_rejection_files_each_cancellation_under_the_recruiter(
    client: TestClient, db: Session, world: World
) -> None:
    reject(client, db, world)

    db.expire_all()
    rows = list(db.scalars(select(AuditLog).where(AuditLog.action == "interview.cancelled")))
    assert len(rows) == 2 and {row.actor_user_id for row in rows} == {world.recruiter.id}
    assert {row.entity_id for row in rows} == {world.first.id, world.second.id}
    assert all(row.new_value == {"status": "cancelled"} for row in rows)


def test_a_withdrawal_files_each_cancellation_under_the_candidate_and_the_company(
    client: TestClient, db: Session, world: World
) -> None:
    withdraw(client, db, world)

    db.expire_all()
    rows = list(db.scalars(select(AuditLog).where(AuditLog.action == "interview.cancelled")))
    assert len(rows) == 2 and {row.actor_user_id for row in rows} == {world.cara.id}
    assert {row.company_id for row in rows} == {world.admin.company_id}  # a candidate has none


def test_reactivating_a_withdrawn_application_does_not_bring_the_interviews_back(
    client: TestClient, db: Session, world: World
) -> None:
    withdraw(client, db, world)

    response = Browser(client, db, world.cara).send(
        "POST", f"/api/applications/{world.application.id}/reactivate"
    )

    assert response.status_code == 200
    assert statuses(db, world)["first"] == InterviewStatus.CANCELLED  # scheduling again is the way
