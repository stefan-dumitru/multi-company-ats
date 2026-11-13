"""Candidate registration and profile (functional.md > Authentication; data-model.md >
CandidateProfile).

A candidate registers themselves: one global account, no company. Like every account they must
verify their email before they can do anything but look at who they are and log out.
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import BackgroundJob, CandidateProfile, Role, User
from app.services import candidates as candidates_service
from tests.browser import Browser
from tests.factories import DEFAULT_PASSWORD, make_company, make_user, verify_email_of

GENERIC_FAILURE = {
    "detail": "We couldn't create this account. If you already have one, log in instead."
}


def register_payload(**overrides: str) -> dict[str, str]:
    payload = {
        "full_name": "Cara Candidate",
        "email": "cara@example.test",
        "password": DEFAULT_PASSWORD,
    }
    return {**payload, **overrides}


def count(db: Session, model: type[User] | type[CandidateProfile]) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


def register_and_verify(client: TestClient, db: Session, **overrides: str) -> str:
    """Register through the real API, mark the email verified, return the CSRF token."""
    payload = register_payload(**overrides)
    csrf = client.post("/api/candidates", json=payload).json()["csrf_token"]
    verify_email_of(db, payload["email"])
    return str(csrf)


# ---- registering -------------------------------------------------------------------------


def test_registering_creates_a_candidate_without_a_company(client: TestClient, db: Session) -> None:
    response = client.post("/api/candidates", json=register_payload())

    assert response.status_code == 201
    body = response.json()
    assert body["user"]["email"] == "cara@example.test"
    assert body["user"]["role"] == "candidate"
    assert body["user"]["company_id"] is None
    assert body["user"]["full_name"] == "Cara Candidate"
    assert body["user"]["email_verified_at"] is None
    user = db.scalar(select(User))
    assert user is not None and user.role == Role.CANDIDATE and user.company_id is None


def test_a_profile_is_created_with_the_account(client: TestClient, db: Session) -> None:
    client.post("/api/candidates", json=register_payload())

    user = db.scalar(select(User))
    assert user is not None
    profile = db.get(CandidateProfile, user.id)
    assert profile is not None and profile.phone is None and profile.location is None


def test_the_new_candidate_is_logged_in_straight_away(client: TestClient) -> None:
    csrf = client.post("/api/candidates", json=register_payload()).json()["csrf_token"]

    me = client.get("/api/auth/me")

    assert me.status_code == 200
    assert me.json()["user"]["role"] == "candidate"
    assert me.json()["csrf_token"] == csrf


def test_the_candidate_session_uses_the_longer_candidate_cookie(client: TestClient) -> None:
    response = client.post("/api/candidates", json=register_payload())

    # Candidates stay logged in for up to 30 days; staff for 12 hours (security.md).
    cookie = response.headers["set-cookie"]
    assert "ats_session=" in cookie and "HttpOnly" in cookie
    assert f"Max-Age={30 * 24 * 3600}" in cookie


def test_a_verification_email_is_queued_with_the_account(client: TestClient, db: Session) -> None:
    client.post("/api/candidates", json=register_payload())

    jobs = list(db.scalars(select(BackgroundJob)))
    assert len(jobs) == 1
    assert jobs[0].type == "send_email" and jobs[0].payload["template"] == "verify_email"


def test_the_password_is_stored_hashed_and_never_returned(client: TestClient, db: Session) -> None:
    response = client.post("/api/candidates", json=register_payload())

    user = db.scalar(select(User))
    assert user is not None
    assert user.password_hash is not None and user.password_hash.startswith("$argon2id$")
    assert DEFAULT_PASSWORD not in response.text


def test_the_email_is_stored_lowercase_and_trimmed(client: TestClient, db: Session) -> None:
    client.post("/api/candidates", json=register_payload(email="  Cara@Example.TEST "))

    user = db.scalar(select(User))
    assert user is not None and user.email == "cara@example.test"


def test_a_candidate_can_log_in_again_later(client: TestClient) -> None:
    client.post("/api/candidates", json=register_payload())
    client.cookies.clear()

    response = client.post(
        "/api/auth/login", json={"email": "cara@example.test", "password": DEFAULT_PASSWORD}
    )

    assert response.status_code == 200
    assert response.json()["user"]["role"] == "candidate"


@pytest.mark.parametrize("existing_role", [Role.CANDIDATE, Role.RECRUITER])
def test_an_email_that_already_has_an_account_gets_the_generic_failure(
    client: TestClient, db: Session, existing_role: Role
) -> None:
    company = None if existing_role == Role.CANDIDATE else make_company(db, "Acme")
    make_user(db, email="cara@example.test", role=existing_role, company=company)
    db.commit()

    response = client.post("/api/candidates", json=register_payload(email="CARA@example.test"))

    assert response.status_code == 400
    assert response.json() == GENERIC_FAILURE
    assert "set-cookie" not in response.headers
    assert count(db, User) == 1


def test_losing_a_race_for_an_email_is_the_same_generic_failure(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Two registrations with one email can both pass the "is it taken?" check; the database's
    # unique index is the real guard. Pretend the check passed and let the index refuse.
    client.post("/api/candidates", json=register_payload())
    monkeypatch.setattr(candidates_service, "email_is_taken", lambda db, email: False)

    response = client.post("/api/candidates", json=register_payload(full_name="Racer"))

    assert response.status_code == 400
    assert response.json() == GENERIC_FAILURE
    assert count(db, User) == 1 and count(db, CandidateProfile) == 1


def test_only_a_collision_on_the_email_index_counts_as_a_taken_email() -> None:
    def integrity_error(constraint: str | None) -> IntegrityError:
        original = SimpleNamespace(diag=SimpleNamespace(constraint_name=constraint))
        return IntegrityError("INSERT", {}, original)  # type: ignore[arg-type]

    assert candidates_service.is_email_collision(integrity_error("uq_users_email_lower"))
    assert not candidates_service.is_email_collision(integrity_error("fk_other"))


@pytest.mark.parametrize("password", ["short", "x" * 11, "a" * 129])
def test_a_weak_password_is_refused_and_nothing_is_created(
    client: TestClient, db: Session, password: str
) -> None:
    response = client.post("/api/candidates", json=register_payload(password=password))

    assert response.status_code == 422
    assert "Password" in response.json()["detail"]
    assert count(db, User) == 0 and count(db, CandidateProfile) == 0


@pytest.mark.parametrize("field", ["full_name", "email", "password"])
def test_every_field_is_required(client: TestClient, field: str) -> None:
    payload = register_payload()
    del payload[field]

    assert client.post("/api/candidates", json=payload).status_code == 422


@pytest.mark.parametrize(
    "overrides",
    [{"full_name": "   "}, {"full_name": ""}, {"email": "nope"}, {"full_name": "x" * 201}],
)
def test_blank_or_malformed_values_are_refused(
    client: TestClient, db: Session, overrides: dict[str, str]
) -> None:
    assert client.post("/api/candidates", json=register_payload(**overrides)).status_code == 422
    assert count(db, User) == 0


@pytest.mark.parametrize("extra", ["role", "company_id", "email_verified_at", "is_active"])
def test_a_registration_cannot_choose_its_own_role_or_state(
    client: TestClient, db: Session, extra: str
) -> None:
    value = "company_admin" if extra == "role" else "x"

    response = client.post("/api/candidates", json={**register_payload(), extra: value})

    assert response.status_code == 422  # unknown fields are rejected, not silently ignored
    assert count(db, User) == 0


# ---- the profile -------------------------------------------------------------------------


def test_an_unverified_candidate_cannot_use_the_profile_yet(client: TestClient) -> None:
    csrf = client.post("/api/candidates", json=register_payload()).json()["csrf_token"]

    read = client.get("/api/profile")
    write = client.patch("/api/profile", json={"phone": "123"}, headers={"X-CSRF-Token": csrf})

    for response in (read, write):
        assert response.status_code == 403
        assert response.json()["code"] == "email_not_verified"


def test_a_verified_candidate_reads_their_own_profile(client: TestClient, db: Session) -> None:
    register_and_verify(client, db)

    response = client.get("/api/profile")

    assert response.status_code == 200
    assert response.json() == {
        "full_name": "Cara Candidate",
        "email": "cara@example.test",
        "phone": None,
        "location": None,
    }


def test_a_profile_missing_its_row_is_created_when_first_used(
    client: TestClient, db: Session
) -> None:
    # An account made some other way (a later sign-in method) has no profile row yet.
    candidate = make_user(
        db, email="odd@example.test", role=Role.CANDIDATE, company=None, full_name="Odd One"
    )
    db.commit()
    browser = Browser(client, db, candidate)

    response = browser.get("/api/profile")

    assert response.status_code == 200 and response.json()["phone"] is None
    assert db.get(CandidateProfile, candidate.id) is not None


def patch(client: TestClient, csrf: str, body: dict[str, object]) -> object:
    return client.patch("/api/profile", json=body, headers={"X-CSRF-Token": csrf})


def test_a_candidate_updates_their_profile(client: TestClient, db: Session) -> None:
    csrf = register_and_verify(client, db)

    response = patch(
        client,
        csrf,
        {"full_name": "Cara C. Candidate", "phone": "+47 123 45 678", "location": "Oslo"},
    )

    assert response.status_code == 200  # type: ignore[attr-defined]
    assert response.json() == {  # type: ignore[attr-defined]
        "full_name": "Cara C. Candidate",
        "email": "cara@example.test",
        "phone": "+47 123 45 678",
        "location": "Oslo",
    }
    assert client.get("/api/profile").json()["phone"] == "+47 123 45 678"
    user = db.scalar(select(User))
    db.refresh(user)  # type: ignore[arg-type]
    assert user is not None and user.full_name == "Cara C. Candidate"


def test_values_are_trimmed(client: TestClient, db: Session) -> None:
    csrf = register_and_verify(client, db)

    response = patch(client, csrf, {"location": "  Oslo  ", "full_name": "  Cara  "})

    assert response.json()["location"] == "Oslo"  # type: ignore[attr-defined]
    assert response.json()["full_name"] == "Cara"  # type: ignore[attr-defined]


def test_only_what_is_sent_changes(client: TestClient, db: Session) -> None:
    csrf = register_and_verify(client, db)
    patch(client, csrf, {"phone": "12345", "location": "Oslo"})

    patch(client, csrf, {"location": "Bergen"})

    body = client.get("/api/profile").json()
    assert body["phone"] == "12345" and body["location"] == "Bergen"


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_phone_and_location_can_be_cleared(
    client: TestClient, db: Session, empty: str | None
) -> None:
    csrf = register_and_verify(client, db)
    patch(client, csrf, {"phone": "12345", "location": "Oslo"})

    patch(client, csrf, {"phone": empty, "location": empty})

    body = client.get("/api/profile").json()
    assert body["phone"] is None and body["location"] is None


def test_an_empty_change_is_fine_and_changes_nothing(client: TestClient, db: Session) -> None:
    csrf = register_and_verify(client, db)
    patch(client, csrf, {"location": "Oslo"})

    response = patch(client, csrf, {})

    assert response.status_code == 200  # type: ignore[attr-defined]
    assert client.get("/api/profile").json()["location"] == "Oslo"


@pytest.mark.parametrize(
    "body",
    [
        {"full_name": ""},
        {"full_name": "   "},
        {"full_name": None},
        {"full_name": "x" * 201},
        {"phone": "call me"},
        {"phone": "1" * 31},
        {"phone": "<script>"},
        {"location": "x" * 201},
    ],
)
def test_bad_values_are_refused_and_nothing_changes(
    client: TestClient, db: Session, body: dict[str, object]
) -> None:
    csrf = register_and_verify(client, db)

    response = patch(client, csrf, body)

    assert response.status_code == 422  # type: ignore[attr-defined]
    assert client.get("/api/profile").json()["full_name"] == "Cara Candidate"


def test_the_limits_themselves_are_allowed(client: TestClient, db: Session) -> None:
    csrf = register_and_verify(client, db)

    response = patch(
        client, csrf, {"phone": "1" * 30, "location": "x" * 200, "full_name": "n" * 200}
    )

    assert response.status_code == 200  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "field", ["email", "role", "company_id", "email_verified_at", "current_resume_file_id"]
)
def test_the_profile_cannot_change_anything_else(
    client: TestClient, db: Session, field: str
) -> None:
    csrf = register_and_verify(client, db)

    response = patch(client, csrf, {field: "x"})

    assert response.status_code == 422  # type: ignore[attr-defined]
    user = db.scalar(select(User))
    assert user is not None and user.email == "cara@example.test" and user.role == Role.CANDIDATE


def test_one_candidate_cannot_change_another(client: TestClient, db: Session) -> None:
    other = make_user(db, email="dan@example.test", role=Role.CANDIDATE, company=None)
    db.add(CandidateProfile(user_id=other.id, phone="999", location="Rome"))
    db.commit()
    csrf = register_and_verify(client, db)

    patch(client, csrf, {"phone": "111", "location": "Oslo", "full_name": "Changed"})

    db.expire_all()
    untouched = db.get(CandidateProfile, other.id)
    assert untouched is not None and untouched.phone == "999" and untouched.location == "Rome"
    reloaded = db.get(User, other.id)
    assert reloaded is not None and reloaded.full_name != "Changed"


def test_staff_cannot_use_the_candidate_profile(client: TestClient, db: Session) -> None:
    company = make_company(db, "Acme")
    admin = make_user(db, email="admin@acme.test", role=Role.COMPANY_ADMIN, company=company)
    db.commit()
    browser = Browser(client, db, admin)

    assert browser.get("/api/profile").status_code == 403
    assert browser.send("PATCH", "/api/profile", json={"phone": "1"}).status_code == 403


def test_the_profile_needs_a_login(client: TestClient) -> None:
    assert client.get("/api/profile").status_code == 401
    assert client.patch("/api/profile", json={}).status_code == 401
