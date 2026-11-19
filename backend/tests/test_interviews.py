"""Scheduling and cancelling interviews (functional.md > Schedule an interview).

The rules under test: only the job's assigned recruiters schedule or cancel; an interview exists
only while the application is in the Interview stage; interviewers must be active interviewers of
the same company; each change writes its audit row and queues its emails in one transaction; and a
stale or repeated change is refused instead of overwriting anything.
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
    Job,
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
INTERVIEW_FIELDS = {
    "id",
    "application_id",
    "round_name",
    "scheduled_at",
    "duration_minutes",
    "location",
    "status",
    "version",
    "calendar_sync_status",
    "needs_reassignment",
    "participants",
    "created_at",
}
PARTICIPANT_FIELDS = {"user_id", "full_name", "is_active"}


@dataclass
class World:
    acme: Company
    admin: User
    recruiter: User  # assigned to the job
    other_recruiter: User  # assigned to nothing
    ivy: User  # interviewer
    ian: User  # interviewer
    ghost: User  # interviewer who has been deactivated
    cara: User
    application: Application  # in the Interview stage
    globex_recruiter: User
    globex_interviewer: User


@pytest.fixture
def world(db: Session) -> World:
    acme, globex = make_company(db, "Acme"), make_company(db, "Globex")
    admin = make_user(db, email="admin@acme.test", role=Role.COMPANY_ADMIN, company=acme)
    recruiter = make_user(db, email="rec@acme.test", role=Role.RECRUITER, company=acme)
    other_recruiter = make_user(db, email="rec2@acme.test", role=Role.RECRUITER, company=acme)
    ivy = make_user(
        db, email="ivy@acme.test", role=Role.INTERVIEWER, company=acme, full_name="Ivy Inman"
    )
    ian = make_user(
        db, email="ian@acme.test", role=Role.INTERVIEWER, company=acme, full_name="Ian Ito"
    )
    ghost = make_user(db, email="ghost@acme.test", role=Role.INTERVIEWER, company=acme)
    ghost.is_active = False
    job = make_job(
        db,
        company=acme,
        department=make_department(db, acme),
        created_by=admin,
        recruiters=[recruiter],
        status=PostingStatus.OPEN,
        title="Backend Engineer",
    )
    cara = make_candidate(db, email="cara@example.test", full_name="Cara Candidate")
    application = make_application(db, job=job, candidate=cara, stage=ApplicationStage.INTERVIEW)
    globex_recruiter = make_user(db, email="rec@globex.test", role=Role.RECRUITER, company=globex)
    globex_interviewer = make_user(
        db, email="int@globex.test", role=Role.INTERVIEWER, company=globex
    )
    db.commit()
    return World(
        acme,
        admin,
        recruiter,
        other_recruiter,
        ivy,
        ian,
        ghost,
        cara,
        application,
        globex_recruiter,
        globex_interviewer,
    )


def in_days(days: int) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


def schedule(
    browser: Browser, application: Application, interviewers: list[User], **changes: Any
) -> Response:
    body: dict[str, Any] = {
        "round_name": "Technical round",
        "scheduled_at": in_days(3),
        "duration_minutes": 60,
        "location": "Room 4",
        "interviewer_ids": [str(person.id) for person in interviewers],
        **changes,
    }
    return browser.send("POST", f"/api/applications/{application.id}/interviews", json=body)


def cancel(browser: Browser, interview_id: object, version: int = 1) -> Response:
    return browser.send("POST", f"/api/interviews/{interview_id}/cancel", json={"version": version})


def audit_rows(db: Session, action: str) -> list[AuditLog]:
    db.expire_all()
    return list(db.scalars(select(AuditLog).where(AuditLog.action == action)))


def queued(db: Session, template: str) -> list[BackgroundJob]:
    db.expire_all()
    return [
        job for job in db.scalars(select(BackgroundJob)) if job.payload.get("template") == template
    ]


def stored_interviews(db: Session) -> list[Interview]:
    db.expire_all()
    return list(db.scalars(select(Interview)))


# ---- scheduling --------------------------------------------------------------------------------


def test_a_recruiter_schedules_an_interview_with_two_interviewers(
    client: TestClient, db: Session, world: World
) -> None:
    response = schedule(
        Browser(client, db, world.recruiter), world.application, [world.ivy, world.ian]
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body) == INTERVIEW_FIELDS
    assert body["application_id"] == str(world.application.id)
    assert body["round_name"] == "Technical round" and body["location"] == "Room 4"
    assert body["duration_minutes"] == 60 and body["status"] == "scheduled"
    assert body["version"] == 1 and body["calendar_sync_status"] == "not_requested"
    assert body["needs_reassignment"] is False
    assert {person["full_name"] for person in body["participants"]} == {"Ivy Inman", "Ian Ito"}
    assert all(set(person) == PARTICIPANT_FIELDS for person in body["participants"])
    stored = stored_interviews(db)[0]
    assert stored.company_id == world.acme.id and stored.scheduled_by == world.recruiter.id
    assert stored.scheduled_at.tzinfo is not None  # stored with its zone (UTC)


def test_the_time_is_stored_in_utc_whatever_zone_it_was_sent_in(
    client: TestClient, db: Session, world: World
) -> None:
    sent = (datetime.now(UTC) + timedelta(days=2)).replace(microsecond=0)
    plus_two = sent.astimezone(timezone(timedelta(hours=2))).isoformat()

    response = schedule(
        Browser(client, db, world.recruiter), world.application, [world.ivy], scheduled_at=plus_two
    )

    assert response.status_code == 201
    assert stored_interviews(db)[0].scheduled_at == sent
    assert datetime.fromisoformat(response.json()["scheduled_at"]) == sent


def test_scheduling_writes_the_audit_row_and_queues_every_email_together(
    client: TestClient, db: Session, world: World
) -> None:
    schedule(Browser(client, db, world.recruiter), world.application, [world.ivy, world.ian])

    audit = audit_rows(db, "interview.scheduled")
    assert len(audit) == 1
    assert audit[0].actor_user_id == world.recruiter.id and audit[0].company_id == world.acme.id
    assert audit[0].entity_type == "interview"
    assert audit[0].new_value == {"application_id": str(world.application.id)}
    emails = queued(db, "interview_scheduled")
    recipients = {job.payload["recipient_id"] for job in emails}
    assert recipients == {str(world.ivy.id), str(world.ian.id), str(world.cara.id)}
    assert len({job.idempotency_key for job in emails}) == 3  # one key per recipient


def test_an_application_can_have_several_rounds(
    client: TestClient, db: Session, world: World
) -> None:
    browser = Browser(client, db, world.recruiter)

    first = schedule(browser, world.application, [world.ivy], round_name="Phone screen")
    second = schedule(browser, world.application, [world.ian], round_name="Final round")

    assert first.status_code == 201 and second.status_code == 201
    assert len(stored_interviews(db)) == 2


@pytest.mark.parametrize(
    "stage",
    [
        ApplicationStage.APPLIED,
        ApplicationStage.SCREENING,
        ApplicationStage.OFFER,
        ApplicationStage.HIRED,
        ApplicationStage.REJECTED,
        ApplicationStage.WITHDRAWN,
    ],
)
def test_interviews_are_only_scheduled_in_the_interview_stage(
    client: TestClient, db: Session, world: World, stage: ApplicationStage
) -> None:
    job = db.get(Job, world.application.job_id)
    assert job is not None
    other = make_candidate(db, email="other@example.test")
    application = make_application(db, job=job, candidate=other, stage=stage)
    db.commit()

    response = schedule(Browser(client, db, world.recruiter), application, [world.ivy])

    assert response.status_code == 409
    assert response.json()["code"] == "application_not_in_interview"
    assert stored_interviews(db) == []


def test_a_time_in_the_past_is_refused(client: TestClient, db: Session, world: World) -> None:
    response = schedule(
        Browser(client, db, world.recruiter),
        world.application,
        [world.ivy],
        scheduled_at=in_days(-1),
    )

    assert response.status_code == 409 and response.json()["code"] == "interview_in_the_past"
    assert stored_interviews(db) == []


def test_a_time_without_a_zone_is_refused(client: TestClient, db: Session, world: World) -> None:
    naive = (datetime.now() + timedelta(days=3)).replace(tzinfo=None).isoformat()

    response = schedule(
        Browser(client, db, world.recruiter), world.application, [world.ivy], scheduled_at=naive
    )

    assert response.status_code == 422  # "3 pm" means nothing without knowing where


@pytest.mark.parametrize(
    "changes",
    [
        {"duration_minutes": 4},
        {"duration_minutes": 481},
        {"round_name": "   "},
        {"round_name": "x" * 101},
        {"location": ""},
        {"location": "x" * 301},
        {"scheduled_at": "not a time"},
        {"company_id": "00000000-0000-0000-0000-000000000000"},  # never taken from the request
    ],
)
def test_bad_values_are_refused(
    client: TestClient, db: Session, world: World, changes: dict[str, Any]
) -> None:
    response = schedule(
        Browser(client, db, world.recruiter), world.application, [world.ivy], **changes
    )

    assert response.status_code == 422
    assert stored_interviews(db) == []


def test_the_interviewer_list_must_be_sensible(
    client: TestClient, db: Session, world: World
) -> None:
    browser = Browser(client, db, world.recruiter)

    assert schedule(browser, world.application, []).status_code == 422
    twice = [str(world.ivy.id), str(world.ivy.id)]
    assert schedule(browser, world.application, [], interviewer_ids=twice).status_code == 422
    many = [str(world.ivy.id)] + [f"00000000-0000-0000-0000-0000000000{n:02d}" for n in range(10)]
    assert schedule(browser, world.application, [], interviewer_ids=many).status_code == 422
    assert stored_interviews(db) == []


@pytest.mark.parametrize("who", ["ghost", "globex_interviewer", "recruiter", "admin", "cara"])
def test_only_active_interviewers_of_the_same_company_can_be_assigned(
    client: TestClient, db: Session, world: World, who: str
) -> None:
    # A deactivated interviewer, another company's, a recruiter, an admin or a candidate: all the
    # same refusal, so the answer cannot be used to find out who exists elsewhere.
    response = schedule(
        Browser(client, db, world.recruiter), world.application, [world.ivy, getattr(world, who)]
    )

    assert response.status_code == 422 and response.json()["code"] == "invalid_interviewer"
    assert stored_interviews(db) == []  # not even the valid half was kept
    assert queued(db, "interview_scheduled") == []


def test_an_unknown_interviewer_is_refused_the_same_way(
    client: TestClient, db: Session, world: World
) -> None:
    response = schedule(
        Browser(client, db, world.recruiter),
        world.application,
        [],
        interviewer_ids=["6f1c2d3e-0000-4000-8000-000000000000"],
    )

    assert response.status_code == 422 and response.json()["code"] == "invalid_interviewer"


def test_a_company_admin_cannot_schedule(client: TestClient, db: Session, world: World) -> None:
    response = schedule(Browser(client, db, world.admin), world.application, [world.ivy])

    assert response.status_code == 403
    assert stored_interviews(db) == []


@pytest.mark.parametrize("who", ["ivy", "cara"])
def test_interviewers_and_candidates_cannot_schedule(
    client: TestClient, db: Session, world: World, who: str
) -> None:
    response = schedule(Browser(client, db, getattr(world, who)), world.application, [world.ivy])

    assert response.status_code == 403


@pytest.mark.parametrize("who", ["other_recruiter", "globex_recruiter"])
def test_a_recruiter_outside_the_job_gets_not_found(
    client: TestClient, db: Session, world: World, who: str
) -> None:
    response = schedule(Browser(client, db, getattr(world, who)), world.application, [world.ivy])

    assert response.status_code == 404 and response.json() == NOT_FOUND
    assert stored_interviews(db) == []


def test_an_unknown_application_is_not_found(client: TestClient, db: Session, world: World) -> None:
    browser = Browser(client, db, world.recruiter)
    response = browser.send(
        "POST",
        "/api/applications/6f1c2d3e-0000-4000-8000-000000000000/interviews",
        json={
            "round_name": "x",
            "scheduled_at": in_days(2),
            "duration_minutes": 30,
            "location": "y",
            "interviewer_ids": [str(world.ivy.id)],
        },
    )

    assert response.status_code == 404 and response.json() == NOT_FOUND


# ---- reading -----------------------------------------------------------------------------------


def test_staff_list_an_applications_interviews_in_time_order(
    client: TestClient, db: Session, world: World
) -> None:
    later = make_interview(
        db,
        application=world.application,
        scheduled_by=world.recruiter,
        interviewers=[world.ivy],
        scheduled_at=datetime.now(UTC) + timedelta(days=9),
        round_name="Final round",
    )
    sooner = make_interview(
        db,
        application=world.application,
        scheduled_by=world.recruiter,
        interviewers=[world.ian],
        scheduled_at=datetime.now(UTC) + timedelta(days=2),
        round_name="Phone screen",
    )
    db.commit()

    for person in (world.recruiter, world.admin):
        response = Browser(client, db, person).get(
            f"/api/applications/{world.application.id}/interviews"
        )

        assert response.status_code == 200
        assert [item["id"] for item in response.json()] == [str(sooner.id), str(later.id)]
        assert all(set(item) == INTERVIEW_FIELDS for item in response.json())


def test_an_application_with_no_interviews_has_an_empty_list(
    client: TestClient, db: Session, world: World
) -> None:
    response = Browser(client, db, world.recruiter).get(
        f"/api/applications/{world.application.id}/interviews"
    )

    assert response.status_code == 200 and response.json() == []


def test_an_interview_with_a_deactivated_interviewer_needs_reassignment(
    client: TestClient, db: Session, world: World
) -> None:
    make_interview(
        db,
        application=world.application,
        scheduled_by=world.recruiter,
        interviewers=[world.ivy, world.ghost],
    )
    db.commit()

    body = (
        Browser(client, db, world.recruiter)
        .get(f"/api/applications/{world.application.id}/interviews")
        .json()
    )

    assert body[0]["needs_reassignment"] is True
    flags = {person["full_name"]: person["is_active"] for person in body[0]["participants"]}
    assert flags["Ivy Inman"] is True and False in flags.values()


@pytest.mark.parametrize("who", ["ivy", "cara"])
def test_interviewers_and_candidates_cannot_list_an_applications_interviews(
    client: TestClient, db: Session, world: World, who: str
) -> None:
    response = Browser(client, db, getattr(world, who)).get(
        f"/api/applications/{world.application.id}/interviews"
    )

    assert response.status_code == 403


@pytest.mark.parametrize("who", ["other_recruiter", "globex_recruiter"])
def test_listing_outside_the_scope_is_not_found(
    client: TestClient, db: Session, world: World, who: str
) -> None:
    response = Browser(client, db, getattr(world, who)).get(
        f"/api/applications/{world.application.id}/interviews"
    )

    assert response.status_code == 404 and response.json() == NOT_FOUND


# ---- cancelling --------------------------------------------------------------------------------


def a_scheduled_interview(db: Session, world: World) -> Interview:
    interview = make_interview(
        db,
        application=world.application,
        scheduled_by=world.recruiter,
        interviewers=[world.ivy, world.ian],
    )
    db.commit()
    return interview


def test_a_recruiter_cancels_an_interview(client: TestClient, db: Session, world: World) -> None:
    interview = a_scheduled_interview(db, world)

    response = cancel(Browser(client, db, world.recruiter), interview.id)

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled" and response.json()["version"] == 2
    db.expire_all()
    stored = db.get(Interview, interview.id)
    assert stored is not None and stored.status == InterviewStatus.CANCELLED


def test_cancelling_writes_the_audit_row_and_queues_every_email_together(
    client: TestClient, db: Session, world: World
) -> None:
    interview = a_scheduled_interview(db, world)

    cancel(Browser(client, db, world.recruiter), interview.id)

    audit = audit_rows(db, "interview.cancelled")
    assert len(audit) == 1 and audit[0].actor_user_id == world.recruiter.id
    assert audit[0].old_value == {"status": "scheduled"}
    assert audit[0].new_value == {"status": "cancelled"}
    emails = queued(db, "interview_cancelled")
    assert {job.payload["recipient_id"] for job in emails} == {
        str(world.ivy.id),
        str(world.ian.id),
        str(world.cara.id),
    }


def test_cancelling_twice_is_refused_and_sends_nothing_more(
    client: TestClient, db: Session, world: World
) -> None:
    interview = a_scheduled_interview(db, world)
    browser = Browser(client, db, world.recruiter)
    cancel(browser, interview.id)

    again = cancel(browser, interview.id, version=2)

    assert again.status_code == 409 and again.json()["code"] == "interview_not_scheduled"
    assert len(queued(db, "interview_cancelled")) == 3
    assert len(audit_rows(db, "interview.cancelled")) == 1


def test_a_completed_interview_cannot_be_cancelled(
    client: TestClient, db: Session, world: World
) -> None:
    done = make_interview(
        db,
        application=world.application,
        scheduled_by=world.recruiter,
        interviewers=[world.ivy],
        status=InterviewStatus.COMPLETED,
    )
    db.commit()

    response = cancel(Browser(client, db, world.recruiter), done.id)

    assert response.status_code == 409 and response.json()["code"] == "interview_not_scheduled"


def test_a_stale_version_is_a_conflict_and_changes_nothing(
    client: TestClient, db: Session, world: World
) -> None:
    interview = a_scheduled_interview(db, world)

    response = cancel(Browser(client, db, world.recruiter), interview.id, version=7)

    assert response.status_code == 409 and response.json()["code"] == "version_conflict"
    assert "interview" in response.json()["detail"].lower()
    db.expire_all()
    stored = db.get(Interview, interview.id)
    assert stored is not None and stored.status == InterviewStatus.SCHEDULED
    assert queued(db, "interview_cancelled") == []


def test_a_company_admin_cannot_cancel(client: TestClient, db: Session, world: World) -> None:
    interview = a_scheduled_interview(db, world)

    assert cancel(Browser(client, db, world.admin), interview.id).status_code == 403


@pytest.mark.parametrize("who", ["ivy", "cara"])
def test_interviewers_and_candidates_cannot_cancel(
    client: TestClient, db: Session, world: World, who: str
) -> None:
    interview = a_scheduled_interview(db, world)

    assert cancel(Browser(client, db, getattr(world, who)), interview.id).status_code == 403


@pytest.mark.parametrize("who", ["other_recruiter", "globex_recruiter"])
def test_cancelling_outside_the_scope_is_not_found(
    client: TestClient, db: Session, world: World, who: str
) -> None:
    interview = a_scheduled_interview(db, world)

    response = cancel(Browser(client, db, getattr(world, who)), interview.id)

    assert response.status_code == 404 and response.json() == NOT_FOUND
    db.expire_all()
    stored = db.get(Interview, interview.id)
    assert stored is not None and stored.status == InterviewStatus.SCHEDULED


def test_an_unknown_interview_is_not_found(client: TestClient, db: Session, world: World) -> None:
    response = cancel(Browser(client, db, world.recruiter), "6f1c2d3e-0000-4000-8000-000000000000")

    assert response.status_code == 404 and response.json() == NOT_FOUND


# ---- what the database refuses -----------------------------------------------------------------


def test_an_interviewer_cannot_be_assigned_twice_to_the_same_interview(
    db: Session, world: World
) -> None:
    from sqlalchemy.exc import IntegrityError

    interview = make_interview(
        db, application=world.application, scheduled_by=world.recruiter, interviewers=[world.ivy]
    )
    db.add(
        InterviewParticipant(
            interview_id=interview.id, interviewer_id=world.ivy.id, assigned_at=datetime.now(UTC)
        )
    )

    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
