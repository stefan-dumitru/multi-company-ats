"""An unverified user can log in and nothing else (security.md > Authentication).

The rule lives in `require_permission`, so it covers every route that declares a permission. The
role x endpoint matrix has an "unverified" dimension (test_route_matrix.py) that checks it route by
route; these tests pin down the wording, the exceptions and the details.
"""

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth.sessions import SESSION_COOKIE_NAME, create_session
from app.models import Role, User
from tests.factories import DEFAULT_PASSWORD, make_company, make_user

NOT_VERIFIED = {"detail": "Verify your email first.", "code": "email_not_verified"}
NO_ACCESS = {"detail": "You do not have access to this."}


def log_in_as(
    client: TestClient, db: Session, role: Role, *, verified: bool, email: str = "u@acme.test"
) -> tuple[User, str]:
    company = None if role == Role.CANDIDATE else make_company(db)
    user = make_user(db, email=email, role=role, company=company, verified=verified)
    token, session = create_session(db, user, datetime.now(UTC))
    db.commit()
    client.cookies.clear()
    client.cookies.set(SESSION_COOKIE_NAME, token)
    return user, session.csrf_token


def test_an_unverified_admin_is_told_to_verify_when_they_reach_for_anything_else(
    client: TestClient, db: Session
) -> None:
    log_in_as(client, db, Role.COMPANY_ADMIN, verified=False)

    response = client.get("/api/users")

    assert response.status_code == 403
    assert response.json() == NOT_VERIFIED


def test_an_unverified_user_can_still_see_who_they_are_and_log_out(
    client: TestClient, db: Session
) -> None:
    _, csrf = log_in_as(client, db, Role.COMPANY_ADMIN, verified=False)

    me = client.get("/api/auth/me")
    logout = client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf})

    assert me.status_code == 200
    assert me.json()["user"]["email_verified_at"] is None
    assert logout.status_code == 204


def test_an_unverified_user_can_ask_for_the_link_again(client: TestClient, db: Session) -> None:
    _, csrf = log_in_as(client, db, Role.COMPANY_ADMIN, verified=False)

    response = client.post("/api/auth/resend-verification", headers={"X-CSRF-Token": csrf})

    assert response.status_code == 204


def test_a_verified_admin_is_not_held_back(client: TestClient, db: Session) -> None:
    log_in_as(client, db, Role.COMPANY_ADMIN, verified=True)

    assert client.get("/api/users").status_code == 200


def test_being_unverified_does_not_reveal_a_route_the_role_could_never_use(
    client: TestClient, db: Session
) -> None:
    # A recruiter is refused the admin page for their role; the verification hint would be a
    # misleading (and leaky) answer, since verifying would not help.
    log_in_as(client, db, Role.RECRUITER, verified=False)

    response = client.get("/api/users")

    assert response.status_code == 403
    assert response.json() == NO_ACCESS


def test_an_unverified_user_can_log_in(client: TestClient, db: Session) -> None:
    make_user(
        db,
        email="u@acme.test",
        role=Role.COMPANY_ADMIN,
        company=make_company(db),
        password=DEFAULT_PASSWORD,
        verified=False,
    )
    db.commit()

    response = client.post(
        "/api/auth/login", json={"email": "u@acme.test", "password": DEFAULT_PASSWORD}
    )

    assert response.status_code == 200
    assert response.json()["user"]["email_verified_at"] is None


def test_verifying_takes_effect_in_the_session_already_open(
    client: TestClient, db: Session
) -> None:
    user, _ = log_in_as(client, db, Role.COMPANY_ADMIN, verified=False)
    assert client.get("/api/users").status_code == 403

    user.email_verified_at = datetime.now(UTC)
    db.commit()

    assert client.get("/api/users").status_code == 200


def test_the_refusal_says_nothing_about_other_accounts(client: TestClient, db: Session) -> None:
    log_in_as(client, db, Role.COMPANY_ADMIN, verified=False)

    assert set(client.get("/api/users").json()) == {"detail", "code"}
