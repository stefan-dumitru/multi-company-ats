"""Tenant scoping (CLAUDE.md): data access goes through functions that take the current user."""

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.error_handlers import add_error_handlers
from app.main import app as real_app
from app.models import Role, User
from app.services.errors import NotFoundError
from app.services.users import get_company_user, list_company_users
from tests.factories import make_company, make_user


@pytest.fixture
def two_companies(db: Session) -> dict[str, User]:
    acme = make_company(db, "Acme")
    globex = make_company(db, "Globex")
    return {
        "acme_admin": make_user(db, email="a1@acme.test", role=Role.COMPANY_ADMIN, company=acme),
        "acme_rec": make_user(db, email="a2@acme.test", role=Role.RECRUITER, company=acme),
        "globex_admin": make_user(
            db, email="g1@globex.test", role=Role.COMPANY_ADMIN, company=globex
        ),
        "candidate": make_user(db, email="c1@example.test", role=Role.CANDIDATE, company=None),
    }


def test_a_company_sees_only_its_own_users(db: Session, two_companies: dict[str, User]) -> None:
    emails = {user.email for user in list_company_users(db, two_companies["acme_admin"])}

    assert emails == {"a1@acme.test", "a2@acme.test"}


def test_a_user_of_another_company_is_not_found_not_forbidden(
    db: Session, two_companies: dict[str, User]
) -> None:
    other = two_companies["globex_admin"]

    with pytest.raises(NotFoundError):
        get_company_user(db, two_companies["acme_admin"], other.id)


def test_a_user_of_the_same_company_is_found(db: Session, two_companies: dict[str, User]) -> None:
    found = get_company_user(db, two_companies["acme_admin"], two_companies["acme_rec"].id)

    assert found.email == "a2@acme.test"


def test_an_id_that_does_not_exist_is_not_found_in_the_same_way(
    db: Session, two_companies: dict[str, User]
) -> None:
    # Same error as "exists in another company", so ids cannot be probed across tenants.
    with pytest.raises(NotFoundError):
        get_company_user(db, two_companies["acme_admin"], uuid.uuid4())


def test_a_candidate_has_no_company_so_sees_no_company_users(
    db: Session, two_companies: dict[str, User]
) -> None:
    assert list_company_users(db, two_companies["candidate"]) == []
    with pytest.raises(NotFoundError):
        get_company_user(db, two_companies["candidate"], two_companies["acme_admin"].id)


def test_a_not_found_error_becomes_the_same_404_for_every_cause() -> None:
    app = FastAPI()
    add_error_handlers(app)

    @app.get("/missing")
    def missing() -> None:
        raise NotFoundError

    response = TestClient(app).get("/missing")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not found."}


def test_the_real_app_registers_that_handler() -> None:
    assert NotFoundError in real_app.exception_handlers
