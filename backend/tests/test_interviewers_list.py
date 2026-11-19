"""The list of interviewers a recruiter picks from when scheduling an interview.

Like the recruiters list (test_recruiters.py): only active people with the Interviewer role in the
caller's own company, and nothing but what a picker shows. Only recruiters schedule, so only they
get it.
"""

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Role, User
from tests.browser import Browser
from tests.factories import make_company, make_user


@dataclass
class World:
    admin: User
    recruiter: User
    int_ann: User
    int_bob: User
    deactivated: User
    interviewer_elsewhere: User
    cara_like: User


@pytest.fixture
def world(db: Session) -> World:
    acme, globex = make_company(db, "Acme"), make_company(db, "Globex")
    deactivated = make_user(
        db, email="gone@acme.test", role=Role.INTERVIEWER, company=acme, full_name="Gone Away"
    )
    deactivated.is_active = False
    built = World(
        admin=make_user(db, email="admin@acme.test", role=Role.COMPANY_ADMIN, company=acme),
        recruiter=make_user(db, email="rec@acme.test", role=Role.RECRUITER, company=acme),
        int_ann=make_user(
            db, email="ann@acme.test", role=Role.INTERVIEWER, company=acme, full_name="Ann Active"
        ),
        int_bob=make_user(
            db, email="bob@acme.test", role=Role.INTERVIEWER, company=acme, full_name="bob Bold"
        ),
        deactivated=deactivated,
        interviewer_elsewhere=make_user(
            db, email="int@globex.test", role=Role.INTERVIEWER, company=globex, full_name="Globex"
        ),
        cara_like=make_user(db, email="rec2@acme.test", role=Role.RECRUITER, company=acme),
    )
    db.commit()
    return built


def test_a_recruiter_sees_the_active_interviewers_of_their_company_by_name(
    client: TestClient, db: Session, world: World
) -> None:
    response = Browser(client, db, world.recruiter).get("/api/interviewers")

    assert response.status_code == 200
    body = response.json()
    # By name regardless of case; no deactivated person, no recruiter or admin, no other company.
    assert [person["email"] for person in body["items"]] == ["ann@acme.test", "bob@acme.test"]
    assert body["total"] == 2 and body["page"] == 1 and body["page_size"] == 20


def test_only_the_fields_a_picker_needs_are_shown(
    client: TestClient, db: Session, world: World
) -> None:
    item = Browser(client, db, world.recruiter).get("/api/interviewers").json()["items"][0]

    assert set(item) == {"id", "full_name", "email"}


def test_the_list_is_paged(client: TestClient, db: Session, world: World) -> None:
    browser = Browser(client, db, world.recruiter)

    first = browser.get("/api/interviewers?page=1&page_size=1").json()
    second = browser.get("/api/interviewers?page=2&page_size=1").json()

    assert first["total"] == 2 and [p["email"] for p in first["items"]] == ["ann@acme.test"]
    assert [p["email"] for p in second["items"]] == ["bob@acme.test"]


def test_a_company_with_no_interviewers_gets_an_empty_list(client: TestClient, db: Session) -> None:
    lonely = make_company(db, "Lonely")
    recruiter = make_user(db, email="rec@lonely.test", role=Role.RECRUITER, company=lonely)
    db.commit()

    body = Browser(client, db, recruiter).get("/api/interviewers").json()

    assert body["items"] == [] and body["total"] == 0


@pytest.mark.parametrize("who", ["admin", "int_ann"])
def test_only_recruiters_get_the_list(
    client: TestClient, db: Session, world: World, who: str
) -> None:
    assert Browser(client, db, getattr(world, who)).get("/api/interviewers").status_code == 403


def test_a_visitor_is_not_logged_in(client: TestClient, db: Session, world: World) -> None:
    client.cookies.clear()

    assert client.get("/api/interviewers").status_code == 401
