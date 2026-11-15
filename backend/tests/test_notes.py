"""Internal notes on an application (data-model.md > Note).

The rules under test: only the assigned recruiters write notes; admins can read them; everyone else
is refused or sees "not found"; a note is append-only (no edit, no delete); the audit row records
that a note was added but never its text; and nothing a candidate can reach ever contains one.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Application, AuditLog, Company, Note, PostingStatus, Role, User
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
NOTE_FIELDS = {"id", "author_name", "body", "created_at"}


@dataclass
class World:
    acme: Company
    admin: User
    recruiter: User  # assigned to the job
    other_recruiter: User  # assigned to nothing
    interviewer: User
    cara: User
    application: Application
    other_application: Application  # a second application on the same job
    globex_recruiter: User


@pytest.fixture
def world(db: Session) -> World:
    acme, globex = make_company(db, "Acme"), make_company(db, "Globex")
    admin = make_user(db, email="admin@acme.test", role=Role.COMPANY_ADMIN, company=acme)
    recruiter = make_user(
        db, email="rec@acme.test", role=Role.RECRUITER, company=acme, full_name="Rae Recruiter"
    )
    other_recruiter = make_user(db, email="rec2@acme.test", role=Role.RECRUITER, company=acme)
    interviewer = make_user(db, email="int@acme.test", role=Role.INTERVIEWER, company=acme)
    job = make_job(
        db,
        company=acme,
        department=make_department(db, acme),
        created_by=admin,
        recruiters=[recruiter],
        status=PostingStatus.OPEN,
    )
    cara = make_candidate(db, email="cara@example.test", full_name="Cara Candidate")
    application = make_application(db, job=job, candidate=cara)
    other_application = make_application(
        db, job=job, candidate=make_candidate(db, email="dan@example.test")
    )
    globex_recruiter = make_user(db, email="rec@globex.test", role=Role.RECRUITER, company=globex)
    db.commit()
    return World(
        acme,
        admin,
        recruiter,
        other_recruiter,
        interviewer,
        cara,
        application,
        other_application,
        globex_recruiter,
    )


def add_note(
    browser: Browser, application: Application, body: str = "Strong on systems."
) -> Response:
    return browser.send("POST", f"/api/applications/{application.id}/notes", json={"body": body})


def notes_of(browser: Browser, application: Application, query: str = "") -> dict[str, Any]:
    response = browser.get(f"/api/applications/{application.id}/notes{query}")
    assert response.status_code == 200
    return dict(response.json())


# ---- writing ---------------------------------------------------------------------------------


def test_an_assigned_recruiter_adds_a_note(client: TestClient, db: Session, world: World) -> None:
    response = add_note(
        Browser(client, db, world.recruiter), world.application, "  Call on Friday.  "
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body) == NOTE_FIELDS
    assert body["body"] == "Call on Friday." and body["author_name"] == "Rae Recruiter"
    stored = db.scalars(select(Note)).one()
    assert stored.application_id == world.application.id
    assert stored.company_id == world.acme.id and stored.author_id == world.recruiter.id


def test_adding_a_note_is_audited_without_the_text(
    client: TestClient, db: Session, world: World
) -> None:
    secret = "Candidate mentioned a competing offer from Initech"

    add_note(Browser(client, db, world.recruiter), world.application, secret)

    db.expire_all()
    rows = list(db.scalars(select(AuditLog).where(AuditLog.action == "note.added")))
    assert len(rows) == 1
    assert rows[0].actor_user_id == world.recruiter.id and rows[0].company_id == world.acme.id
    assert rows[0].entity_type == "note"
    assert rows[0].new_value == {"application_id": str(world.application.id)}
    assert secret not in str([(row.old_value, row.new_value) for row in rows])


@pytest.mark.parametrize("body", ["", "   ", "\n\t "])
def test_a_blank_note_is_refused(client: TestClient, db: Session, world: World, body: str) -> None:
    response = add_note(Browser(client, db, world.recruiter), world.application, body)

    assert response.status_code == 422
    assert db.scalars(select(Note)).all() == []


def test_a_note_can_be_as_long_as_4000_characters_and_not_longer(
    client: TestClient, db: Session, world: World
) -> None:
    browser = Browser(client, db, world.recruiter)

    assert add_note(browser, world.application, "x" * 4000).status_code == 201
    assert add_note(browser, world.application, "x" * 4001).status_code == 422


def test_a_note_cannot_carry_other_fields(client: TestClient, db: Session, world: World) -> None:
    # Who wrote it, and where, come from the session and the address: never from the request.
    response = Browser(client, db, world.recruiter).send(
        "POST",
        f"/api/applications/{world.application.id}/notes",
        json={"body": "hi", "author_id": str(world.admin.id), "company_id": "x"},
    )

    assert response.status_code == 422
    assert db.scalars(select(Note)).all() == []


def test_a_company_admin_cannot_write_notes(client: TestClient, db: Session, world: World) -> None:
    response = add_note(Browser(client, db, world.admin), world.application)

    assert response.status_code == 403
    assert db.scalars(select(Note)).all() == []


@pytest.mark.parametrize("who", ["interviewer", "cara"])
def test_interviewers_and_candidates_can_neither_write_nor_read_notes(
    client: TestClient, db: Session, world: World, who: str
) -> None:
    browser = Browser(client, db, getattr(world, who))

    assert add_note(browser, world.application).status_code == 403
    assert browser.get(f"/api/applications/{world.application.id}/notes").status_code == 403


def test_a_recruiter_not_assigned_to_the_job_gets_not_found(
    client: TestClient, db: Session, world: World
) -> None:
    browser = Browser(client, db, world.other_recruiter)

    assert add_note(browser, world.application).status_code == 404
    response = browser.get(f"/api/applications/{world.application.id}/notes")
    assert response.status_code == 404 and response.json() == NOT_FOUND
    assert db.scalars(select(Note)).all() == []


def test_another_companys_recruiter_gets_not_found(
    client: TestClient, db: Session, world: World
) -> None:
    browser = Browser(client, db, world.globex_recruiter)

    assert add_note(browser, world.application).status_code == 404
    assert browser.get(f"/api/applications/{world.application.id}/notes").json() == NOT_FOUND


def test_an_unknown_application_is_not_found(client: TestClient, db: Session, world: World) -> None:
    browser = Browser(client, db, world.recruiter)
    missing = "6f1c2d3e-0000-4000-8000-000000000000"

    assert browser.get(f"/api/applications/{missing}/notes").status_code == 404
    assert (
        browser.send("POST", f"/api/applications/{missing}/notes", json={"body": "x"}).status_code
        == 404
    )


# ---- reading ---------------------------------------------------------------------------------


def test_notes_are_listed_newest_first_with_their_author(
    client: TestClient, db: Session, world: World
) -> None:
    older = Note(
        application_id=world.application.id,
        company_id=world.acme.id,
        author_id=world.recruiter.id,
        body="First impression: promising.",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    newer = Note(
        application_id=world.application.id,
        company_id=world.acme.id,
        author_id=world.other_recruiter.id,
        body="Second call went well.",
        created_at=datetime(2026, 2, 1, tzinfo=UTC),
    )
    db.add_all([older, newer])
    db.commit()

    body = notes_of(Browser(client, db, world.recruiter), world.application)

    assert body["total"] == 2
    assert [item["body"] for item in body["items"]] == [
        "Second call went well.",
        "First impression: promising.",
    ]
    assert all(set(item) == NOTE_FIELDS for item in body["items"])


def test_a_company_admin_can_read_the_notes(client: TestClient, db: Session, world: World) -> None:
    add_note(Browser(client, db, world.recruiter), world.application, "Visible to admins.")

    body = notes_of(Browser(client, db, world.admin), world.application)

    assert [item["body"] for item in body["items"]] == ["Visible to admins."]


def test_each_application_has_its_own_notes(client: TestClient, db: Session, world: World) -> None:
    browser = Browser(client, db, world.recruiter)
    add_note(browser, world.application, "About Cara.")
    add_note(browser, world.other_application, "About Dan.")

    cara = notes_of(browser, world.application)
    dan = notes_of(browser, world.other_application)

    assert [n["body"] for n in cara["items"]] == ["About Cara."]
    assert [n["body"] for n in dan["items"]] == ["About Dan."]


def test_notes_are_paged(client: TestClient, db: Session, world: World) -> None:
    browser = Browser(client, db, world.recruiter)
    for index in range(3):
        add_note(browser, world.application, f"Note {index}")

    first = notes_of(browser, world.application, "?page=1&page_size=2")
    second = notes_of(browser, world.application, "?page=2&page_size=2")

    assert first["total"] == 3 and len(first["items"]) == 2
    assert len(second["items"]) == 1


def test_an_application_with_no_notes_has_an_empty_list(
    client: TestClient, db: Session, world: World
) -> None:
    body = notes_of(Browser(client, db, world.recruiter), world.application)

    assert body["items"] == [] and body["total"] == 0


# ---- append-only, and never reaching the candidate ---------------------------------------------


def test_a_note_can_be_neither_edited_nor_deleted(
    client: TestClient, db: Session, world: World
) -> None:
    browser = Browser(client, db, world.recruiter)
    created = add_note(browser, world.application, "Final words.").json()

    for method in ("PUT", "PATCH", "DELETE"):
        response = browser.send(
            method,
            f"/api/applications/{world.application.id}/notes/{created['id']}",
            json={"body": "changed"},
        )
        assert response.status_code in (404, 405)
    assert db.scalars(select(Note)).one().body == "Final words."


def test_nothing_a_candidate_can_fetch_contains_a_note(
    client: TestClient, db: Session, world: World
) -> None:
    secret = "Internal: do not tell the candidate"
    add_note(Browser(client, db, world.recruiter), world.application, secret)

    candidate = Browser(client, db, world.cara)
    answers = [
        candidate.get("/api/applications").text,
        candidate.get("/api/profile").text,
        candidate.get(f"/api/applications?job_id={world.application.job_id}").text,
    ]

    assert all(secret not in text for text in answers)


def test_the_staff_detail_of_an_application_does_not_carry_the_notes(
    client: TestClient, db: Session, world: World
) -> None:
    # Notes have their own route (and their own permission to write); the detail stays small.
    add_note(Browser(client, db, world.recruiter), world.application, "Only on the notes route.")

    detail = Browser(client, db, world.recruiter).get(f"/api/applications/{world.application.id}")

    assert "Only on the notes route." not in detail.text


# ---- what the database refuses ----------------------------------------------------------------


@pytest.mark.parametrize("body", ["", "   ", "x" * 4001])
def test_the_database_refuses_a_blank_or_oversized_note(
    db: Session, world: World, body: str
) -> None:
    db.add(
        Note(
            application_id=world.application.id,
            company_id=world.acme.id,
            author_id=world.recruiter.id,
            body=body,
        )
    )

    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
