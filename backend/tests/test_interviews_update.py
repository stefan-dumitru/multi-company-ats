"""Changing an interview: reschedule it, or change who interviews (functional.md > Schedule an
interview).

The rules under test: only the job's assigned recruiters change an interview, only while it is
scheduled and with the version they were looking at; the new time is in the future; people who are
added, kept and removed each get the right email; an unchanged request changes nothing; and a
deactivated interviewer who is already assigned can stay.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Application,
    ApplicationStage,
    AuditLog,
    BackgroundJob,
    Company,
    Interview,
    InterviewParticipant,
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

NOT_FOUND = {"detail": "Not found."}


@dataclass
class World:
    admin: User
    recruiter: User
    other_recruiter: User
    ivy: User
    ian: User
    ivo: User  # an interviewer who is not on the interview at first
    ghost: User  # deactivated after being assigned
    cara: User
    application: Application
    interview: Interview  # Ivy, Ian and Ghost, in three days
    globex_recruiter: User
    globex_interviewer: User


@pytest.fixture
def world(db: Session) -> World:
    acme, globex = make_company(db, "Acme"), make_company(db, "Globex")
    admin = make_user(db, email="admin@acme.test", role=Role.COMPANY_ADMIN, company=acme)
    recruiter = make_user(db, email="rec@acme.test", role=Role.RECRUITER, company=acme)
    other_recruiter = make_user(db, email="rec2@acme.test", role=Role.RECRUITER, company=acme)
    ivy = make_user(db, email="ivy@acme.test", role=Role.INTERVIEWER, company=acme)
    ian = make_user(db, email="ian@acme.test", role=Role.INTERVIEWER, company=acme)
    ivo = make_user(db, email="ivo@acme.test", role=Role.INTERVIEWER, company=acme)
    ghost = make_user(db, email="ghost@acme.test", role=Role.INTERVIEWER, company=acme)
    job = make_job(
        db,
        company=acme,
        department=make_department(db, acme),
        created_by=admin,
        recruiters=[recruiter],
        status=PostingStatus.OPEN,
    )
    cara = make_candidate(db, email="cara@example.test")
    application = make_application(db, job=job, candidate=cara, stage=ApplicationStage.INTERVIEW)
    interview = make_interview(
        db, application=application, scheduled_by=recruiter, interviewers=[ivy, ian, ghost]
    )
    ghost.is_active = False  # deactivated after the assignment
    globex_recruiter = make_user(db, email="rec@globex.test", role=Role.RECRUITER, company=globex)
    globex_interviewer = make_user(
        db, email="int@globex.test", role=Role.INTERVIEWER, company=globex
    )
    db.commit()
    return World(
        admin,
        recruiter,
        other_recruiter,
        ivy,
        ian,
        ivo,
        ghost,
        cara,
        application,
        interview,
        globex_recruiter,
        globex_interviewer,
    )


def update(browser: Browser, interview: Interview, version: int = 1, **changes: Any) -> Response:
    return browser.send(
        "PATCH", f"/api/interviews/{interview.id}", json={"version": version, **changes}
    )


def ids(*people: User) -> list[str]:
    return [str(person.id) for person in people]


def in_days(days: int) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


def reloaded(db: Session, interview: Interview) -> Interview:
    db.expire_all()
    fresh = db.get(Interview, interview.id)
    assert fresh is not None
    return fresh


def participants(db: Session, interview: Interview) -> set[str]:
    db.expire_all()
    return {
        str(row)
        for row in db.scalars(
            select(InterviewParticipant.interviewer_id).where(
                InterviewParticipant.interview_id == interview.id
            )
        )
    }


def emails(db: Session, template: str) -> dict[str, BackgroundJob]:
    """The queued emails of one kind, by recipient."""
    db.expire_all()
    return {
        job.payload["recipient_id"]: job
        for job in db.scalars(select(BackgroundJob))
        if job.payload.get("template") == template
    }


def audit_rows(db: Session, action: str) -> list[AuditLog]:
    db.expire_all()
    return list(db.scalars(select(AuditLog).where(AuditLog.action == action)))


# ---- rescheduling ----------------------------------------------------------------------------


def test_a_recruiter_reschedules_an_interview(
    client: TestClient, db: Session, world: World
) -> None:
    new_time = (datetime.now(UTC) + timedelta(days=6)).replace(microsecond=0)

    response = update(
        Browser(client, db, world.recruiter),
        world.interview,
        scheduled_at=new_time.isoformat(),
        duration_minutes=90,
        location="Room 9",
        round_name="Final round",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == 2 and body["status"] == "scheduled"
    assert body["duration_minutes"] == 90 and body["location"] == "Room 9"
    assert body["round_name"] == "Final round"
    stored = reloaded(db, world.interview)
    assert stored.scheduled_at == new_time and stored.version == 2


def test_the_time_may_be_sent_in_any_zone_and_is_stored_in_utc(
    client: TestClient, db: Session, world: World
) -> None:
    sent = (datetime.now(UTC) + timedelta(days=4)).replace(microsecond=0)
    plus_five = sent.astimezone(timezone(timedelta(hours=5))).isoformat()

    update(Browser(client, db, world.recruiter), world.interview, scheduled_at=plus_five)

    assert reloaded(db, world.interview).scheduled_at == sent


def test_a_reschedule_tells_everyone_who_can_still_act_and_the_candidate(
    client: TestClient, db: Session, world: World
) -> None:
    update(Browser(client, db, world.recruiter), world.interview, location="Room 9")

    told = emails(db, "interview_rescheduled")
    # The deactivated interviewer keeps the assignment but is not written to.
    assert set(told) == {str(world.ivy.id), str(world.ian.id), str(world.cara.id)}
    assert len({job.idempotency_key for job in told.values()}) == 3
    assert all(job.payload["interview_id"] == str(world.interview.id) for job in told.values())
    assert emails(db, "interview_scheduled") == {} and emails(db, "interview_unassigned") == {}


def test_a_reschedule_writes_one_audit_row_naming_what_changed_and_no_values(
    client: TestClient, db: Session, world: World
) -> None:
    update(Browser(client, db, world.recruiter), world.interview, location="Secret room 7")

    rows = audit_rows(db, "interview.updated")
    assert len(rows) == 1 and rows[0].actor_user_id == world.recruiter.id
    assert rows[0].new_value == {"changed": ["location"]}
    assert "Secret room 7" not in str(rows[0].new_value) + str(rows[0].old_value)


def test_sending_the_values_it_already_has_changes_nothing(
    client: TestClient, db: Session, world: World
) -> None:
    current = reloaded(db, world.interview)

    response = update(
        Browser(client, db, world.recruiter),
        world.interview,
        location=current.location,
        duration_minutes=current.duration_minutes,
        interviewer_ids=ids(world.ivy, world.ian, world.ghost),
    )

    assert response.status_code == 200 and response.json()["version"] == 1
    assert reloaded(db, world.interview).version == 1
    assert audit_rows(db, "interview.updated") == []
    assert emails(db, "interview_rescheduled") == {}


# ---- who interviews --------------------------------------------------------------------------


def test_adding_an_interviewer_invites_only_the_new_one(
    client: TestClient, db: Session, world: World
) -> None:
    response = update(
        Browser(client, db, world.recruiter),
        world.interview,
        interviewer_ids=ids(world.ivy, world.ian, world.ghost, world.ivo),
    )

    assert response.status_code == 200
    assert participants(db, world.interview) == set(
        ids(world.ivy, world.ian, world.ghost, world.ivo)
    )
    assert set(emails(db, "interview_scheduled")) == {str(world.ivo.id)}
    assert emails(db, "interview_rescheduled") == {}  # the time did not change


def test_removing_an_interviewer_tells_that_person_and_only_that_person(
    client: TestClient, db: Session, world: World
) -> None:
    response = update(
        Browser(client, db, world.recruiter),
        world.interview,
        interviewer_ids=ids(world.ivy, world.ghost),
    )

    assert response.status_code == 200
    assert participants(db, world.interview) == set(ids(world.ivy, world.ghost))
    assert set(emails(db, "interview_unassigned")) == {str(world.ian.id)}
    assert emails(db, "interview_rescheduled") == {} and emails(db, "interview_scheduled") == {}


def test_a_change_of_time_and_people_tells_each_group_the_right_thing(
    client: TestClient, db: Session, world: World
) -> None:
    update(
        Browser(client, db, world.recruiter),
        world.interview,
        scheduled_at=in_days(8),
        interviewer_ids=ids(world.ivy, world.ghost, world.ivo),
    )

    assert set(emails(db, "interview_rescheduled")) == {str(world.ivy.id), str(world.cara.id)}
    assert set(emails(db, "interview_scheduled")) == {str(world.ivo.id)}
    assert set(emails(db, "interview_unassigned")) == {str(world.ian.id)}


def test_an_interviewer_who_was_deactivated_after_assignment_can_stay(
    client: TestClient, db: Session, world: World
) -> None:
    response = update(
        Browser(client, db, world.recruiter),
        world.interview,
        interviewer_ids=ids(world.ivy, world.ian, world.ghost),
    )

    assert response.status_code == 200
    assert str(world.ghost.id) in participants(db, world.interview)


@pytest.mark.parametrize("who", ["globex_interviewer", "recruiter", "admin", "cara"])
def test_new_interviewers_must_be_active_interviewers_of_the_company(
    client: TestClient, db: Session, world: World, who: str
) -> None:
    response = update(
        Browser(client, db, world.recruiter),
        world.interview,
        interviewer_ids=ids(world.ivy, getattr(world, who)),
    )

    assert response.status_code == 422 and response.json()["code"] == "invalid_interviewer"
    assert participants(db, world.interview) == set(ids(world.ivy, world.ian, world.ghost))
    assert reloaded(db, world.interview).version == 1


def test_a_deactivated_person_cannot_be_added_though_one_may_stay(
    client: TestClient, db: Session, world: World
) -> None:
    company = db.get(Company, world.admin.company_id)
    assert company is not None
    other_ghost = make_user(db, email="ghost2@acme.test", role=Role.INTERVIEWER, company=company)
    other_ghost.is_active = False
    db.commit()

    response = update(
        Browser(client, db, world.recruiter),
        world.interview,
        interviewer_ids=ids(world.ivy, world.ian, world.ghost, other_ghost),
    )

    assert response.status_code == 422 and response.json()["code"] == "invalid_interviewer"


# ---- refusals --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "changes",
    [
        {},  # nothing to change
        {"scheduled_at": "not a time"},
        {"scheduled_at": "2030-01-01T10:00:00"},  # no zone
        {"duration_minutes": 4},
        {"duration_minutes": 481},
        {"round_name": "   "},
        {"location": ""},
        {"interviewer_ids": []},
        {"status": "completed"},  # never taken from the request
        {"company_id": "00000000-0000-0000-0000-000000000000"},
    ],
)
def test_bad_requests_are_refused_and_change_nothing(
    client: TestClient, db: Session, world: World, changes: dict[str, Any]
) -> None:
    response = update(Browser(client, db, world.recruiter), world.interview, **changes)

    assert response.status_code == 422
    assert reloaded(db, world.interview).version == 1


def test_a_missing_version_is_refused(client: TestClient, db: Session, world: World) -> None:
    response = Browser(client, db, world.recruiter).send(
        "PATCH", f"/api/interviews/{world.interview.id}", json={"location": "Room 9"}
    )

    assert response.status_code == 422


def test_a_new_time_in_the_past_is_refused(client: TestClient, db: Session, world: World) -> None:
    response = update(
        Browser(client, db, world.recruiter), world.interview, scheduled_at=in_days(-1)
    )

    assert response.status_code == 409 and response.json()["code"] == "interview_in_the_past"
    assert reloaded(db, world.interview).version == 1


def test_a_stale_version_is_a_conflict_and_changes_nothing(
    client: TestClient, db: Session, world: World
) -> None:
    browser = Browser(client, db, world.recruiter)
    assert update(browser, world.interview, location="Room 9").status_code == 200

    response = update(browser, world.interview, version=1, location="Room 12")

    assert response.status_code == 409 and response.json()["code"] == "version_conflict"
    assert reloaded(db, world.interview).location == "Room 9"


@pytest.mark.parametrize("status", [InterviewStatus.CANCELLED, InterviewStatus.COMPLETED])
def test_only_a_scheduled_interview_can_be_changed(
    client: TestClient, db: Session, world: World, status: InterviewStatus
) -> None:
    done = make_interview(
        db,
        application=world.application,
        scheduled_by=world.recruiter,
        interviewers=[world.ivy],
        status=status,
    )
    db.commit()

    response = update(Browser(client, db, world.recruiter), done, location="Room 9")

    assert response.status_code == 409 and response.json()["code"] == "interview_not_scheduled"


def test_a_company_admin_cannot_change_an_interview(
    client: TestClient, db: Session, world: World
) -> None:
    assert (
        update(Browser(client, db, world.admin), world.interview, location="x").status_code == 403
    )


@pytest.mark.parametrize("who", ["ivy", "cara"])
def test_interviewers_and_candidates_cannot_change_an_interview(
    client: TestClient, db: Session, world: World, who: str
) -> None:
    response = update(Browser(client, db, getattr(world, who)), world.interview, location="x")

    assert response.status_code == 403


@pytest.mark.parametrize("who", ["other_recruiter", "globex_recruiter"])
def test_a_recruiter_outside_the_job_gets_not_found(
    client: TestClient, db: Session, world: World, who: str
) -> None:
    response = update(Browser(client, db, getattr(world, who)), world.interview, location="x")

    assert response.status_code == 404 and response.json() == NOT_FOUND
    assert reloaded(db, world.interview).version == 1


def test_an_unknown_interview_is_not_found(client: TestClient, db: Session, world: World) -> None:
    response = Browser(client, db, world.recruiter).send(
        "PATCH",
        "/api/interviews/6f1c2d3e-0000-4000-8000-000000000000",
        json={"version": 1, "location": "x"},
    )

    assert response.status_code == 404 and response.json() == NOT_FOUND
