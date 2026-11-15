"""Applying to a job, withdrawing, reactivating, and the candidate's own list
(functional.md > Candidate applies to a job; Candidate withdraws, reactivates ...).

The rules under test: one application per candidate per job (a retry returns the existing one), a
job must be open, a resume must be on file and is snapshotted, every change writes its history and
audit rows and queues its email in the same transaction, and a candidate only ever reaches their
own applications.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Application,
    ApplicationStage,
    ApplicationStageHistory,
    AuditLog,
    BackgroundJob,
    CandidateProfile,
    Company,
    Department,
    File,
    Job,
    PostingStatus,
    Role,
    User,
)
from app.services import applications as applications_service
from tests.browser import Browser
from tests.factories import (
    make_application,
    make_candidate,
    make_company,
    make_department,
    make_job,
    make_resume_file,
    make_user,
)

NOT_FOUND = {"detail": "Not found."}
VIEW_FIELDS = {"id", "job_id", "job_title", "company_name", "stage", "applied_at", "job_is_open"}


@dataclass
class World:
    acme: Company
    globex: Company
    department: Department
    admin: User
    recruiter: User
    open_job: Job
    closed_job: Job
    draft_job: Job
    globex_job: Job
    cara: User
    dan: User
    eve: User  # verified, but has no resume
    uma: User  # has a resume, but has not verified her email


@pytest.fixture
def world(db: Session) -> World:
    acme, globex = make_company(db, "Acme"), make_company(db, "Globex")
    department = make_department(db, acme, "Engineering")
    admin = make_user(db, email="admin@acme.test", role=Role.COMPANY_ADMIN, company=acme)
    recruiter = make_user(db, email="rec@acme.test", role=Role.RECRUITER, company=acme)

    def job(status: PostingStatus, title: str) -> Job:
        return make_job(
            db,
            company=acme,
            department=department,
            created_by=admin,
            recruiters=[recruiter],
            status=status,
            title=title,
        )

    globex_admin = make_user(db, email="admin@globex.test", role=Role.COMPANY_ADMIN, company=globex)
    built = World(
        acme=acme,
        globex=globex,
        department=department,
        admin=admin,
        recruiter=recruiter,
        open_job=job(PostingStatus.OPEN, "Backend Engineer"),
        closed_job=job(PostingStatus.CLOSED, "Old role"),
        draft_job=job(PostingStatus.DRAFT, "Secret draft"),
        globex_job=make_job(
            db,
            company=globex,
            department=make_department(db, globex, "Platform"),
            created_by=globex_admin,
            recruiters=[],
            status=PostingStatus.OPEN,
            title="Globex Designer",
        ),
        cara=make_candidate(db, email="cara@example.test", full_name="Cara Candidate"),
        dan=make_candidate(db, email="dan@example.test", full_name="Dan Candidate"),
        eve=make_candidate(db, email="eve@example.test", resume=False),
        uma=make_candidate(db, email="uma@example.test", verified=False),
    )
    db.commit()
    return built


def apply(browser: Browser, job: Job | str) -> Any:
    job_id = job.id if isinstance(job, Job) else job
    return browser.send("POST", "/api/applications", json={"job_id": str(job_id)})


def rows(db: Session, model: Any) -> list[Any]:
    db.expire_all()
    return list(db.scalars(select(model)))


def audit_actions(db: Session) -> list[str]:
    db.expire_all()
    return list(db.scalars(select(AuditLog.action).order_by(AuditLog.created_at, AuditLog.id)))


def count(db: Session, model: Any) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(model)) or 0


# ---- applying ----------------------------------------------------------------------------


def test_a_candidate_applies_to_an_open_job(client: TestClient, db: Session, world: World) -> None:
    response = apply(Browser(client, db, world.cara), world.open_job)

    assert response.status_code == 201
    body = response.json()
    assert set(body) == VIEW_FIELDS  # nothing internal, no resume id, no version
    assert body["job_id"] == str(world.open_job.id)
    assert body["job_title"] == "Backend Engineer" and body["company_name"] == "Acme"
    assert body["stage"] == "applied" and body["job_is_open"] is True


def test_the_application_copies_the_company_and_snapshots_the_resume(
    client: TestClient, db: Session, world: World
) -> None:
    profile = db.get(CandidateProfile, world.cara.id)
    assert profile is not None and profile.current_resume_file_id is not None

    apply(Browser(client, db, world.cara), world.open_job)

    application = rows(db, Application)[0]
    assert application.candidate_id == world.cara.id
    assert application.job_id == world.open_job.id
    assert application.company_id == world.acme.id  # copied from the job
    assert application.resume_file_id == profile.current_resume_file_id
    assert application.stage == ApplicationStage.APPLIED
    assert application.stage_before_withdrawal is None and application.version == 1


def test_a_later_resume_does_not_change_what_was_applied_with(
    client: TestClient, db: Session, world: World
) -> None:
    browser = Browser(client, db, world.cara)
    apply(browser, world.open_job)
    snapshot = rows(db, Application)[0].resume_file_id

    newer = make_resume_file(db, world.cara, "newer.pdf")
    profile = db.get(CandidateProfile, world.cara.id)
    assert profile is not None
    profile.current_resume_file_id = newer.id
    db.commit()

    assert rows(db, Application)[0].resume_file_id == snapshot != newer.id


def test_applying_writes_history_audit_and_the_confirmation_email_together(
    client: TestClient, db: Session, world: World
) -> None:
    apply(Browser(client, db, world.cara), world.open_job)

    application = rows(db, Application)[0]
    (history,) = rows(db, ApplicationStageHistory)
    assert history.application_id == application.id
    assert history.from_stage is None and history.to_stage == ApplicationStage.APPLIED
    assert history.changed_by == world.cara.id
    (audit,) = rows(db, AuditLog)
    assert audit.action == "application.created" and audit.entity_type == "application"
    assert audit.entity_id == application.id and audit.actor_user_id == world.cara.id
    assert audit.company_id == world.acme.id  # filed under the company the application is for
    assert audit.new_value == {"stage": "applied"}
    (email,) = rows(db, BackgroundJob)
    assert email.type == "send_email" and email.payload["template"] == "application_received"
    assert email.payload["application_id"] == str(application.id)
    assert email.idempotency_key == f"application_received:{application.id}"


def test_everything_is_one_transaction(
    client: TestClient, db: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    # If queueing the email fails, there must be no application, history or audit row either.
    def failing_enqueue(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("the queue is broken")

    monkeypatch.setattr(applications_service, "enqueue", failing_enqueue)
    browser = Browser(client, db, world.cara)

    with pytest.raises(RuntimeError):
        apply(browser, world.open_job)

    db.rollback()
    assert count(db, Application) == 0
    assert count(db, ApplicationStageHistory) == 0
    assert count(db, AuditLog) == 0


def test_applying_again_returns_the_same_application_and_changes_nothing(
    client: TestClient, db: Session, world: World
) -> None:
    browser = Browser(client, db, world.cara)
    first = apply(browser, world.open_job)

    again = apply(browser, world.open_job)

    assert again.status_code == 200  # found, not created
    assert again.json()["id"] == first.json()["id"]
    assert count(db, Application) == 1 and count(db, ApplicationStageHistory) == 1
    assert len(audit_actions(db)) == 1 and count(db, BackgroundJob) == 1  # no second email


def test_applying_again_finds_the_application_even_if_the_resume_or_the_job_is_gone(
    client: TestClient, db: Session, world: World
) -> None:
    # Someone who already applied gets their application back, not a new refusal about a resume
    # they no longer have or a job that has since closed.
    browser = Browser(client, db, world.cara)
    first = apply(browser, world.open_job).json()
    profile = db.get(CandidateProfile, world.cara.id)
    assert profile is not None
    profile.current_resume_file_id = None
    world.open_job.status = PostingStatus.CLOSED
    db.commit()

    again = apply(browser, world.open_job)

    assert again.status_code == 200 and again.json()["id"] == first["id"]
    assert count(db, Application) == 1


def test_applying_after_withdrawing_returns_the_withdrawn_application(
    client: TestClient, db: Session, world: World
) -> None:
    browser = Browser(client, db, world.cara)
    first = apply(browser, world.open_job).json()
    browser.send("POST", f"/api/applications/{first['id']}/withdraw")

    again = apply(browser, world.open_job)

    assert again.status_code == 200
    assert again.json()["id"] == first["id"] and again.json()["stage"] == "withdrawn"
    assert count(db, Application) == 1


def test_a_candidate_may_apply_to_any_company_and_each_candidate_gets_their_own(
    client: TestClient, db: Session, world: World
) -> None:
    assert apply(Browser(client, db, world.cara), world.globex_job).status_code == 201
    assert apply(Browser(client, db, world.cara), world.open_job).status_code == 201
    assert apply(Browser(client, db, world.dan), world.open_job).status_code == 201

    by_candidate = {(a.candidate_id, a.job_id): a.company_id for a in rows(db, Application)}
    assert by_candidate == {
        (world.cara.id, world.globex_job.id): world.globex.id,
        (world.cara.id, world.open_job.id): world.acme.id,
        (world.dan.id, world.open_job.id): world.acme.id,
    }


def test_a_closed_job_does_not_take_applications(
    client: TestClient, db: Session, world: World
) -> None:
    response = apply(Browser(client, db, world.cara), world.closed_job)

    assert response.status_code == 409 and response.json()["code"] == "job_not_open"
    assert count(db, Application) == 0 and count(db, BackgroundJob) == 0


def test_a_draft_and_an_unknown_job_look_exactly_the_same(
    client: TestClient, db: Session, world: World
) -> None:
    browser = Browser(client, db, world.cara)

    draft = apply(browser, world.draft_job)
    unknown = apply(browser, str(uuid.uuid4()))

    assert draft.status_code == unknown.status_code == 404
    assert draft.json() == unknown.json() == NOT_FOUND
    assert count(db, Application) == 0


def test_a_resume_is_needed_first(client: TestClient, db: Session, world: World) -> None:
    response = apply(Browser(client, db, world.eve), world.open_job)

    assert response.status_code == 409 and response.json()["code"] == "resume_required"
    assert count(db, Application) == 0 and count(db, AuditLog) == 0


def test_a_resume_that_was_removed_from_storage_does_not_count(
    client: TestClient, db: Session, world: World
) -> None:
    profile = db.get(CandidateProfile, world.cara.id)
    assert profile is not None and profile.current_resume_file_id is not None
    removed = db.get(File, profile.current_resume_file_id)
    assert removed is not None
    removed.deleted_at = datetime.now(UTC)
    db.commit()

    response = apply(Browser(client, db, world.cara), world.open_job)

    assert response.status_code == 409 and response.json()["code"] == "resume_required"


def test_a_candidate_without_any_profile_row_is_asked_for_a_resume(
    client: TestClient, db: Session, world: World
) -> None:
    bare = make_user(db, email="bare@example.test", role=Role.CANDIDATE, company=None)
    db.commit()

    response = apply(Browser(client, db, bare), world.open_job)

    assert response.status_code == 409 and response.json()["code"] == "resume_required"


def test_an_unverified_candidate_cannot_apply(
    client: TestClient, db: Session, world: World
) -> None:
    response = apply(Browser(client, db, world.uma), world.open_job)

    assert response.status_code == 403 and response.json()["code"] == "email_not_verified"
    assert count(db, Application) == 0


def test_staff_and_visitors_cannot_apply(client: TestClient, db: Session, world: World) -> None:
    assert apply(Browser(client, db, world.recruiter), world.open_job).status_code == 403
    assert apply(Browser(client, db, world.admin), world.open_job).status_code == 403
    client.cookies.clear()
    assert (
        client.post("/api/applications", json={"job_id": str(world.open_job.id)}).status_code == 401
    )
    assert count(db, Application) == 0


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"job_id": "not-an-id"},
        {"job_id": None},
        {"job_id": str(uuid.uuid4()), "company_id": str(uuid.uuid4())},
        {"job_id": str(uuid.uuid4()), "stage": "offer"},
        {"job_id": str(uuid.uuid4()), "candidate_id": str(uuid.uuid4())},
    ],
)
def test_the_request_holds_the_job_and_nothing_else(
    client: TestClient, db: Session, world: World, body: dict[str, Any]
) -> None:
    response = Browser(client, db, world.cara).send("POST", "/api/applications", json=body)

    assert response.status_code == 422
    assert count(db, Application) == 0


# ---- withdrawing -------------------------------------------------------------------------


def applied(
    db: Session, world: World, stage: ApplicationStage, job: Job | None = None
) -> Application:
    application = make_application(
        db, job=job or world.open_job, candidate=world.cara, stage=ApplicationStage.APPLIED
    )
    if stage != ApplicationStage.APPLIED:
        application.stage = stage
    db.commit()
    return application


@pytest.mark.parametrize(
    "stage",
    [
        ApplicationStage.APPLIED,
        ApplicationStage.SCREENING,
        ApplicationStage.INTERVIEW,
        ApplicationStage.OFFER,
    ],
)
def test_an_application_can_be_withdrawn_from_any_active_stage(
    client: TestClient, db: Session, world: World, stage: ApplicationStage
) -> None:
    application = applied(db, world, stage)

    response = Browser(client, db, world.cara).send(
        "POST", f"/api/applications/{application.id}/withdraw"
    )

    assert response.status_code == 200 and response.json()["stage"] == "withdrawn"
    db.expire_all()
    stored = db.get(Application, application.id)
    assert stored is not None
    assert stored.stage == ApplicationStage.WITHDRAWN and stored.stage_before_withdrawal == stage
    assert stored.version == 2
    last = rows(db, ApplicationStageHistory)[-1]
    assert last.from_stage is not None and last.to_stage == ApplicationStage.WITHDRAWN
    assert last.changed_by == world.cara.id
    assert audit_actions(db)[-1] == "application.withdrawn"


def test_withdrawing_twice_changes_nothing_the_second_time(
    client: TestClient, db: Session, world: World
) -> None:
    application = applied(db, world, ApplicationStage.SCREENING)
    browser = Browser(client, db, world.cara)
    browser.send("POST", f"/api/applications/{application.id}/withdraw")
    history, audits = count(db, ApplicationStageHistory), len(audit_actions(db))

    again = browser.send("POST", f"/api/applications/{application.id}/withdraw")

    assert again.status_code == 200 and again.json()["stage"] == "withdrawn"
    assert count(db, ApplicationStageHistory) == history and len(audit_actions(db)) == audits
    db.expire_all()
    remembered = db.get(Application, application.id)
    assert remembered is not None
    assert remembered.stage_before_withdrawal == ApplicationStage.SCREENING  # not overwritten
    assert remembered.version == 2


@pytest.mark.parametrize("ended", [ApplicationStage.HIRED, ApplicationStage.REJECTED])
def test_an_application_that_has_ended_cannot_be_withdrawn(
    client: TestClient, db: Session, world: World, ended: ApplicationStage
) -> None:
    application = applied(db, world, ended)

    response = Browser(client, db, world.cara).send(
        "POST", f"/api/applications/{application.id}/withdraw"
    )

    assert response.status_code == 409 and response.json()["code"] == "application_ended"
    db.expire_all()
    stored = db.get(Application, application.id)
    assert stored is not None and stored.stage == ended


def test_an_application_to_a_job_that_has_since_closed_can_still_be_withdrawn(
    client: TestClient, db: Session, world: World
) -> None:
    application = applied(db, world, ApplicationStage.INTERVIEW, job=world.closed_job)

    response = Browser(client, db, world.cara).send(
        "POST", f"/api/applications/{application.id}/withdraw"
    )

    assert response.status_code == 200 and response.json()["job_is_open"] is False


# ---- reactivating ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "stage",
    [
        ApplicationStage.APPLIED,
        ApplicationStage.SCREENING,
        ApplicationStage.INTERVIEW,
        ApplicationStage.OFFER,
    ],
)
def test_reactivating_restores_the_stage_the_application_was_in(
    client: TestClient, db: Session, world: World, stage: ApplicationStage
) -> None:
    application = applied(db, world, stage)
    browser = Browser(client, db, world.cara)
    browser.send("POST", f"/api/applications/{application.id}/withdraw")

    response = browser.send("POST", f"/api/applications/{application.id}/reactivate")

    assert response.status_code == 200 and response.json()["stage"] == stage.value
    db.expire_all()
    stored = db.get(Application, application.id)
    assert stored is not None
    assert stored.stage == stage and stored.stage_before_withdrawal is None
    assert stored.version == 3
    last = rows(db, ApplicationStageHistory)[-1]
    assert last.from_stage == ApplicationStage.WITHDRAWN and last.to_stage == stage
    assert audit_actions(db)[-1] == "application.reactivated"


def test_reactivating_an_application_that_is_not_withdrawn_changes_nothing(
    client: TestClient, db: Session, world: World
) -> None:
    application = applied(db, world, ApplicationStage.SCREENING)
    before = (count(db, ApplicationStageHistory), len(audit_actions(db)))

    response = Browser(client, db, world.cara).send(
        "POST", f"/api/applications/{application.id}/reactivate"
    )

    assert response.status_code == 200 and response.json()["stage"] == "screening"
    assert (count(db, ApplicationStageHistory), len(audit_actions(db))) == before
    db.expire_all()
    stored = db.get(Application, application.id)
    assert stored is not None and stored.version == 1


@pytest.mark.parametrize("ended", [ApplicationStage.REJECTED, ApplicationStage.HIRED])
def test_an_application_that_ended_cannot_be_reactivated(
    client: TestClient, db: Session, world: World, ended: ApplicationStage
) -> None:
    application = applied(db, world, ended)

    response = Browser(client, db, world.cara).send(
        "POST", f"/api/applications/{application.id}/reactivate"
    )

    assert response.status_code == 409 and response.json()["code"] == "cannot_reactivate"
    db.expire_all()
    stored = db.get(Application, application.id)
    assert stored is not None and stored.stage == ended


def test_a_withdrawn_application_to_a_job_that_has_closed_cannot_be_reactivated(
    client: TestClient, db: Session, world: World
) -> None:
    application = applied(db, world, ApplicationStage.INTERVIEW, job=world.closed_job)
    browser = Browser(client, db, world.cara)
    browser.send("POST", f"/api/applications/{application.id}/withdraw")

    response = browser.send("POST", f"/api/applications/{application.id}/reactivate")

    assert response.status_code == 409 and response.json()["code"] == "job_not_open"
    db.expire_all()
    stored = db.get(Application, application.id)
    assert stored is not None and stored.stage == ApplicationStage.WITHDRAWN


# ---- only your own ----------------------------------------------------------------------


@pytest.mark.parametrize("action", ["withdraw", "reactivate"])
def test_another_candidates_application_is_not_found(
    client: TestClient, db: Session, world: World, action: str
) -> None:
    theirs = make_application(db, job=world.open_job, candidate=world.dan)
    db.commit()
    browser = Browser(client, db, world.cara)

    other = browser.send("POST", f"/api/applications/{theirs.id}/{action}")
    unknown = browser.send("POST", f"/api/applications/{uuid.uuid4()}/{action}")

    assert other.status_code == unknown.status_code == 404
    assert other.json() == unknown.json() == NOT_FOUND  # indistinguishable
    db.expire_all()
    untouched = db.get(Application, theirs.id)
    assert untouched is not None and untouched.stage == ApplicationStage.APPLIED


@pytest.mark.parametrize("action", ["withdraw", "reactivate"])
def test_staff_and_visitors_cannot_withdraw_or_reactivate(
    client: TestClient, db: Session, world: World, action: str
) -> None:
    theirs = make_application(db, job=world.open_job, candidate=world.cara)
    db.commit()

    assert (
        Browser(client, db, world.admin)
        .send("POST", f"/api/applications/{theirs.id}/{action}")
        .status_code
        == 403
    )
    client.cookies.clear()
    assert client.post(f"/api/applications/{theirs.id}/{action}").status_code == 401


# ---- my applications ---------------------------------------------------------------------


def test_the_list_holds_only_my_applications_newest_first(
    client: TestClient, db: Session, world: World
) -> None:
    older = make_application(db, job=world.open_job, candidate=world.cara)
    newer = make_application(db, job=world.globex_job, candidate=world.cara)
    older.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    newer.created_at = datetime(2026, 2, 1, tzinfo=UTC)
    make_application(db, job=world.open_job, candidate=world.dan)  # someone else's
    db.commit()

    body = Browser(client, db, world.cara).get("/api/applications").json()

    assert [item["id"] for item in body["items"]] == [str(newer.id), str(older.id)]
    assert body["total"] == 2 and body["page"] == 1 and body["page_size"] == 20
    assert all(set(item) == VIEW_FIELDS for item in body["items"])


def test_the_list_can_be_narrowed_to_one_job(client: TestClient, db: Session, world: World) -> None:
    # The job page asks "did I already apply here?" this way. Someone else's application for the
    # same job must never appear, and a job I did not apply to gives an empty list.
    mine = make_application(db, job=world.open_job, candidate=world.cara)
    make_application(db, job=world.globex_job, candidate=world.cara)
    make_application(db, job=world.open_job, candidate=world.dan)
    db.commit()
    browser = Browser(client, db, world.cara)

    same_job = browser.get(f"/api/applications?job_id={world.open_job.id}").json()
    other_job = browser.get(f"/api/applications?job_id={world.closed_job.id}").json()

    assert [item["id"] for item in same_job["items"]] == [str(mine.id)]
    assert same_job["total"] == 1
    assert other_job["items"] == [] and other_job["total"] == 0


def test_a_job_filter_that_is_not_an_id_is_refused(
    client: TestClient, db: Session, world: World
) -> None:
    assert Browser(client, db, world.cara).get("/api/applications?job_id=oops").status_code == 422


def test_the_list_shows_the_job_company_and_whether_it_is_still_open(
    client: TestClient, db: Session, world: World
) -> None:
    make_application(db, job=world.open_job, candidate=world.cara)
    make_application(db, job=world.closed_job, candidate=world.cara)
    db.commit()

    items = {
        item["job_title"]: item
        for item in Browser(client, db, world.cara).get("/api/applications").json()["items"]
    }

    assert items["Backend Engineer"]["job_is_open"] is True
    assert items["Backend Engineer"]["company_name"] == "Acme"
    assert items["Old role"]["job_is_open"] is False  # still listed: the application goes on


def test_a_candidate_with_no_applications_gets_an_empty_page(
    client: TestClient, db: Session, world: World
) -> None:
    body = Browser(client, db, world.dan).get("/api/applications").json()

    assert body == {"items": [], "total": 0, "page": 1, "page_size": 20}


def test_the_list_is_paginated(client: TestClient, db: Session, world: World) -> None:
    for number in range(5):
        job = make_job(
            db,
            company=world.acme,
            department=world.department,
            created_by=world.admin,
            status=PostingStatus.OPEN,
            title=f"Job {number}",
        )
        application = make_application(db, job=job, candidate=world.cara)
        application.created_at = datetime(2026, 1, 1 + number, tzinfo=UTC)
    db.commit()
    browser = Browser(client, db, world.cara)

    first = browser.get("/api/applications?page=1&page_size=2").json()
    last = browser.get("/api/applications?page=3&page_size=2").json()

    assert [i["job_title"] for i in first["items"]] == ["Job 4", "Job 3"]
    assert [i["job_title"] for i in last["items"]] == ["Job 0"]
    assert first["total"] == last["total"] == 5


@pytest.mark.parametrize("query", ["page=0", "page_size=0", "page_size=101"])
def test_silly_page_numbers_are_refused(
    client: TestClient, db: Session, world: World, query: str
) -> None:
    assert Browser(client, db, world.cara).get(f"/api/applications?{query}").status_code == 422


def test_staff_and_visitors_cannot_list_a_candidates_applications(
    client: TestClient, db: Session, world: World
) -> None:
    assert Browser(client, db, world.recruiter).get("/api/applications").status_code == 403
    client.cookies.clear()
    assert client.get("/api/applications").status_code == 401


def test_job_and_company_names_are_plain_text_in_the_answer(
    client: TestClient, db: Session, world: World
) -> None:
    world.open_job.title = "<img src=x onerror=alert(1)>"
    db.commit()
    make_application(db, job=world.open_job, candidate=world.cara)
    db.commit()

    item = Browser(client, db, world.cara).get("/api/applications").json()["items"][0]

    assert (
        item["job_title"] == "<img src=x onerror=alert(1)>"
    )  # stored as typed; the screen escapes


# ---- the database backs the rules up -----------------------------------------------------


def test_the_database_refuses_a_second_application_for_the_same_job(
    db: Session, world: World
) -> None:
    make_application(db, job=world.open_job, candidate=world.cara)
    db.commit()

    with pytest.raises(IntegrityError):
        make_application(db, job=world.open_job, candidate=world.cara)
        db.commit()
    db.rollback()


@pytest.mark.parametrize(
    ("stage", "remembered"),
    [
        (ApplicationStage.WITHDRAWN, None),  # withdrawn with nothing to go back to
        (ApplicationStage.APPLIED, ApplicationStage.APPLIED),  # not withdrawn, but remembering
        (ApplicationStage.WITHDRAWN, ApplicationStage.HIRED),  # cannot have withdrawn from "hired"
        (ApplicationStage.WITHDRAWN, ApplicationStage.WITHDRAWN),
    ],
)
def test_the_database_keeps_withdrawal_consistent(
    db: Session, world: World, stage: ApplicationStage, remembered: ApplicationStage | None
) -> None:
    now = datetime.now(UTC)
    application = Application(
        job_id=world.open_job.id,
        company_id=world.acme.id,
        candidate_id=world.cara.id,
        resume_file_id=make_resume_file(db, world.cara).id,
        stage=stage,
        stage_before_withdrawal=remembered,
        created_at=now,
        updated_at=now,
    )
    db.add(application)

    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
