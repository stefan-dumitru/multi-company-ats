"""Company signup (functional.md > Company signup and onboarding)."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Company, Role, User
from app.services import companies as companies_service
from tests.factories import DEFAULT_PASSWORD, make_company, make_user

GENERIC_FAILURE = {
    "detail": "We couldn't create this account. If you already have one, log in instead."
}


def signup_payload(**overrides: str) -> dict[str, str]:
    payload = {
        "company_name": "Acme Corp",
        "full_name": "Ada Admin",
        "email": "ada@acme.test",
        "password": DEFAULT_PASSWORD,
    }
    return {**payload, **overrides}


def count(db: Session, model: type[Company] | type[User]) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


def test_signing_up_creates_the_company_and_its_first_admin(
    client: TestClient, db: Session
) -> None:
    response = client.post("/api/companies", json=signup_payload())

    assert response.status_code == 201
    body = response.json()
    assert body["user"]["email"] == "ada@acme.test"
    assert body["user"]["role"] == "company_admin"
    assert body["user"]["full_name"] == "Ada Admin"
    company = db.scalar(select(Company))
    assert company is not None and company.name == "Acme Corp"
    assert body["user"]["company_id"] == str(company.id)


def test_the_new_admin_is_logged_in_straight_away(client: TestClient) -> None:
    csrf_token = client.post("/api/companies", json=signup_payload()).json()["csrf_token"]

    me = client.get("/api/auth/me")

    assert me.status_code == 200
    assert me.json()["user"]["email"] == "ada@acme.test"
    assert me.json()["csrf_token"] == csrf_token


def test_the_password_is_stored_hashed_and_never_returned(client: TestClient, db: Session) -> None:
    response = client.post("/api/companies", json=signup_payload())

    user = db.scalar(select(User))
    assert user is not None
    assert user.password_hash is not None and user.password_hash.startswith("$argon2id$")
    assert DEFAULT_PASSWORD not in response.text


def test_email_verification_is_stored_but_not_enforced_yet(client: TestClient, db: Session) -> None:
    # Phase 3 sends the verification emails; until then the admin is unverified but not blocked.
    client.post("/api/companies", json=signup_payload())

    user = db.scalar(select(User))
    assert user is not None and user.email_verified_at is None
    assert client.get("/api/auth/me").status_code == 200


def test_the_email_is_stored_lowercase_and_trimmed(client: TestClient, db: Session) -> None:
    client.post("/api/companies", json=signup_payload(email="  Ada@Acme.TEST "))

    user = db.scalar(select(User))
    assert user is not None and user.email == "ada@acme.test"


def test_company_names_need_not_be_unique(client: TestClient, db: Session) -> None:
    assert client.post("/api/companies", json=signup_payload()).status_code == 201
    other = signup_payload(email="someone@else.test")

    assert client.post("/api/companies", json=other).status_code == 201
    assert count(db, Company) == 2


@pytest.mark.parametrize("existing_role", [Role.RECRUITER, Role.CANDIDATE])
def test_an_email_that_already_has_an_account_gets_the_generic_failure(
    client: TestClient, db: Session, existing_role: Role
) -> None:
    company = None if existing_role == Role.CANDIDATE else make_company(db, "Other")
    make_user(db, email="ada@acme.test", role=existing_role, company=company)
    db.commit()

    response = client.post("/api/companies", json=signup_payload(email="ADA@acme.test"))

    assert response.status_code == 400
    assert response.json() == GENERIC_FAILURE
    assert "set-cookie" not in response.headers


def test_a_failed_signup_leaves_no_company_behind(client: TestClient, db: Session) -> None:
    # All-or-nothing: never a company without an admin.
    client.post("/api/companies", json=signup_payload())
    companies_before = count(db, Company)

    client.post("/api/companies", json=signup_payload(company_name="Second Try"))

    assert count(db, Company) == companies_before == 1
    assert count(db, User) == 1


def test_losing_a_race_for_an_email_is_the_same_generic_failure(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Two signups with one email can both pass the "is it taken?" check; the database's unique
    # index is the real guard. Pretend the check passed and let the index refuse.
    client.post("/api/companies", json=signup_payload())
    monkeypatch.setattr(companies_service, "email_is_taken", lambda db, email: False)

    response = client.post("/api/companies", json=signup_payload(company_name="Racer"))

    assert response.status_code == 400
    assert response.json() == GENERIC_FAILURE
    assert count(db, Company) == 1


@pytest.mark.parametrize("password", ["short", "x" * 11, "a" * 129])
def test_a_weak_password_is_refused_and_nothing_is_created(
    client: TestClient, db: Session, password: str
) -> None:
    response = client.post("/api/companies", json=signup_payload(password=password))

    assert response.status_code == 422
    assert "Password" in response.json()["detail"]
    assert count(db, Company) == 0
    assert count(db, User) == 0


@pytest.mark.parametrize("field", ["company_name", "full_name", "email", "password"])
def test_every_field_is_required(client: TestClient, field: str) -> None:
    payload = signup_payload()
    del payload[field]

    assert client.post("/api/companies", json=payload).status_code == 422


@pytest.mark.parametrize(
    "overrides",
    [
        {"company_name": "   "},
        {"full_name": ""},
        {"email": "not-an-email"},
        {"email": "a@b"},
        {"company_name": "x" * 201},
    ],
)
def test_blank_or_malformed_values_are_refused(
    client: TestClient, db: Session, overrides: dict[str, str]
) -> None:
    response = client.post("/api/companies", json=signup_payload(**overrides))

    assert response.status_code == 422
    assert count(db, Company) == 0


def test_a_signup_cannot_choose_its_own_role_or_company(client: TestClient, db: Session) -> None:
    other = make_company(db, "Victim Inc")
    db.commit()

    response = client.post(
        "/api/companies",
        json={**signup_payload(), "role": "candidate", "company_id": str(other.id)},
    )

    assert response.status_code == 422  # unknown fields are rejected, not silently ignored
    assert count(db, Company) == 1  # only the victim, nothing new


def fake_integrity_error(constraint_name: str | None) -> IntegrityError:
    original = SimpleNamespace(diag=SimpleNamespace(constraint_name=constraint_name))
    return IntegrityError("INSERT", {}, original)  # type: ignore[arg-type]


def test_only_a_collision_on_the_email_index_counts_as_a_taken_email() -> None:
    # Any other database error is a real bug and must surface, not be reported as "log in instead".
    assert companies_service.is_email_collision(fake_integrity_error("uq_users_email_lower"))
    assert not companies_service.is_email_collision(fake_integrity_error("fk_users_company_id"))
    assert not companies_service.is_email_collision(fake_integrity_error(None))
