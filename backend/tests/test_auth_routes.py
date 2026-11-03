"""Login, logout and "who am I" through the real HTTP layer (security.md > Authentication)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Role, User
from tests.factories import DEFAULT_PASSWORD, make_company, make_user

SAME_FAILURE = {"detail": "Invalid email or password."}


@pytest.fixture
def recruiter(db: Session) -> User:
    company = make_company(db)
    user = make_user(
        db,
        email="rec@example.com",
        role=Role.RECRUITER,
        company=company,
        full_name="Rae Recruiter",
        password=DEFAULT_PASSWORD,
    )
    db.commit()
    return user


def log_in(client: TestClient, email: str = "rec@example.com", password: str = DEFAULT_PASSWORD):  # type: ignore[no-untyped-def]
    return client.post("/api/auth/login", json={"email": email, "password": password})


def test_logging_in_returns_the_user_and_a_csrf_token(client: TestClient, recruiter: User) -> None:
    response = log_in(client)

    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == "rec@example.com"
    assert body["user"]["role"] == "recruiter"
    assert body["user"]["full_name"] == "Rae Recruiter"
    assert len(body["csrf_token"]) >= 32


def test_the_response_never_contains_the_password_hash(client: TestClient, recruiter: User) -> None:
    response = log_in(client)

    assert "password" not in response.text
    assert "argon2" not in response.text


def test_the_session_cookie_is_httponly_secure_and_samesite_lax(
    client: TestClient, recruiter: User
) -> None:
    response = log_in(client)

    cookie = response.headers["set-cookie"].lower()
    assert "ats_session=" in cookie
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=lax" in cookie


def test_the_secure_flag_can_be_switched_off_for_local_http_only(
    client: TestClient, recruiter: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COOKIE_SECURE", "false")

    cookie = log_in(client).headers["set-cookie"].lower()

    assert "secure" not in cookie
    assert "httponly" in cookie  # everything else stays strict


def test_the_email_is_matched_ignoring_case(client: TestClient, recruiter: User) -> None:
    assert log_in(client, email="  REC@Example.com ").status_code == 200


@pytest.mark.parametrize(
    ("email", "password"),
    [
        ("rec@example.com", "wrong password here"),
        ("nobody@example.com", DEFAULT_PASSWORD),
        ("rec@example.com", ""),
    ],
)
def test_every_kind_of_failed_login_gets_the_same_answer(
    client: TestClient, recruiter: User, email: str, password: str
) -> None:
    response = log_in(client, email=email, password=password)

    assert response.status_code == 401
    assert response.json() == SAME_FAILURE
    assert "set-cookie" not in response.headers


def test_a_deactivated_user_gets_the_same_answer_as_a_wrong_password(
    client: TestClient, db: Session, recruiter: User
) -> None:
    recruiter.is_active = False
    db.commit()

    response = log_in(client)

    assert response.status_code == 401
    assert response.json() == SAME_FAILURE


def test_an_account_with_no_password_cannot_log_in(client: TestClient, db: Session) -> None:
    make_user(db, email="google@example.com", role=Role.CANDIDATE, company=None)
    db.commit()

    response = log_in(client, email="google@example.com", password="anything at all")

    assert response.status_code == 401
    assert response.json() == SAME_FAILURE


def test_the_sixth_wrong_attempt_is_refused_even_with_the_right_password(
    client: TestClient, recruiter: User
) -> None:
    for _ in range(5):
        assert log_in(client, password="wrong password here").status_code == 401

    response = log_in(client)  # the correct password, but the account is locked for now

    assert response.status_code == 429
    assert "set-cookie" not in response.headers


def test_failed_attempts_for_unknown_emails_are_counted_too(client: TestClient) -> None:
    # Otherwise the lockout itself would reveal which emails have accounts.
    for _ in range(5):
        log_in(client, email="ghost@example.com", password="wrong password here")

    assert log_in(client, email="ghost@example.com").status_code == 429


def test_a_successful_login_forgives_earlier_failures(client: TestClient, recruiter: User) -> None:
    for _ in range(4):
        log_in(client, password="wrong password here")
    assert log_in(client).status_code == 200

    for _ in range(4):
        assert log_in(client, password="wrong password here").status_code == 401


def test_me_returns_the_logged_in_user_and_csrf_token(client: TestClient, recruiter: User) -> None:
    csrf_token = log_in(client).json()["csrf_token"]

    response = client.get("/api/auth/me")

    assert response.status_code == 200
    assert response.json()["user"]["email"] == "rec@example.com"
    assert response.json()["csrf_token"] == csrf_token


def test_me_without_a_session_is_unauthorized(client: TestClient) -> None:
    assert client.get("/api/auth/me").status_code == 401


def test_me_with_a_made_up_cookie_is_unauthorized(client: TestClient) -> None:
    client.cookies.set("ats_session", "made-up-value", domain="testserver.local")

    assert client.get("/api/auth/me").status_code == 401


def test_logout_requires_the_csrf_token(client: TestClient, recruiter: User) -> None:
    log_in(client)

    assert client.post("/api/auth/logout").status_code == 403
    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert client.get("/api/auth/me").status_code == 200  # still logged in


def test_logout_ends_the_session_for_good(client: TestClient, recruiter: User) -> None:
    csrf_token = log_in(client).json()["csrf_token"]
    stolen_cookie = client.cookies.get("ats_session")

    response = client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf_token})

    assert response.status_code == 204
    assert client.get("/api/auth/me").status_code == 401
    # Even someone who copied the cookie earlier is out: the session is revoked on the server.
    client.cookies.set("ats_session", stolen_cookie or "")
    assert client.get("/api/auth/me").status_code == 401


def test_logging_out_when_not_logged_in_is_unauthorized(client: TestClient) -> None:
    assert client.post("/api/auth/logout").status_code == 401
