"""Jobs for staff (data-model.md > Job, JobRecruiter; functional.md > Roles).

Rules under test: admins see every job of their company, a recruiter only the jobs assigned to
them; a job goes draft -> open -> closed; a live job always has a recruiter; every edit quotes the
version it saw; every change is audited in the same transaction; other companies' jobs are "not
found".
"""

import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import Engine, event, func, select
from sqlalchemy.orm import Session

from app.models import AuditLog, Company, Department, Job, JobRecruiter, PostingStatus, Role, User
from tests.browser import Browser
from tests.factories import make_company, make_department, make_job, make_user

NOT_FOUND = {"detail": "Not found."}


@dataclass
class World:
    acme: Company
    globex: Company
    admin: User
    rec1: User
    rec2: User
    interviewer: User
    engineering: Department
    archived: Department
    globex_admin: User
    globex_rec: User
    globex_dept: Department


@pytest.fixture
def world(db: Session) -> World:
    acme, globex = make_company(db, "Acme"), make_company(db, "Globex")
    archived = make_department(db, acme, "Old team")
    archived.is_archived = True
    built = World(
        acme=acme,
        globex=globex,
        admin=make_user(db, email="admin@acme.test", role=Role.COMPANY_ADMIN, company=acme),
        rec1=make_user(db, email="rec1@acme.test", role=Role.RECRUITER, company=acme),
        rec2=make_user(db, email="rec2@acme.test", role=Role.RECRUITER, company=acme),
        interviewer=make_user(db, email="int@acme.test", role=Role.INTERVIEWER, company=acme),
        engineering=make_department(db, acme, "Engineering"),
        archived=archived,
        globex_admin=make_user(
            db, email="admin@globex.test", role=Role.COMPANY_ADMIN, company=globex
        ),
        globex_rec=make_user(db, email="rec@globex.test", role=Role.RECRUITER, company=globex),
        globex_dept=make_department(db, globex, "Globex Eng"),
    )
    db.commit()
    return built


def job_body(department: Department, **overrides: Any) -> dict[str, Any]:
    body = {
        "title": "Backend Engineer",
        "location": "Remote",
        "description": "Build and run our services.",
        "department_id": str(department.id),
    }
    return {**body, **overrides}


def create_job(browser: Browser, department: Department, **overrides: Any) -> Response:
    return browser.send("POST", "/api/jobs", json=job_body(department, **overrides))


def audit_actions(db: Session) -> list[str]:
    db.expire_all()
    return list(db.scalars(select(AuditLog.action).order_by(AuditLog.created_at, AuditLog.id)))


def stored(db: Session, job_id: str) -> Job:
    db.expire_all()
    job = db.get(Job, uuid.UUID(job_id))
    assert job is not None
    return job


def recruiter_ids(db: Session, job_id: str) -> set[str]:
    db.expire_all()
    rows = db.scalars(select(JobRecruiter.user_id).where(JobRecruiter.job_id == uuid.UUID(job_id)))
    return {str(row) for row in rows}


def draft_with(db: Session, world: World, *recruiters: User, title: str = "Backend") -> Job:
    job = make_job(
        db,
        company=world.acme,
        department=world.engineering,
        created_by=world.admin,
        recruiters=list(recruiters),
        title=title,
    )
    db.commit()
    return job


# ---- creating ----------------------------------------------------------------------------


def test_a_recruiter_creates_a_draft_and_is_assigned_to_it(
    client: TestClient, db: Session, world: World
) -> None:
    response = create_job(Browser(client, db, world.rec1), world.engineering)

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "draft" and body["version"] == 1
    assert body["opened_at"] is None and body["closed_at"] is None
    assert body["department"]["name"] == "Engineering"
    assert [r["id"] for r in body["recruiters"]] == [str(world.rec1.id)]
    assert audit_actions(db) == ["job.created"]


def test_an_admin_creates_a_draft_without_being_assigned(
    client: TestClient, db: Session, world: World
) -> None:
    # An admin is not a recruiter: they add recruiters afterwards.
    response = create_job(Browser(client, db, world.admin), world.engineering)

    assert response.status_code == 201
    assert response.json()["recruiters"] == []
    assert response.json()["needs_reassignment"] is True


@pytest.mark.parametrize(
    "bad",
    [
        {"title": ""},
        {"title": "   "},
        {"title": "x" * 201},
        {"location": ""},
        {"description": ""},
        {"description": "x" * 20_001},
        {"status": "open"},
        {"company_id": str(uuid.uuid4())},
        {"created_by": str(uuid.uuid4())},
    ],
)
def test_bad_input_is_refused_and_nothing_is_written(
    client: TestClient, db: Session, world: World, bad: dict[str, Any]
) -> None:
    response = create_job(Browser(client, db, world.rec1), world.engineering, **bad)

    assert response.status_code == 422
    assert audit_actions(db) == []
    assert db.scalar(select(func.count()).select_from(Job)) == 0


def test_the_limits_themselves_are_allowed(client: TestClient, db: Session, world: World) -> None:
    response = create_job(
        Browser(client, db, world.rec1),
        world.engineering,
        title="x" * 200,
        location="y" * 200,
        description="z" * 20_000,
    )

    assert response.status_code == 201


def test_text_is_trimmed(client: TestClient, db: Session, world: World) -> None:
    response = create_job(Browser(client, db, world.rec1), world.engineering, title="  Designer ")

    assert response.json()["title"] == "Designer"


def test_a_department_of_another_company_unknown_or_archived_cannot_be_used(
    client: TestClient, db: Session, world: World
) -> None:
    recruiter = Browser(client, db, world.rec1)

    foreign = create_job(recruiter, world.globex_dept)
    unknown = recruiter.send(
        "POST", "/api/jobs", json=job_body(world.engineering, department_id=str(uuid.uuid4()))
    )
    archived = create_job(recruiter, world.archived)

    assert foreign.status_code == unknown.status_code == 422
    assert foreign.json() == unknown.json()  # a foreign id looks exactly like an unknown one
    assert archived.status_code == 422
    assert archived.json()["code"] == "department_archived"
    assert audit_actions(db) == []


def test_an_interviewer_cannot_create_a_job(client: TestClient, db: Session, world: World) -> None:
    response = create_job(Browser(client, db, world.interviewer), world.engineering)

    assert response.status_code == 403


# ---- who sees which jobs -----------------------------------------------------------------


def test_an_admin_sees_every_job_of_the_company_and_no_other(
    client: TestClient, db: Session, world: World
) -> None:
    mine = draft_with(db, world, world.rec1, title="One")
    also_mine = draft_with(db, world, title="Two (nobody assigned)")
    make_job(
        db,
        company=world.globex,
        department=world.globex_dept,
        created_by=world.globex_admin,
        recruiters=[world.globex_rec],
    )
    db.commit()

    body = Browser(client, db, world.admin).get("/api/jobs").json()

    assert {item["id"] for item in body["items"]} == {str(mine.id), str(also_mine.id)}
    assert body["total"] == 2


def test_a_recruiter_sees_only_jobs_assigned_to_them(
    client: TestClient, db: Session, world: World
) -> None:
    assigned = draft_with(db, world, world.rec1, title="Mine")
    draft_with(db, world, world.rec2, title="Someone else's")
    draft_with(db, world, title="Nobody's")

    body = Browser(client, db, world.rec1).get("/api/jobs").json()

    assert [item["id"] for item in body["items"]] == [str(assigned.id)]
    assert body["total"] == 1


def test_a_second_recruiter_sees_a_job_only_after_being_assigned(
    client: TestClient, db: Session, world: World
) -> None:
    job_id = create_job(Browser(client, db, world.rec1), world.engineering).json()["id"]
    second = Browser(client, db, world.rec2)
    assert second.get("/api/jobs").json()["items"] == []
    assert second.get(f"/api/jobs/{job_id}").status_code == 404

    Browser(client, db, world.rec1).send(
        "POST", f"/api/jobs/{job_id}/recruiters", json={"user_id": str(world.rec2.id)}
    )

    second = Browser(client, db, world.rec2)
    assert [item["id"] for item in second.get("/api/jobs").json()["items"]] == [job_id]
    assert second.get(f"/api/jobs/{job_id}").status_code == 200


def test_the_list_is_newest_first_filterable_and_paginated(
    client: TestClient, db: Session, world: World
) -> None:
    admin = Browser(client, db, world.admin)
    ids = [create_job(admin, world.engineering, title=f"Job {n}").json()["id"] for n in range(5)]
    admin.send("POST", f"/api/jobs/{ids[0]}/recruiters", json={"user_id": str(world.rec1.id)})
    admin.send("POST", f"/api/jobs/{ids[0]}/publish", json={"version": 1})

    everything = admin.get("/api/jobs?page_size=2").json()
    only_open = admin.get("/api/jobs?status=open").json()
    in_dept = admin.get(f"/api/jobs?department_id={world.archived.id}").json()
    last_page = admin.get("/api/jobs?page=3&page_size=2").json()

    assert [i["id"] for i in everything["items"]] == [ids[4], ids[3]]  # newest first
    assert everything["total"] == 5 and everything["page_size"] == 2
    assert [i["id"] for i in only_open["items"]] == [ids[0]]
    assert in_dept == {"items": [], "total": 0, "page": 1, "page_size": 20}
    assert [i["id"] for i in last_page["items"]] == [ids[0]]


@pytest.mark.parametrize("query", ["status=nonsense", "department_id=x", "page=0", "page_size=101"])
def test_bad_list_parameters_are_refused(
    client: TestClient, db: Session, world: World, query: str
) -> None:
    assert Browser(client, db, world.admin).get(f"/api/jobs?{query}").status_code == 422


def test_the_list_costs_the_same_number_of_queries_however_many_jobs_there_are(
    client: TestClient, db: Session, scratch_engine: Engine, world: World
) -> None:
    admin = Browser(client, db, world.admin)
    counter = {"queries": 0}

    def count(*_args: object) -> None:
        counter["queries"] += 1

    def queries_for_one_list_request() -> int:
        counter["queries"] = 0
        event.listen(scratch_engine, "before_cursor_execute", count)
        try:
            assert admin.get("/api/jobs?page_size=100").status_code == 200
        finally:
            event.remove(scratch_engine, "before_cursor_execute", count)
        return counter["queries"]

    for n in range(3):
        draft_with(db, world, world.rec1, title=f"A{n}")
    few = queries_for_one_list_request()
    for n in range(30):
        draft_with(db, world, world.rec1, title=f"B{n}")
    many = queries_for_one_list_request()

    assert few == many


def test_the_list_flags_jobs_that_need_a_new_recruiter(
    client: TestClient, db: Session, world: World
) -> None:
    draft_with(db, world, world.rec1, title="Covered")
    draft_with(db, world, world.rec2, title="Orphaned")
    make_job(
        db,
        company=world.acme,
        department=world.engineering,
        created_by=world.admin,
        recruiters=[world.rec2],
        status=PostingStatus.CLOSED,
        title="Closed",
    )
    world.rec2.is_active = False  # deactivated: their assignment rows stay
    db.commit()

    items = {
        item["title"]: item["needs_reassignment"]
        for item in Browser(client, db, world.admin).get("/api/jobs").json()["items"]
    }

    assert items == {"Covered": False, "Orphaned": True, "Closed": False}


# ---- reading one job ---------------------------------------------------------------------


def test_the_detail_shows_the_department_and_recruiters(
    client: TestClient, db: Session, world: World
) -> None:
    job = draft_with(db, world, world.rec1)

    body = Browser(client, db, world.rec1).get(f"/api/jobs/{job.id}").json()

    assert body["department"] == {
        "id": str(world.engineering.id),
        "name": "Engineering",
        "is_archived": False,
    }
    assert [(r["id"], r["full_name"], r["is_active"]) for r in body["recruiters"]] == [
        (str(world.rec1.id), world.rec1.full_name, True)
    ]
    assert body["description"] == "Build and run our services."


def test_an_unassigned_recruiter_another_company_and_an_unknown_id_all_get_not_found(
    client: TestClient, db: Session, world: World
) -> None:
    job = draft_with(db, world, world.rec1)

    unassigned = Browser(client, db, world.rec2).get(f"/api/jobs/{job.id}")
    foreign = Browser(client, db, world.globex_admin).get(f"/api/jobs/{job.id}")
    unknown = Browser(client, db, world.admin).get(f"/api/jobs/{uuid.uuid4()}")

    for response in (unassigned, foreign, unknown):
        assert response.status_code == 404 and response.json() == NOT_FOUND


# ---- editing -----------------------------------------------------------------------------


def edit(browser: Browser, job_id: str | uuid.UUID, **body: Any) -> Response:
    return browser.send("PATCH", f"/api/jobs/{job_id}", json=body)


def test_editing_changes_the_job_and_raises_the_version(
    client: TestClient, db: Session, world: World
) -> None:
    job = draft_with(db, world, world.rec1)

    response = edit(
        Browser(client, db, world.rec1), job.id, version=1, title="Staff Engineer", location="Oslo"
    )

    assert response.status_code == 200
    assert response.json()["title"] == "Staff Engineer" and response.json()["version"] == 2
    assert stored(db, str(job.id)).location == "Oslo"
    assert audit_actions(db) == ["job.updated"]


def test_the_audit_row_names_the_changed_fields_but_never_the_text(
    client: TestClient, db: Session, world: World
) -> None:
    job = draft_with(db, world, world.rec1)

    edit(Browser(client, db, world.rec1), job.id, version=1, description="A very private text.")

    row = db.scalars(select(AuditLog).where(AuditLog.action == "job.updated")).one()
    assert row.new_value == {"fields": ["description"]}
    assert "private" not in str(row.old_value) + str(row.new_value)


def test_an_edit_quoting_an_old_version_is_a_conflict_and_changes_nothing(
    client: TestClient, db: Session, world: World
) -> None:
    job = draft_with(db, world, world.rec1)
    recruiter = Browser(client, db, world.rec1)
    edit(recruiter, job.id, version=1, title="First writer")

    response = edit(recruiter, job.id, version=1, title="Second writer")

    assert response.status_code == 409
    assert response.json()["code"] == "version_conflict"
    assert stored(db, str(job.id)).title == "First writer"
    assert audit_actions(db) == ["job.updated"]


def test_an_edit_that_changes_nothing_keeps_the_version_and_writes_no_audit_row(
    client: TestClient, db: Session, world: World
) -> None:
    job = draft_with(db, world, world.rec1)

    response = edit(Browser(client, db, world.rec1), job.id, version=1, title=job.title)

    assert response.status_code == 200 and response.json()["version"] == 1
    assert audit_actions(db) == []


def test_the_version_is_required_and_other_fields_are_refused(
    client: TestClient, db: Session, world: World
) -> None:
    job = draft_with(db, world, world.rec1)
    recruiter = Browser(client, db, world.rec1)

    assert edit(recruiter, job.id, title="No version").status_code == 422
    assert edit(recruiter, job.id, version=1, status="open").status_code == 422
    assert edit(recruiter, job.id, version=1, company_id=str(uuid.uuid4())).status_code == 422
    assert edit(recruiter, job.id, version=0, title="Zero").status_code == 422


def test_an_open_job_can_be_edited_but_a_closed_one_cannot(
    client: TestClient, db: Session, world: World
) -> None:
    job_id = create_job(Browser(client, db, world.rec1), world.engineering).json()["id"]
    recruiter = Browser(client, db, world.rec1)
    recruiter.send("POST", f"/api/jobs/{job_id}/publish", json={"version": 1})

    assert edit(recruiter, job_id, version=2, title="Edited while open").status_code == 200
    recruiter.send("POST", f"/api/jobs/{job_id}/close", json={"version": 3})
    response = edit(recruiter, job_id, version=4, title="Too late")

    assert response.status_code == 409 and response.json()["code"] == "job_closed"


def test_the_department_can_change_to_a_usable_one_only(
    client: TestClient, db: Session, world: World
) -> None:
    job = draft_with(db, world, world.rec1)
    other = make_department(db, world.acme, "Sales")
    db.commit()
    recruiter = Browser(client, db, world.rec1)

    to_archived = edit(recruiter, job.id, version=1, department_id=str(world.archived.id))
    to_foreign = edit(recruiter, job.id, version=1, department_id=str(world.globex_dept.id))
    to_other = edit(recruiter, job.id, version=1, department_id=str(other.id))

    assert to_archived.status_code == 422 and to_archived.json()["code"] == "department_archived"
    assert to_foreign.status_code == 422
    assert to_other.status_code == 200 and to_other.json()["department"]["name"] == "Sales"


def test_a_job_may_keep_a_department_that_was_archived_after_it_was_chosen(
    client: TestClient, db: Session, world: World
) -> None:
    job = draft_with(db, world, world.rec1)
    world.engineering.is_archived = True
    db.commit()

    response = edit(Browser(client, db, world.rec1), job.id, version=1, title="Still editable")

    assert response.status_code == 200


def test_only_people_who_can_see_the_job_can_edit_it(
    client: TestClient, db: Session, world: World
) -> None:
    job = draft_with(db, world, world.rec1)

    assert edit(Browser(client, db, world.rec2), job.id, version=1, title="x").status_code == 404
    assert (
        edit(Browser(client, db, world.globex_admin), job.id, version=1, title="x").status_code
        == 404
    )
    assert stored(db, str(job.id)).title == "Backend"
    assert (
        edit(Browser(client, db, world.admin), job.id, version=1, title="By admin").status_code
        == 200
    )


# ---- publishing and closing --------------------------------------------------------------


def post(browser: Browser, job_id: str | uuid.UUID, action: str, version: int) -> Response:
    return browser.send("POST", f"/api/jobs/{job_id}/{action}", json={"version": version})


def test_publishing_opens_the_job(client: TestClient, db: Session, world: World) -> None:
    job = draft_with(db, world, world.rec1)

    response = post(Browser(client, db, world.rec1), job.id, "publish", 1)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "open" and body["version"] == 2 and body["opened_at"] is not None
    assert audit_actions(db) == ["job.published"]


def test_a_job_without_an_active_recruiter_cannot_be_published(
    client: TestClient, db: Session, world: World
) -> None:
    nobody = draft_with(db, world)
    only_inactive = draft_with(db, world, world.rec2)
    world.rec2.is_active = False
    db.commit()
    admin = Browser(client, db, world.admin)

    for job in (nobody, only_inactive):
        response = post(admin, job.id, "publish", 1)
        assert response.status_code == 409 and response.json()["code"] == "no_recruiter"
        assert stored(db, str(job.id)).status == PostingStatus.DRAFT
    assert audit_actions(db) == []


def test_publishing_an_open_job_again_changes_nothing(
    client: TestClient, db: Session, world: World
) -> None:
    job = draft_with(db, world, world.rec1)
    recruiter = Browser(client, db, world.rec1)
    post(recruiter, job.id, "publish", 1)

    again = post(recruiter, job.id, "publish", 1)  # a double click quotes the old version

    assert again.status_code == 200 and again.json()["version"] == 2
    assert audit_actions(db) == ["job.published"]


def test_a_closed_job_cannot_be_reopened(client: TestClient, db: Session, world: World) -> None:
    job = draft_with(db, world, world.rec1)
    recruiter = Browser(client, db, world.rec1)
    post(recruiter, job.id, "publish", 1)
    post(recruiter, job.id, "close", 2)

    response = post(recruiter, job.id, "publish", 3)

    assert response.status_code == 409 and response.json()["code"] == "job_closed"
    assert stored(db, str(job.id)).status == PostingStatus.CLOSED


def test_publishing_with_an_old_version_is_a_conflict(
    client: TestClient, db: Session, world: World
) -> None:
    job = draft_with(db, world, world.rec1)
    recruiter = Browser(client, db, world.rec1)
    edit(recruiter, job.id, version=1, title="Edited meanwhile")

    response = post(recruiter, job.id, "publish", 1)

    assert response.status_code == 409 and response.json()["code"] == "version_conflict"
    assert stored(db, str(job.id)).status == PostingStatus.DRAFT


def test_closing_ends_an_open_job_and_keeps_when_it_opened(
    client: TestClient, db: Session, world: World
) -> None:
    job = draft_with(db, world, world.rec1)
    recruiter = Browser(client, db, world.rec1)
    opened = post(recruiter, job.id, "publish", 1).json()["opened_at"]

    response = post(recruiter, job.id, "close", 2)

    body = response.json()
    assert response.status_code == 200 and body["status"] == "closed" and body["version"] == 3
    assert body["closed_at"] is not None and body["opened_at"] == opened
    assert audit_actions(db) == ["job.published", "job.closed"]


def test_closing_a_closed_job_changes_nothing(
    client: TestClient, db: Session, world: World
) -> None:
    job = draft_with(db, world, world.rec1)
    recruiter = Browser(client, db, world.rec1)
    post(recruiter, job.id, "publish", 1)
    post(recruiter, job.id, "close", 2)

    again = post(recruiter, job.id, "close", 2)

    assert again.status_code == 200 and again.json()["version"] == 3
    assert audit_actions(db).count("job.closed") == 1


def test_a_draft_cannot_be_closed(client: TestClient, db: Session, world: World) -> None:
    job = draft_with(db, world, world.rec1)

    response = post(Browser(client, db, world.rec1), job.id, "close", 1)

    assert response.status_code == 409 and response.json()["code"] == "draft_cannot_close"


@pytest.mark.parametrize("action", ["publish", "close"])
def test_status_changes_are_not_found_for_those_who_cannot_see_the_job(
    client: TestClient, db: Session, world: World, action: str
) -> None:
    job = draft_with(db, world, world.rec1)

    assert post(Browser(client, db, world.rec2), job.id, action, 1).status_code == 404
    assert post(Browser(client, db, world.globex_admin), job.id, action, 1).status_code == 404
    assert stored(db, str(job.id)).status == PostingStatus.DRAFT


# ---- deleting a draft --------------------------------------------------------------------


def test_a_draft_can_be_deleted_with_its_recruiter_rows(
    client: TestClient, db: Session, world: World
) -> None:
    job = draft_with(db, world, world.rec1, world.rec2)
    job_id = str(job.id)

    response = Browser(client, db, world.rec1).send("DELETE", f"/api/jobs/{job_id}")

    assert response.status_code == 204
    assert db.get(Job, job.id) is None and recruiter_ids(db, job_id) == set()
    assert audit_actions(db) == ["job.deleted"]


@pytest.mark.parametrize("final_status", [PostingStatus.OPEN, PostingStatus.CLOSED])
def test_only_a_draft_can_be_deleted(
    client: TestClient, db: Session, world: World, final_status: PostingStatus
) -> None:
    job = make_job(
        db,
        company=world.acme,
        department=world.engineering,
        created_by=world.admin,
        recruiters=[world.rec1],
        status=final_status,
    )
    db.commit()

    response = Browser(client, db, world.rec1).send("DELETE", f"/api/jobs/{job.id}")

    assert response.status_code == 409 and response.json()["code"] == "only_drafts_deletable"
    assert db.get(Job, job.id) is not None


def test_nobody_outside_the_job_can_delete_it(
    client: TestClient, db: Session, world: World
) -> None:
    job = draft_with(db, world, world.rec1)

    assert Browser(client, db, world.rec2).send("DELETE", f"/api/jobs/{job.id}").status_code == 404
    assert (
        Browser(client, db, world.globex_admin).send("DELETE", f"/api/jobs/{job.id}").status_code
        == 404
    )
    assert db.get(Job, job.id) is not None


# ---- assigning recruiters ----------------------------------------------------------------


def assign(browser: Browser, job_id: str | uuid.UUID, user_id: str | uuid.UUID) -> Response:
    return browser.send("POST", f"/api/jobs/{job_id}/recruiters", json={"user_id": str(user_id)})


def unassign(browser: Browser, job_id: str | uuid.UUID, user_id: str | uuid.UUID) -> Response:
    return browser.send("DELETE", f"/api/jobs/{job_id}/recruiters/{user_id}")


def test_an_admin_or_an_assigned_recruiter_can_add_a_recruiter(
    client: TestClient, db: Session, world: World
) -> None:
    job = draft_with(db, world, world.rec1)
    third = make_user(db, email="rec3@acme.test", role=Role.RECRUITER, company=world.acme)
    db.commit()

    by_admin = assign(Browser(client, db, world.admin), job.id, world.rec2.id)
    by_recruiter = assign(Browser(client, db, world.rec1), job.id, third.id)

    assert by_admin.status_code == by_recruiter.status_code == 200
    assert recruiter_ids(db, str(job.id)) == {
        str(world.rec1.id),
        str(world.rec2.id),
        str(third.id),
    }
    assert audit_actions(db) == ["job.recruiter_added", "job.recruiter_added"]


def test_adding_someone_already_assigned_changes_nothing(
    client: TestClient, db: Session, world: World
) -> None:
    job = draft_with(db, world, world.rec1)

    response = assign(Browser(client, db, world.admin), job.id, world.rec1.id)

    assert response.status_code == 200
    assert audit_actions(db) == []


def test_an_unassigned_recruiter_cannot_add_anyone(
    client: TestClient, db: Session, world: World
) -> None:
    job = draft_with(db, world, world.rec1)

    response = assign(Browser(client, db, world.rec2), job.id, world.rec2.id)

    assert response.status_code == 404
    assert recruiter_ids(db, str(job.id)) == {str(world.rec1.id)}


def test_only_an_active_recruiter_of_the_same_company_can_be_assigned(
    client: TestClient, db: Session, world: World
) -> None:
    job = draft_with(db, world, world.rec1)
    deactivated = make_user(db, email="gone@acme.test", role=Role.RECRUITER, company=world.acme)
    deactivated.is_active = False
    candidate = make_user(db, email="cand@example.test", role=Role.CANDIDATE, company=None)
    db.commit()
    admin = Browser(client, db, world.admin)

    responses = [
        assign(admin, job.id, person.id)
        for person in (
            world.interviewer,
            world.admin,
            deactivated,
            candidate,
            world.globex_rec,
        )
    ] + [assign(admin, job.id, uuid.uuid4())]

    assert {r.status_code for r in responses} == {422}
    assert all(r.json()["code"] == "invalid_recruiter" for r in responses)
    # A foreign recruiter looks exactly like an unknown id.
    assert responses[4].json() == responses[5].json()
    assert recruiter_ids(db, str(job.id)) == {str(world.rec1.id)}
    assert audit_actions(db) == []


def test_removing_a_recruiter_from_a_draft_is_always_allowed(
    client: TestClient, db: Session, world: World
) -> None:
    job = draft_with(db, world, world.rec1)

    response = unassign(Browser(client, db, world.admin), job.id, world.rec1.id)

    assert response.status_code == 204
    assert recruiter_ids(db, str(job.id)) == set()
    assert audit_actions(db) == ["job.recruiter_removed"]


def test_an_open_job_keeps_at_least_one_active_recruiter(
    client: TestClient, db: Session, world: World
) -> None:
    job = draft_with(db, world, world.rec1, world.rec2)
    admin = Browser(client, db, world.admin)
    post(admin, job.id, "publish", 1)

    first = unassign(admin, job.id, world.rec1.id)
    last = unassign(admin, job.id, world.rec2.id)

    assert first.status_code == 204
    assert last.status_code == 409 and last.json()["code"] == "last_recruiter"
    assert recruiter_ids(db, str(job.id)) == {str(world.rec2.id)}


def test_a_deactivated_recruiter_does_not_count_as_the_one_who_stays(
    client: TestClient, db: Session, world: World
) -> None:
    job = draft_with(db, world, world.rec1, world.rec2)
    admin = Browser(client, db, world.admin)
    post(admin, job.id, "publish", 1)
    world.rec2.is_active = False
    db.commit()

    # rec1 is the only active recruiter left, so rec1 cannot be removed...
    refused = unassign(admin, job.id, world.rec1.id)
    # ...but the deactivated one can be cleaned up.
    cleaned = unassign(admin, job.id, world.rec2.id)

    assert refused.status_code == 409 and refused.json()["code"] == "last_recruiter"
    assert cleaned.status_code == 204


def test_a_closed_job_has_no_last_recruiter_rule(
    client: TestClient, db: Session, world: World
) -> None:
    job = draft_with(db, world, world.rec1)
    admin = Browser(client, db, world.admin)
    post(admin, job.id, "publish", 1)
    post(admin, job.id, "close", 2)

    assert unassign(admin, job.id, world.rec1.id).status_code == 204


def test_removing_someone_who_is_not_assigned_changes_nothing(
    client: TestClient, db: Session, world: World
) -> None:
    job = draft_with(db, world, world.rec1)

    response = unassign(Browser(client, db, world.admin), job.id, world.rec2.id)

    assert response.status_code == 204
    assert audit_actions(db) == []


def test_a_recruiter_who_removes_themselves_loses_sight_of_the_job(
    client: TestClient, db: Session, world: World
) -> None:
    job = draft_with(db, world, world.rec1, world.rec2)
    recruiter = Browser(client, db, world.rec1)

    assert unassign(recruiter, job.id, world.rec1.id).status_code == 204

    assert recruiter.get(f"/api/jobs/{job.id}").status_code == 404


def test_an_unassigned_recruiter_cannot_remove_anyone(
    client: TestClient, db: Session, world: World
) -> None:
    job = draft_with(db, world, world.rec1)

    response = unassign(Browser(client, db, world.rec2), job.id, world.rec1.id)

    assert response.status_code == 404
    assert recruiter_ids(db, str(job.id)) == {str(world.rec1.id)}
