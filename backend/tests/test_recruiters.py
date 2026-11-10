"""The list of recruiters a job screen picks from (functional.md: "a company admin or an
already-assigned recruiter can add others").

Admins already have the full user list; recruiters do not, so they need this narrower one: only
active recruiters of their own company, and nothing but what a picker shows.
"""

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Company, Role, User
from tests.browser import Browser
from tests.factories import make_company, make_user


@dataclass
class World:
    acme: Company
    admin: User
    rec_ann: User
    rec_bob: User
    deactivated: User
    interviewer: User
    globex_rec: User


@pytest.fixture
def world(db: Session) -> World:
    acme, globex = make_company(db, "Acme"), make_company(db, "Globex")
    deactivated = make_user(
        db, email="gone@acme.test", role=Role.RECRUITER, company=acme, full_name="Gone Away"
    )
    deactivated.is_active = False
    built = World(
        acme=acme,
        admin=make_user(db, email="admin@acme.test", role=Role.COMPANY_ADMIN, company=acme),
        rec_ann=make_user(
            db, email="ann@acme.test", role=Role.RECRUITER, company=acme, full_name="Ann Active"
        ),
        rec_bob=make_user(
            db, email="bob@acme.test", role=Role.RECRUITER, company=acme, full_name="bob Bold"
        ),
        deactivated=deactivated,
        interviewer=make_user(db, email="int@acme.test", role=Role.INTERVIEWER, company=acme),
        globex_rec=make_user(
            db, email="rec@globex.test", role=Role.RECRUITER, company=globex, full_name="Globex Gal"
        ),
    )
    db.commit()
    return built


def test_an_admin_and_a_recruiter_see_the_same_active_recruiters_of_their_company(
    client: TestClient, db: Session, world: World
) -> None:
    for viewer in (world.admin, world.rec_ann):
        response = Browser(client, db, viewer).get("/api/recruiters")

        assert response.status_code == 200
        body = response.json()
        assert [person["email"] for person in body["items"]] == ["ann@acme.test", "bob@acme.test"]
        assert body["total"] == 2 and body["page"] == 1 and body["page_size"] == 20


def test_only_the_fields_a_picker_needs_are_shown(
    client: TestClient, db: Session, world: World
) -> None:
    person = Browser(client, db, world.admin).get("/api/recruiters").json()["items"][0]

    assert set(person) == {"id", "full_name", "email", "is_active"}


def test_the_list_is_ordered_by_name_ignoring_case(
    client: TestClient, db: Session, world: World
) -> None:
    # A plain (case-sensitive) sort would put "adam Lower" after "Zoe Zed".
    for email, name in [("zoe@acme.test", "Zoe Zed"), ("adam@acme.test", "adam Lower")]:
        make_user(db, email=email, role=Role.RECRUITER, company=world.acme, full_name=name)
    db.commit()

    body = Browser(client, db, world.admin).get("/api/recruiters").json()

    assert [p["full_name"] for p in body["items"]] == [
        "adam Lower",
        "Ann Active",
        "bob Bold",
        "Zoe Zed",
    ]


def test_it_is_paginated(client: TestClient, db: Session, world: World) -> None:
    admin = Browser(client, db, world.admin)

    first = admin.get("/api/recruiters?page=1&page_size=1").json()
    second = admin.get("/api/recruiters?page=2&page_size=1").json()

    assert [p["email"] for p in first["items"]] == ["ann@acme.test"]
    assert [p["email"] for p in second["items"]] == ["bob@acme.test"]
    assert first["total"] == second["total"] == 2


@pytest.mark.parametrize("query", ["page=0", "page_size=0", "page_size=101"])
def test_silly_page_numbers_are_refused(
    client: TestClient, db: Session, world: World, query: str
) -> None:
    assert Browser(client, db, world.admin).get(f"/api/recruiters?{query}").status_code == 422


def test_an_interviewer_cannot_use_it(client: TestClient, db: Session, world: World) -> None:
    assert Browser(client, db, world.interviewer).get("/api/recruiters").status_code == 403


def test_it_needs_a_login(client: TestClient, world: World) -> None:
    assert client.get("/api/recruiters").status_code == 401
