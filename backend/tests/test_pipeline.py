"""Moving an application through the pipeline (functional.md > Move an application through the
pipeline) and rejecting it.

The rules under test: only the job's assigned recruiters move or reject; stages go forward one at a
time and the server decides which; a rejection needs a reason; every change carries the version the
person was looking at; each change writes its history row, its audit row and its candidate email
in one transaction; and nothing a recruiter writes can reach the candidate.
"""

from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Application,
    ApplicationStage,
    ApplicationStageHistory,
    AuditLog,
    BackgroundJob,
    Company,
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
    make_job,
    make_user,
)

NOT_FOUND = {"detail": "Not found."}
DETAIL_FIELDS = {
    "id",
    "job_id",
    "job_title",
    "candidate_name",
    "candidate_email",
    "candidate_phone",
    "candidate_location",
    "stage",
    "next_stage",
    "version",
    "applied_at",
    "rejection",
    "history",
}
HISTORY_FIELDS = {"from_stage", "to_stage", "changed_by_name", "changed_at"}
STAGES_IN_ORDER = ["applied", "screening", "interview", "offer", "hired"]


@dataclass
class World:
    acme: Company
    admin: User
    recruiter: User  # assigned to `job`
    other_recruiter: User  # assigned to nothing
    interviewer: User
    job: Job
    cara: User
    application: Application
    globex_admin: User


@pytest.fixture
def world(db: Session) -> World:
    acme, globex = make_company(db, "Acme"), make_company(db, "Globex")
    department = make_department(db, acme, "Engineering")
    admin = make_user(db, email="admin@acme.test", role=Role.COMPANY_ADMIN, company=acme)
    recruiter = make_user(
        db, email="rec@acme.test", role=Role.RECRUITER, company=acme, full_name="Rae Recruiter"
    )
    other_recruiter = make_user(db, email="rec2@acme.test", role=Role.RECRUITER, company=acme)
    interviewer = make_user(db, email="int@acme.test", role=Role.INTERVIEWER, company=acme)
    job = make_job(
        db,
        company=acme,
        department=department,
        created_by=admin,
        recruiters=[recruiter],
        status=PostingStatus.OPEN,
        title="Backend Engineer",
    )
    cara = make_candidate(db, email="cara@example.test", full_name="Cara Candidate")
    application = make_application(db, job=job, candidate=cara)
    globex_admin = make_user(db, email="admin@globex.test", role=Role.COMPANY_ADMIN, company=globex)
    db.commit()
    return World(
        acme, admin, recruiter, other_recruiter, interviewer, job, cara, application, globex_admin
    )


def advance(browser: Browser, application: Application, version: int | None = None) -> Any:
    body = {"version": application.version if version is None else version}
    return browser.send("POST", f"/api/applications/{application.id}/advance", json=body)


def reject(
    browser: Browser,
    application: Application,
    reason: str = "skills_mismatch",
    comment: str | None = None,
    version: int | None = None,
) -> Any:
    body: dict[str, Any] = {
        "version": application.version if version is None else version,
        "reason": reason,
    }
    if comment is not None:
        body["comment"] = comment
    return browser.send("POST", f"/api/applications/{application.id}/reject", json=body)


def audit_rows(db: Session, action: str) -> list[AuditLog]:
    db.expire_all()
    return list(db.scalars(select(AuditLog).where(AuditLog.action == action)))


def history_of(db: Session, application: Application) -> list[ApplicationStageHistory]:
    db.expire_all()
    return list(
        db.scalars(
            select(ApplicationStageHistory)
            .where(ApplicationStageHistory.application_id == application.id)
            .order_by(ApplicationStageHistory.changed_at, ApplicationStageHistory.id)
        )
    )


def queued_emails(db: Session, template: str) -> list[BackgroundJob]:
    db.expire_all()
    return [
        job for job in db.scalars(select(BackgroundJob)) if job.payload.get("template") == template
    ]


def reload(db: Session, application: Application) -> Application:
    db.expire_all()
    fresh = db.get(Application, application.id)
    assert fresh is not None
    return fresh


# ---- reading one application ---------------------------------------------------------------


def test_an_assigned_recruiter_sees_the_application_in_full(
    client: TestClient, db: Session, world: World
) -> None:
    response = Browser(client, db, world.recruiter).get(f"/api/applications/{world.application.id}")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == DETAIL_FIELDS
    assert body["id"] == str(world.application.id)
    assert body["candidate_name"] == "Cara Candidate"
    assert body["candidate_email"] == "cara@example.test"
    assert body["job_title"] == "Backend Engineer"
    assert body["stage"] == "applied" and body["next_stage"] == "screening"
    assert body["version"] == 1 and body["rejection"] is None
    first = body["history"][0]
    assert set(first) == HISTORY_FIELDS
    assert first["from_stage"] is None and first["to_stage"] == "applied"


def test_a_company_admin_can_read_but_not_move(
    client: TestClient, db: Session, world: World
) -> None:
    browser = Browser(client, db, world.admin)

    assert browser.get(f"/api/applications/{world.application.id}").status_code == 200
    assert advance(browser, world.application).status_code == 403
    assert reject(browser, world.application).status_code == 403
    assert reload(db, world.application).stage == ApplicationStage.APPLIED


def test_a_recruiter_not_assigned_to_the_job_gets_not_found(
    client: TestClient, db: Session, world: World
) -> None:
    browser = Browser(client, db, world.other_recruiter)

    for response in (
        browser.get(f"/api/applications/{world.application.id}"),
        advance(browser, world.application),
        reject(browser, world.application),
    ):
        assert response.status_code == 404 and response.json() == NOT_FOUND
    assert reload(db, world.application).version == 1


def test_another_companys_staff_get_not_found(
    client: TestClient, db: Session, world: World
) -> None:
    globex = world.globex_admin.company_id
    assert globex is not None
    stranger = make_user(
        db, email="rec@globex.test", role=Role.RECRUITER, company=db.get(Company, globex)
    )
    db.commit()

    admin = Browser(client, db, world.globex_admin)
    assert admin.get(f"/api/applications/{world.application.id}").json() == NOT_FOUND
    recruiter = Browser(client, db, stranger)
    for response in (
        recruiter.get(f"/api/applications/{world.application.id}"),
        advance(recruiter, world.application),
        reject(recruiter, world.application),
    ):
        assert response.status_code == 404 and response.json() == NOT_FOUND
    assert reload(db, world.application).version == 1


@pytest.mark.parametrize("who", ["interviewer", "cara"])
def test_interviewers_and_candidates_have_no_access(
    client: TestClient, db: Session, world: World, who: str
) -> None:
    browser = Browser(client, db, getattr(world, who))

    assert browser.get(f"/api/applications/{world.application.id}").status_code == 403
    assert advance(browser, world.application).status_code == 403
    assert reject(browser, world.application).status_code == 403


def test_an_unknown_application_is_not_found(client: TestClient, db: Session, world: World) -> None:
    response = Browser(client, db, world.recruiter).get(
        "/api/applications/6f1c2d3e-0000-4000-8000-000000000000"
    )

    assert response.status_code == 404 and response.json() == NOT_FOUND


# ---- moving forward --------------------------------------------------------------------------


def test_an_application_moves_forward_one_stage_at_a_time_to_hired(
    client: TestClient, db: Session, world: World
) -> None:
    browser = Browser(client, db, world.recruiter)
    application = world.application

    for index, expected in enumerate(STAGES_IN_ORDER[1:], start=1):
        response = advance(browser, application)

        assert response.status_code == 200
        body = response.json()
        assert body["stage"] == expected
        assert body["version"] == index + 1
        application = reload(db, application)
        assert application.stage == expected and application.version == index + 1

    assert response.json()["next_stage"] is None  # hired is the end
    stages = [(row.from_stage, row.to_stage) for row in history_of(db, application)]
    assert stages[-1] == (ApplicationStage.OFFER, ApplicationStage.HIRED)
    assert len(stages) == 5  # applied (created) plus four moves


def test_a_move_writes_history_audit_and_the_candidate_email_together(
    client: TestClient, db: Session, world: World
) -> None:
    response = advance(Browser(client, db, world.recruiter), world.application)

    assert response.status_code == 200
    last = history_of(db, world.application)[-1]
    assert (
        last.from_stage == ApplicationStage.APPLIED and last.to_stage == ApplicationStage.SCREENING
    )
    assert last.changed_by == world.recruiter.id
    audit = audit_rows(db, "application.stage_changed")
    assert len(audit) == 1
    assert audit[0].actor_user_id == world.recruiter.id
    assert audit[0].company_id == world.acme.id
    assert audit[0].old_value == {"stage": "applied"}
    assert audit[0].new_value == {"stage": "screening"}
    emails = queued_emails(db, "application_stage_changed")
    assert len(emails) == 1
    assert emails[0].payload["application_id"] == str(world.application.id)
    assert emails[0].payload["stage"] == "screening"


def test_the_request_cannot_choose_the_stage(client: TestClient, db: Session, world: World) -> None:
    # Skipping ahead or going back is impossible because the request has no stage in it.
    browser = Browser(client, db, world.recruiter)

    response = browser.send(
        "POST",
        f"/api/applications/{world.application.id}/advance",
        json={"version": 1, "to_stage": "offer"},
    )

    assert response.status_code == 422
    assert reload(db, world.application).stage == ApplicationStage.APPLIED


def test_a_move_needs_the_version(client: TestClient, db: Session, world: World) -> None:
    response = Browser(client, db, world.recruiter).send(
        "POST", f"/api/applications/{world.application.id}/advance", json={}
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "stage",
    [ApplicationStage.HIRED, ApplicationStage.REJECTED, ApplicationStage.WITHDRAWN],
)
def test_ended_applications_cannot_be_moved(
    client: TestClient, db: Session, world: World, stage: ApplicationStage
) -> None:
    application = make_application(
        db, job=world.job, candidate=make_candidate(db, email="x@example.test"), stage=stage
    )
    db.commit()

    response = advance(Browser(client, db, world.recruiter), application)

    assert response.status_code == 409 and response.json()["code"] == "application_not_active"
    assert reload(db, application).stage == stage


def test_a_stale_version_is_a_conflict_and_changes_nothing(
    client: TestClient, db: Session, world: World
) -> None:
    browser = Browser(client, db, world.recruiter)
    assert advance(browser, world.application).status_code == 200  # someone else got there first

    response = advance(browser, world.application, version=1)  # this person still sees version 1

    assert response.status_code == 409 and response.json()["code"] == "version_conflict"
    assert "application" in response.json()["detail"].lower()
    fresh = reload(db, world.application)
    assert fresh.stage == ApplicationStage.SCREENING and fresh.version == 2
    assert len(history_of(db, world.application)) == 2
    assert len(audit_rows(db, "application.stage_changed")) == 1
    assert len(queued_emails(db, "application_stage_changed")) == 1


def test_a_candidate_withdrawing_makes_a_recruiters_move_stale(
    client: TestClient, db: Session, world: World
) -> None:
    candidate = Browser(client, db, world.cara)
    assert (
        candidate.send("POST", f"/api/applications/{world.application.id}/withdraw").status_code
        == 200
    )

    response = advance(Browser(client, db, world.recruiter), world.application, version=1)

    assert response.status_code == 409 and response.json()["code"] == "version_conflict"
    assert reload(db, world.application).stage == ApplicationStage.WITHDRAWN


def test_moving_works_on_a_job_that_has_since_closed(
    client: TestClient, db: Session, world: World
) -> None:
    # Closing a job does not touch its in-flight applications: they continue to a decision.
    world.job.status = PostingStatus.CLOSED
    db.commit()

    response = advance(Browser(client, db, world.recruiter), world.application)

    assert response.status_code == 200 and response.json()["stage"] == "screening"


# ---- rejecting -------------------------------------------------------------------------------


@pytest.mark.parametrize("stage", ["applied", "screening", "interview", "offer"])
def test_an_application_can_be_rejected_from_any_active_stage(
    client: TestClient, db: Session, world: World, stage: str
) -> None:
    application = make_application(
        db,
        job=world.job,
        candidate=make_candidate(db, email="x@example.test"),
        stage=ApplicationStage(stage),
    )
    db.commit()

    response = reject(
        Browser(client, db, world.recruiter),
        application,
        reason="failed_interview",
        comment="  Struggled with the design round.  ",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["stage"] == "rejected" and body["next_stage"] is None
    assert body["rejection"] == {
        "from_stage": stage,
        "reason": "failed_interview",
        "comment": "Struggled with the design round.",
    }
    stored = reload(db, application)
    assert stored.stage == ApplicationStage.REJECTED and stored.version == 2
    assert stored.rejected_from_stage == stage


def test_a_rejection_writes_history_audit_and_a_generic_email_together(
    client: TestClient, db: Session, world: World
) -> None:
    secret = "Seemed arrogant in the interview"

    response = reject(
        Browser(client, db, world.recruiter), world.application, "other", comment=secret
    )

    assert response.status_code == 200
    last = history_of(db, world.application)[-1]
    assert last.to_stage == ApplicationStage.REJECTED and last.changed_by == world.recruiter.id
    audit = audit_rows(db, "application.rejected")
    assert len(audit) == 1
    assert audit[0].old_value == {"stage": "applied"}
    assert audit[0].new_value == {"stage": "rejected", "reason": "other"}
    # The internal comment is never copied anywhere but the application itself.
    assert secret not in str(
        [(row.old_value, row.new_value) for row in audit_rows(db, "application.rejected")]
    )
    emails = queued_emails(db, "application_rejected")
    assert len(emails) == 1
    assert secret not in str(emails[0].payload) and "reason" not in emails[0].payload


def test_other_needs_a_comment_and_the_others_do_not(
    client: TestClient, db: Session, world: World
) -> None:
    browser = Browser(client, db, world.recruiter)

    assert reject(browser, world.application, "other").status_code == 422
    assert reject(browser, world.application, "other", comment="   ").status_code == 422
    assert reload(db, world.application).stage == ApplicationStage.APPLIED
    assert reject(browser, world.application, "skills_mismatch").status_code == 200


def test_an_unknown_reason_or_an_overlong_comment_is_refused(
    client: TestClient, db: Session, world: World
) -> None:
    browser = Browser(client, db, world.recruiter)

    assert reject(browser, world.application, "bad_vibes").status_code == 422
    assert reject(browser, world.application, comment="x" * 2001).status_code == 422
    assert reject(browser, world.application, comment="x" * 2000).status_code == 200


def test_a_blank_comment_is_stored_as_none(client: TestClient, db: Session, world: World) -> None:
    response = reject(Browser(client, db, world.recruiter), world.application, comment="   ")

    assert response.status_code == 200 and response.json()["rejection"]["comment"] is None


@pytest.mark.parametrize(
    "stage",
    [ApplicationStage.HIRED, ApplicationStage.REJECTED, ApplicationStage.WITHDRAWN],
)
def test_ended_applications_cannot_be_rejected(
    client: TestClient, db: Session, world: World, stage: ApplicationStage
) -> None:
    application = make_application(
        db, job=world.job, candidate=make_candidate(db, email="x@example.test"), stage=stage
    )
    db.commit()

    response = reject(Browser(client, db, world.recruiter), application)

    assert response.status_code == 409 and response.json()["code"] == "application_not_active"
    assert reload(db, application).stage == stage


def test_rejecting_with_a_stale_version_is_a_conflict(
    client: TestClient, db: Session, world: World
) -> None:
    browser = Browser(client, db, world.recruiter)
    assert advance(browser, world.application).status_code == 200

    response = reject(browser, world.application, version=1)

    assert response.status_code == 409 and response.json()["code"] == "version_conflict"
    assert reload(db, world.application).stage == ApplicationStage.SCREENING
    assert audit_rows(db, "application.rejected") == []


def test_a_rejected_application_stays_rejected_for_the_candidate_too(
    client: TestClient, db: Session, world: World
) -> None:
    reject(Browser(client, db, world.recruiter), world.application, comment="internal words")

    candidate = Browser(client, db, world.cara)
    listing = candidate.get("/api/applications").json()
    withdraw = candidate.send("POST", f"/api/applications/{world.application.id}/withdraw")
    reactivate = candidate.send("POST", f"/api/applications/{world.application.id}/reactivate")

    assert listing["items"][0]["stage"] == "rejected"
    # The candidate's view has exactly the fields it had before this phase: no reason, no comment.
    assert set(listing["items"][0]) == {
        "id",
        "job_id",
        "job_title",
        "company_name",
        "stage",
        "applied_at",
        "job_is_open",
    }
    assert "internal words" not in str(listing) and "skills_mismatch" not in str(listing)
    assert withdraw.status_code == 409 and reactivate.status_code == 409


def test_no_stage_change_leaves_a_row_without_history(
    client: TestClient, db: Session, world: World
) -> None:
    browser = Browser(client, db, world.recruiter)
    advance(browser, world.application)
    reject(browser, world.application, version=2)

    history_rows = db.scalar(select(func.count()).select_from(ApplicationStageHistory)) or 0
    assert history_rows == 3  # created, screening, rejected
