"""Inviting staff and accepting invitations (functional.md > Invite and deactivate staff)."""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Invitation, Role, User
from tests.factories import DEFAULT_PASSWORD, make_company, make_user

INVALID_LINK = {"detail": "This invitation link is invalid or has expired."}


def sign_up_company(client: TestClient, name: str, email: str) -> str:
    """Register a company; the client is now logged in as its admin. Returns the CSRF token."""
    response = client.post(
        "/api/companies",
        json={
            "company_name": name,
            "full_name": f"Admin of {name}",
            "email": email,
            "password": DEFAULT_PASSWORD,
        },
    )
    assert response.status_code == 201
    return str(response.json()["csrf_token"])


def log_in_as_admin(client: TestClient) -> str:
    """Accepting an invitation logs the client in as the newcomer; this switches back."""
    client.cookies.clear()
    response = client.post(
        "/api/auth/login", json={"email": "admin@acme.test", "password": DEFAULT_PASSWORD}
    )
    assert response.status_code == 200
    return str(response.json()["csrf_token"])


def invite(client: TestClient, csrf_token: str, email: str, role: str = "recruiter") -> Response:
    return client.post(
        "/api/invitations",
        json={"email": email, "role": role},
        headers={"X-CSRF-Token": csrf_token},
    )


def accept(client: TestClient, token: str, **overrides: str) -> Response:
    payload = {"token": token, "full_name": "Rae Recruiter", "password": DEFAULT_PASSWORD}
    return client.post("/api/invitations/accept", json={**payload, **overrides})


@pytest.fixture
def admin_csrf(client: TestClient) -> str:
    return sign_up_company(client, "Acme", "admin@acme.test")


# ---- signed links -------------------------------------------------------------------------


def test_a_forged_link_for_a_real_invitation_is_refused(
    client: TestClient, admin_csrf: str
) -> None:
    body = invite(client, admin_csrf, "rae@acme.test").json()
    invitation_id = body["invitation"]["id"]

    forged = f"{invitation_id}.{'0' * 64}"  # the right row, but not signed by us

    response = accept(client, forged)
    assert response.status_code == 400
    assert response.json() == INVALID_LINK


def test_a_link_signed_for_another_purpose_is_refused(client: TestClient, admin_csrf: str) -> None:
    from app.auth import tokens

    body = invite(client, admin_csrf, "rae@acme.test").json()
    wrong_purpose = tokens.make_token(tokens.PASSWORD_RESET, uuid.UUID(body["invitation"]["id"]))

    assert accept(client, wrong_purpose).status_code == 400


def test_changing_the_server_key_kills_outstanding_invitations(
    client: TestClient, admin_csrf: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = invite(client, admin_csrf, "rae@acme.test").json()

    monkeypatch.setenv("SECRET_KEY", "z" * 40)

    assert accept(client, body["token"]).status_code == 400


# ---- creating invitations ----------------------------------------------------------------


def test_an_admin_can_invite_and_gets_the_link_once(client: TestClient, admin_csrf: str) -> None:
    response = invite(client, admin_csrf, "rae@acme.test")

    assert response.status_code == 201
    body = response.json()
    assert body["invitation"]["email"] == "rae@acme.test"
    assert body["invitation"]["role"] == "recruiter"
    assert body["invitation"]["status"] == "pending"
    assert len(body["token"]) >= 32
    assert body["accept_path"] == f"/accept-invitation?token={body['token']}"


def test_the_invitation_expires_in_seven_days(client: TestClient, admin_csrf: str) -> None:
    before = datetime.now(UTC)

    body = invite(client, admin_csrf, "rae@acme.test").json()

    expires_at = datetime.fromisoformat(body["invitation"]["expires_at"])
    assert timedelta(days=6, hours=23) < expires_at - before < timedelta(days=7, minutes=1)


def test_only_a_hash_of_the_token_is_stored(
    client: TestClient, db: Session, admin_csrf: str
) -> None:
    token = invite(client, admin_csrf, "rae@acme.test").json()["token"]

    stored = db.scalar(select(Invitation))
    assert stored is not None
    assert stored.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert token not in stored.token_hash


@pytest.mark.parametrize("role", ["company_admin", "recruiter", "interviewer"])
def test_each_staff_role_can_be_invited(client: TestClient, admin_csrf: str, role: str) -> None:
    assert invite(client, admin_csrf, "x@acme.test", role).status_code == 201


@pytest.mark.parametrize("role", ["candidate", "superuser", ""])
def test_other_roles_cannot_be_invited(client: TestClient, admin_csrf: str, role: str) -> None:
    assert invite(client, admin_csrf, "x@acme.test", role).status_code == 422


def test_the_email_is_stored_lowercase_and_trimmed(
    client: TestClient, db: Session, admin_csrf: str
) -> None:
    invite(client, admin_csrf, "  Rae@Acme.TEST ")

    stored = db.scalar(select(Invitation))
    assert stored is not None and stored.email == "rae@acme.test"


def test_an_email_that_already_has_an_account_is_rejected(
    client: TestClient, db: Session, admin_csrf: str
) -> None:
    make_user(db, email="cand@example.test", role=Role.CANDIDATE, company=None)
    db.commit()

    for email in ("cand@example.test", "ADMIN@acme.test"):  # a candidate, and the admin themself
        response = invite(client, admin_csrf, email)
        assert response.status_code == 409
        assert response.json() == {"detail": "That email already has an account."}


def test_inviting_again_replaces_the_old_link(client: TestClient, admin_csrf: str) -> None:
    first = invite(client, admin_csrf, "rae@acme.test").json()["token"]
    second = invite(client, admin_csrf, "rae@acme.test").json()["token"]

    assert first != second
    assert accept(client, first).status_code == 400  # the old link is dead
    assert accept(client, second).status_code == 201  # the new one works


def test_resending_leaves_one_pending_invitation_in_the_list(
    client: TestClient, admin_csrf: str
) -> None:
    invite(client, admin_csrf, "rae@acme.test")
    invite(client, admin_csrf, "rae@acme.test")

    statuses = sorted(i["status"] for i in client.get("/api/invitations").json())
    assert statuses == ["pending", "revoked"]


def test_creating_an_invitation_needs_the_csrf_token(client: TestClient, admin_csrf: str) -> None:
    response = client.post("/api/invitations", json={"email": "x@acme.test", "role": "recruiter"})

    assert response.status_code == 403


def test_only_admins_may_invite(client: TestClient, db: Session) -> None:
    csrf_token = sign_up_company(client, "Acme", "admin@acme.test")
    token = invite(client, csrf_token, "rae@acme.test").json()["token"]
    recruiter_csrf = accept(client, token).json()["csrf_token"]  # now logged in as the recruiter

    assert invite(client, recruiter_csrf, "other@acme.test").status_code == 403
    assert client.get("/api/invitations").status_code == 403


def test_inviting_requires_login(client: TestClient) -> None:
    response = client.post("/api/invitations", json={"email": "x@acme.test", "role": "recruiter"})

    assert response.status_code == 401


# ---- listing -----------------------------------------------------------------------------


def test_the_list_never_contains_tokens(client: TestClient, admin_csrf: str) -> None:
    token = invite(client, admin_csrf, "rae@acme.test").json()["token"]

    response = client.get("/api/invitations")

    assert response.status_code == 200
    assert token not in response.text
    assert "token_hash" not in response.text


def test_a_company_sees_only_its_own_invitations(client: TestClient, db: Session) -> None:
    csrf_a = sign_up_company(client, "Acme", "admin@acme.test")
    invite(client, csrf_a, "rae@acme.test")
    client.cookies.clear()
    csrf_b = sign_up_company(client, "Globex", "admin@globex.test")
    invite(client, csrf_b, "gus@globex.test")

    emails = {i["email"] for i in client.get("/api/invitations").json()}

    assert emails == {"gus@globex.test"}


def test_the_same_email_can_be_invited_by_two_companies(client: TestClient) -> None:
    csrf_a = sign_up_company(client, "Acme", "admin@acme.test")
    assert invite(client, csrf_a, "rae@shared.test").status_code == 201
    client.cookies.clear()
    csrf_b = sign_up_company(client, "Globex", "admin@globex.test")

    assert invite(client, csrf_b, "rae@shared.test").status_code == 201


def test_status_reflects_accepted_and_expired(
    client: TestClient, db: Session, admin_csrf: str
) -> None:
    accepted_token = invite(client, admin_csrf, "a@acme.test").json()["token"]
    invite(client, admin_csrf, "b@acme.test")
    accept(client, accepted_token)
    log_in_as_admin(client)
    expired = db.scalar(select(Invitation).where(Invitation.email == "b@acme.test"))
    assert expired is not None
    expired.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()

    by_email = {i["email"]: i["status"] for i in client.get("/api/invitations").json()}

    assert by_email == {"a@acme.test": "accepted", "b@acme.test": "expired"}


# ---- accepting ---------------------------------------------------------------------------


def test_accepting_creates_the_user_with_the_invited_role_and_company(
    client: TestClient, db: Session, admin_csrf: str
) -> None:
    token = invite(client, admin_csrf, "rae@acme.test", "interviewer").json()["token"]
    client.cookies.clear()

    response = accept(client, token, full_name="Ivy Interviewer")

    assert response.status_code == 201
    body = response.json()
    assert body["user"]["email"] == "rae@acme.test"
    assert body["user"]["role"] == "interviewer"
    assert body["user"]["full_name"] == "Ivy Interviewer"
    admin = db.scalar(select(User).where(User.email == "admin@acme.test"))
    assert admin is not None and body["user"]["company_id"] == str(admin.company_id)


def test_the_new_member_is_logged_in_and_can_log_in_later(
    client: TestClient, admin_csrf: str
) -> None:
    token = invite(client, admin_csrf, "rae@acme.test").json()["token"]
    client.cookies.clear()

    accept(client, token)

    assert client.get("/api/auth/me").json()["user"]["email"] == "rae@acme.test"
    client.cookies.clear()
    login = client.post(
        "/api/auth/login", json={"email": "rae@acme.test", "password": DEFAULT_PASSWORD}
    )
    assert login.status_code == 200


def test_a_link_works_only_once(client: TestClient, admin_csrf: str) -> None:
    token = invite(client, admin_csrf, "rae@acme.test").json()["token"]

    assert accept(client, token).status_code == 201
    assert accept(client, token, full_name="Someone Else").status_code == 400


def test_an_expired_link_is_refused(client: TestClient, db: Session, admin_csrf: str) -> None:
    token = invite(client, admin_csrf, "rae@acme.test").json()["token"]
    stored = db.scalar(select(Invitation))
    assert stored is not None
    stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()

    response = accept(client, token)

    assert response.status_code == 400
    assert response.json() == INVALID_LINK


def test_unknown_expired_used_and_revoked_links_all_give_the_same_answer(
    client: TestClient, db: Session, admin_csrf: str
) -> None:
    used = invite(client, admin_csrf, "used@acme.test").json()["token"]
    accept(client, used)
    admin_csrf = log_in_as_admin(client)
    revoked = invite(client, admin_csrf, "rev@acme.test").json()["token"]
    invite(client, admin_csrf, "rev@acme.test")  # re-send revokes the first link

    for token in ("not-a-real-token", "", used, revoked):
        response = accept(client, token)
        assert response.status_code == 400
        assert response.json() == INVALID_LINK


def test_the_invitee_cannot_pick_their_own_role_or_company(
    client: TestClient, db: Session, admin_csrf: str
) -> None:
    token = invite(client, admin_csrf, "rae@acme.test", "interviewer").json()["token"]
    other = make_company(db, "Other")
    db.commit()

    response = client.post(
        "/api/invitations/accept",
        json={
            "token": token,
            "full_name": "Sneaky",
            "password": DEFAULT_PASSWORD,
            "role": "company_admin",
            "company_id": str(other.id),
        },
    )

    assert response.status_code == 422
    assert accept(client, token).json()["user"]["role"] == "interviewer"  # still usable


def test_a_weak_password_is_refused_and_the_link_stays_usable(
    client: TestClient, admin_csrf: str
) -> None:
    token = invite(client, admin_csrf, "rae@acme.test").json()["token"]

    response = accept(client, token, password="short")

    assert response.status_code == 422
    assert accept(client, token).status_code == 201


def test_if_the_email_registered_elsewhere_meanwhile_the_link_is_refused(
    client: TestClient, db: Session, admin_csrf: str
) -> None:
    token = invite(client, admin_csrf, "rae@acme.test").json()["token"]
    make_user(db, email="rae@acme.test", role=Role.CANDIDATE, company=None)
    db.commit()

    response = accept(client, token)

    assert response.status_code == 400
    assert response.json() == INVALID_LINK
    assert db.scalars(select(User).where(User.email == "rae@acme.test")).all().__len__() == 1


def test_accepting_marks_the_invitation_used(
    client: TestClient, db: Session, admin_csrf: str
) -> None:
    token = invite(client, admin_csrf, "rae@acme.test").json()["token"]

    accept(client, token)

    stored = db.scalar(select(Invitation))
    assert stored is not None and stored.accepted_at is not None


def test_the_whole_story_signup_invite_accept_login(client: TestClient) -> None:
    csrf_token = sign_up_company(client, "Acme", "admin@acme.test")
    token = invite(client, csrf_token, "rae@acme.test").json()["token"]
    client.cookies.clear()

    accepted = accept(client, token)
    client.cookies.clear()
    login = client.post(
        "/api/auth/login", json={"email": "rae@acme.test", "password": DEFAULT_PASSWORD}
    )

    assert accepted.status_code == 201
    assert login.status_code == 200
    assert login.json()["user"]["role"] == "recruiter"
