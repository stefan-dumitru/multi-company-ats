"""Departments (data-model.md > Department): an admin manages them, staff can pick from them.

Rules under test: names are unique per company (ignoring case and surrounding spaces), departments
are archived rather than deleted, every list is paginated, and a department of another company is
"not found". Every change writes its audit row in the same transaction.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.sessions import SESSION_COOKIE_NAME, create_session
from app.models import AuditLog, Role, User
from tests.factories import make_company, make_user

NOT_FOUND = {"detail": "Not found."}
DUPLICATE = {"detail": "A department with this name already exists."}


@dataclass
class World:
    acme_admin: User
    acme_recruiter: User
    acme_interviewer: User
    globex_admin: User


@pytest.fixture
def world(db: Session) -> World:
    acme, globex = make_company(db, "Acme"), make_company(db, "Globex")
    built = World(
        acme_admin=make_user(db, email="admin@acme.test", role=Role.COMPANY_ADMIN, company=acme),
        acme_recruiter=make_user(db, email="rec@acme.test", role=Role.RECRUITER, company=acme),
        acme_interviewer=make_user(db, email="int@acme.test", role=Role.INTERVIEWER, company=acme),
        globex_admin=make_user(
            db, email="admin@globex.test", role=Role.COMPANY_ADMIN, company=globex
        ),
    )
    db.commit()
    return built


class Browser:
    """The test client logged in as one user."""

    def __init__(self, client: TestClient, db: Session, user: User) -> None:
        token, session = create_session(db, user, datetime.now(UTC))
        db.commit()
        client.cookies.clear()
        client.cookies.set(SESSION_COOKIE_NAME, token)
        self.client = client
        self.csrf = session.csrf_token

    def get(self, path: str) -> Response:
        return self.client.get(path)

    def send(self, method: str, path: str, **kwargs: object) -> Response:
        return self.client.request(
            method,
            path,
            headers={"X-CSRF-Token": self.csrf},
            **kwargs,  # type: ignore[arg-type]
        )

    def create(self, name: str) -> Response:
        return self.send("POST", "/api/departments", json={"name": name})


def audit_actions(db: Session) -> list[str]:
    db.expire_all()
    return list(db.scalars(select(AuditLog.action).order_by(AuditLog.created_at, AuditLog.id)))


# ---- creating ----------------------------------------------------------------------------


def test_an_admin_creates_a_department(client: TestClient, db: Session, world: World) -> None:
    admin = Browser(client, db, world.acme_admin)

    response = admin.create("Engineering")

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Engineering" and body["is_archived"] is False
    assert uuid.UUID(body["id"])
    assert audit_actions(db) == ["department.created"]


def test_the_name_is_trimmed(client: TestClient, db: Session, world: World) -> None:
    admin = Browser(client, db, world.acme_admin)

    assert admin.create("   Sales  ").json()["name"] == "Sales"


@pytest.mark.parametrize("bad_name", ["", "   ", "x" * 101])
def test_a_missing_or_overlong_name_is_refused(
    client: TestClient, db: Session, world: World, bad_name: str
) -> None:
    admin = Browser(client, db, world.acme_admin)

    assert admin.create(bad_name).status_code == 422
    assert audit_actions(db) == []


def test_unknown_fields_are_refused(client: TestClient, db: Session, world: World) -> None:
    admin = Browser(client, db, world.acme_admin)

    # A company id in the body must never be trusted, or silently ignored.
    response = admin.send(
        "POST", "/api/departments", json={"name": "Ops", "company_id": str(uuid.uuid4())}
    )

    assert response.status_code == 422


@pytest.mark.parametrize("second_name", ["Engineering", "engineering", "  ENGINEERING "])
def test_a_name_is_unique_within_a_company_ignoring_case(
    client: TestClient, db: Session, world: World, second_name: str
) -> None:
    admin = Browser(client, db, world.acme_admin)
    admin.create("Engineering")

    response = admin.create(second_name)

    assert response.status_code == 409
    assert response.json() == DUPLICATE
    assert audit_actions(db) == ["department.created"]


def test_two_companies_may_use_the_same_name(client: TestClient, db: Session, world: World) -> None:
    Browser(client, db, world.acme_admin).create("Engineering")

    assert Browser(client, db, world.globex_admin).create("Engineering").status_code == 201


def test_a_recruiter_cannot_create_a_department(
    client: TestClient, db: Session, world: World
) -> None:
    recruiter = Browser(client, db, world.acme_recruiter)

    assert recruiter.create("Marketing").status_code == 403
    assert audit_actions(db) == []


# ---- listing -----------------------------------------------------------------------------


def test_staff_see_their_companys_departments_in_name_order(
    client: TestClient, db: Session, world: World
) -> None:
    admin = Browser(client, db, world.acme_admin)
    for name in ["Sales", "engineering", "Operations"]:
        admin.create(name)
    Browser(client, db, world.globex_admin).create("Globex only")

    for user in (world.acme_admin, world.acme_recruiter):
        response = Browser(client, db, user).get("/api/departments")

        assert response.status_code == 200
        body = response.json()
        assert [d["name"] for d in body["items"]] == ["engineering", "Operations", "Sales"]
        assert body["total"] == 3 and body["page"] == 1 and body["page_size"] == 20


def test_an_interviewer_cannot_list_departments(
    client: TestClient, db: Session, world: World
) -> None:
    assert Browser(client, db, world.acme_interviewer).get("/api/departments").status_code == 403


def test_an_empty_company_gets_an_empty_page(client: TestClient, db: Session, world: World) -> None:
    response = Browser(client, db, world.acme_admin).get("/api/departments")

    assert response.json() == {"items": [], "total": 0, "page": 1, "page_size": 20}


def test_lists_are_paginated(client: TestClient, db: Session, world: World) -> None:
    admin = Browser(client, db, world.acme_admin)
    for number in range(5):
        admin.create(f"Dept {number}")

    first = admin.get("/api/departments?page=1&page_size=2").json()
    last = admin.get("/api/departments?page=3&page_size=2").json()
    beyond = admin.get("/api/departments?page=4&page_size=2").json()

    assert [d["name"] for d in first["items"]] == ["Dept 0", "Dept 1"]
    assert [d["name"] for d in last["items"]] == ["Dept 4"]
    assert beyond["items"] == [] and beyond["total"] == 5


@pytest.mark.parametrize(
    "query", ["page=0", "page=-1", "page=10001", "page_size=0", "page_size=101", "page=x"]
)
def test_silly_page_numbers_are_refused(
    client: TestClient, db: Session, world: World, query: str
) -> None:
    assert Browser(client, db, world.acme_admin).get(f"/api/departments?{query}").status_code == 422


def test_the_largest_allowed_page_size_works(client: TestClient, db: Session, world: World) -> None:
    assert (
        Browser(client, db, world.acme_admin).get("/api/departments?page_size=100").status_code
        == 200
    )


# ---- renaming ----------------------------------------------------------------------------


def test_an_admin_renames_a_department(client: TestClient, db: Session, world: World) -> None:
    admin = Browser(client, db, world.acme_admin)
    department_id = admin.create("Eng").json()["id"]

    response = admin.send("PATCH", f"/api/departments/{department_id}", json={"name": "Platform"})

    assert response.status_code == 200
    assert response.json()["name"] == "Platform"
    assert audit_actions(db) == ["department.created", "department.renamed"]


def test_changing_only_the_capitalisation_is_allowed(
    client: TestClient, db: Session, world: World
) -> None:
    # The new name equals the old one ignoring case, but it is the same department, not a clash.
    admin = Browser(client, db, world.acme_admin)
    department_id = admin.create("engineering").json()["id"]

    response = admin.send(
        "PATCH", f"/api/departments/{department_id}", json={"name": "Engineering"}
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Engineering"


def test_renaming_to_another_departments_name_is_a_conflict(
    client: TestClient, db: Session, world: World
) -> None:
    admin = Browser(client, db, world.acme_admin)
    admin.create("Sales")
    department_id = admin.create("Ops").json()["id"]

    response = admin.send("PATCH", f"/api/departments/{department_id}", json={"name": "sales"})

    assert response.status_code == 409
    assert response.json() == DUPLICATE
    assert admin.get("/api/departments").json()["items"][0]["name"] == "Ops"


def test_renaming_to_the_same_name_changes_nothing_and_is_not_audited(
    client: TestClient, db: Session, world: World
) -> None:
    admin = Browser(client, db, world.acme_admin)
    department_id = admin.create("Sales").json()["id"]

    response = admin.send("PATCH", f"/api/departments/{department_id}", json={"name": "Sales"})

    assert response.status_code == 200
    assert audit_actions(db) == ["department.created"]


def test_a_recruiter_cannot_rename(client: TestClient, db: Session, world: World) -> None:
    department_id = Browser(client, db, world.acme_admin).create("Sales").json()["id"]
    recruiter = Browser(client, db, world.acme_recruiter)

    response = recruiter.send("PATCH", f"/api/departments/{department_id}", json={"name": "X"})

    assert response.status_code == 403


# ---- archiving ---------------------------------------------------------------------------


def test_archiving_hides_a_department_unless_asked_for(
    client: TestClient, db: Session, world: World
) -> None:
    admin = Browser(client, db, world.acme_admin)
    department_id = admin.create("Old team").json()["id"]
    admin.create("Current team")

    response = admin.send("POST", f"/api/departments/{department_id}/archive")

    assert response.status_code == 200 and response.json()["is_archived"] is True
    visible = admin.get("/api/departments").json()
    assert [d["name"] for d in visible["items"]] == ["Current team"] and visible["total"] == 1
    everything = admin.get("/api/departments?include_archived=true").json()
    assert [d["name"] for d in everything["items"]] == ["Current team", "Old team"]
    assert audit_actions(db) == ["department.created"] * 2 + ["department.archived"]


def test_a_department_can_be_brought_back(client: TestClient, db: Session, world: World) -> None:
    admin = Browser(client, db, world.acme_admin)
    department_id = admin.create("Old team").json()["id"]
    admin.send("POST", f"/api/departments/{department_id}/archive")

    response = admin.send("POST", f"/api/departments/{department_id}/unarchive")

    assert response.status_code == 200 and response.json()["is_archived"] is False
    assert [d["name"] for d in admin.get("/api/departments").json()["items"]] == ["Old team"]
    assert audit_actions(db)[-1] == "department.unarchived"


def test_repeating_an_archive_changes_nothing_and_writes_no_audit_row(
    client: TestClient, db: Session, world: World
) -> None:
    admin = Browser(client, db, world.acme_admin)
    department_id = admin.create("Old team").json()["id"]
    admin.send("POST", f"/api/departments/{department_id}/archive")

    again = admin.send("POST", f"/api/departments/{department_id}/archive")
    live_id = admin.create("Live").json()["id"]
    unarchive_active = admin.send("POST", f"/api/departments/{live_id}/unarchive")

    assert again.status_code == 200 and again.json()["is_archived"] is True
    assert unarchive_active.status_code == 200
    assert audit_actions(db).count("department.archived") == 1
    assert "department.unarchived" not in audit_actions(db)


def test_a_recruiter_cannot_archive(client: TestClient, db: Session, world: World) -> None:
    department_id = Browser(client, db, world.acme_admin).create("Sales").json()["id"]
    recruiter = Browser(client, db, world.acme_recruiter)

    assert recruiter.send("POST", f"/api/departments/{department_id}/archive").status_code == 403


# ---- other companies and unknown ids -----------------------------------------------------


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("PATCH", "", {"name": "Hijacked"}),
        ("POST", "/archive", None),
        ("POST", "/unarchive", None),
    ],
)
def test_another_companys_department_is_not_found(
    client: TestClient, db: Session, world: World, method: str, suffix: str, body: object
) -> None:
    foreign_id = Browser(client, db, world.globex_admin).create("Globex dept").json()["id"]
    admin = Browser(client, db, world.acme_admin)

    response = admin.send(method, f"/api/departments/{foreign_id}{suffix}", json=body)

    assert response.status_code == 404
    assert response.json() == NOT_FOUND
    unknown = admin.send(method, f"/api/departments/{uuid.uuid4()}{suffix}", json=body)
    assert unknown.json() == response.json()  # indistinguishable from an id that never existed
    assert audit_actions(db) == ["department.created"]  # only Globex's own creation
