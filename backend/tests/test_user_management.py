"""Listing users, changing roles, deactivating and reactivating (functional.md > Invite and
deactivate staff; data-model.md > User)."""

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.main import app
from app.models import AuditLog, Role, User
from app.services import users as users_service
from tests.factories import DEFAULT_PASSWORD, verify_email_of

NOT_FOUND = {"detail": "Not found."}
LAST_ADMIN = {"detail": "A company must keep at least one active admin."}


class Account:
    """A logged-in browser: its own cookie jar and CSRF token."""

    def __init__(self, http: TestClient, csrf_token: str, user_id: str, email: str) -> None:
        self.http = http
        self.csrf_token = csrf_token
        self.user_id = user_id
        self.email = email

    def get(self, path: str) -> Response:
        return self.http.get(path)

    def send(self, method: str, path: str, **kwargs: object) -> Response:
        return self.http.request(
            method,
            path,
            headers={"X-CSRF-Token": self.csrf_token},
            **kwargs,  # type: ignore[arg-type]
        )

    def set_role(self, user_id: str, role: str) -> Response:
        return self.send("PATCH", f"/api/users/{user_id}/role", json={"role": role})

    def deactivate(self, user_id: str) -> Response:
        return self.send("POST", f"/api/users/{user_id}/deactivate")

    def reactivate(self, user_id: str) -> Response:
        return self.send("POST", f"/api/users/{user_id}/reactivate")


@pytest.fixture
def browsers(client: TestClient) -> Iterator[list[TestClient]]:
    """Fresh browsers on demand (each has its own cookies); the `client` fixture is the first."""
    made: list[TestClient] = []
    yield made
    for extra in made:
        extra.close()


class Company:
    """Builds a company through the real API: signup, then invite + accept for each teammate."""

    def __init__(
        self, http: TestClient, db: Session, browsers: list[TestClient], name: str
    ) -> None:
        self.db = db
        self.browsers = browsers
        self.name = name
        self.slug = name.lower()
        response = http.post(
            "/api/companies",
            json={
                "company_name": name,
                "full_name": f"Admin of {name}",
                "email": f"admin@{self.slug}.test",
                "password": DEFAULT_PASSWORD,
            },
        )
        assert response.status_code == 201, response.text
        verify_email_of(db, f"admin@{self.slug}.test")
        body = response.json()
        self.admin = Account(http, body["csrf_token"], body["user"]["id"], body["user"]["email"])

    def add(self, name: str, role: str) -> Account:
        email = f"{name}@{self.slug}.test"
        invited = self.admin.send("POST", "/api/invitations", json={"email": email, "role": role})
        assert invited.status_code == 201, invited.text
        http = new_browser(self.browsers)
        accepted = http.post(
            "/api/invitations/accept",
            json={
                "token": invited.json()["token"],
                "full_name": name.title(),
                "password": DEFAULT_PASSWORD,
            },
        )
        assert accepted.status_code == 201, accepted.text
        verify_email_of(self.db, email)
        body = accepted.json()
        return Account(http, body["csrf_token"], body["user"]["id"], email)


def new_browser(browsers: list[TestClient]) -> TestClient:
    """A browser with its own, empty cookie jar, closed again when the test ends."""
    http = TestClient(app, base_url="https://testserver")
    browsers.append(http)
    return http


@pytest.fixture
def acme(client: TestClient, db: Session, browsers: list[TestClient]) -> Company:
    return Company(client, db, browsers, "Acme")


@pytest.fixture
def globex(db: Session, browsers: list[TestClient]) -> Company:
    return Company(new_browser(browsers), db, browsers, "Globex")


def audit_rows(db: Session, action: str) -> list[AuditLog]:
    return list(db.scalars(select(AuditLog).where(AuditLog.action == action)))


# ---- listing -----------------------------------------------------------------------------


def test_the_list_shows_this_companys_people_and_nobody_elses(
    acme: Company, globex: Company
) -> None:
    acme.add("rae", "recruiter")
    globex.add("gus", "recruiter")

    response = acme.admin.get("/api/users")

    assert response.status_code == 200
    assert {user["email"] for user in response.json()} == {"admin@acme.test", "rae@acme.test"}


def test_the_list_describes_each_user_without_secrets(acme: Company) -> None:
    acme.add("rae", "recruiter")

    response = acme.admin.get("/api/users")

    rae = next(user for user in response.json() if user["email"] == "rae@acme.test")
    assert rae["role"] == "recruiter"
    assert rae["is_active"] is True
    assert rae["full_name"] == "Rae"
    assert "password" not in response.text
    assert "argon2" not in response.text


@pytest.mark.parametrize("role", ["recruiter", "interviewer"])
def test_only_admins_may_use_user_management(acme: Company, role: str) -> None:
    member = acme.add("member", role)

    assert member.get("/api/users").status_code == 403
    assert member.set_role(acme.admin.user_id, "recruiter").status_code == 403
    assert member.deactivate(acme.admin.user_id).status_code == 403
    assert member.reactivate(acme.admin.user_id).status_code == 403


def test_user_management_requires_login(client: TestClient) -> None:
    some_id = uuid.uuid4()

    assert client.get("/api/users").status_code == 401
    assert client.patch(f"/api/users/{some_id}/role", json={"role": "recruiter"}).status_code == 401
    assert client.post(f"/api/users/{some_id}/deactivate").status_code == 401
    assert client.post(f"/api/users/{some_id}/reactivate").status_code == 401


def test_changes_need_the_csrf_token(acme: Company) -> None:
    rae = acme.add("rae", "recruiter")
    http = acme.admin.http

    assert (
        http.patch(f"/api/users/{rae.user_id}/role", json={"role": "interviewer"}).status_code
        == 403
    )
    assert http.post(f"/api/users/{rae.user_id}/deactivate").status_code == 403
    assert http.post(f"/api/users/{rae.user_id}/reactivate").status_code == 403


# ---- tenant isolation --------------------------------------------------------------------


def test_another_companys_user_is_not_found_for_every_action(
    db: Session, acme: Company, globex: Company
) -> None:
    gus = globex.add("gus", "recruiter")

    for response in (
        acme.admin.set_role(gus.user_id, "interviewer"),
        acme.admin.deactivate(gus.user_id),
        acme.admin.reactivate(gus.user_id),
    ):
        assert response.status_code == 404
        assert response.json() == NOT_FOUND

    still_gus = db.get(User, uuid.UUID(gus.user_id))
    assert still_gus is not None
    db.refresh(still_gus)
    assert still_gus.role == Role.RECRUITER and still_gus.is_active


def test_an_unknown_id_looks_exactly_like_another_companys(acme: Company) -> None:
    response = acme.admin.deactivate(str(uuid.uuid4()))

    assert response.status_code == 404
    assert response.json() == NOT_FOUND


def test_a_malformed_id_is_a_validation_error(acme: Company) -> None:
    assert acme.admin.deactivate("not-a-uuid").status_code == 422


# ---- changing roles ----------------------------------------------------------------------


def test_an_admin_can_change_a_role_and_it_is_audited(db: Session, acme: Company) -> None:
    rae = acme.add("rae", "recruiter")

    response = acme.admin.set_role(rae.user_id, "interviewer")

    assert response.status_code == 200
    assert response.json()["role"] == "interviewer"
    (row,) = audit_rows(db, "user.role_changed")
    assert str(row.actor_user_id) == acme.admin.user_id
    assert str(row.entity_id) == rae.user_id
    assert row.entity_type == "user"
    assert row.old_value == {"role": "recruiter"}
    assert row.new_value == {"role": "interviewer"}
    assert row.company_id is not None


def test_a_role_change_applies_at_the_very_next_request(acme: Company) -> None:
    second_admin = acme.add("boss", "company_admin")
    assert second_admin.get("/api/users").status_code == 200

    acme.admin.set_role(second_admin.user_id, "recruiter")

    assert second_admin.get("/api/users").status_code == 403


def test_setting_the_role_a_user_already_has_changes_nothing(db: Session, acme: Company) -> None:
    rae = acme.add("rae", "recruiter")

    response = acme.admin.set_role(rae.user_id, "recruiter")

    assert response.status_code == 200
    assert audit_rows(db, "user.role_changed") == []


@pytest.mark.parametrize("role", ["candidate", "superuser", ""])
def test_only_staff_roles_can_be_assigned(acme: Company, role: str) -> None:
    rae = acme.add("rae", "recruiter")

    assert acme.admin.set_role(rae.user_id, role).status_code == 422


def test_extra_fields_in_a_role_change_are_rejected(acme: Company) -> None:
    rae = acme.add("rae", "recruiter")

    response = acme.admin.send(
        "PATCH",
        f"/api/users/{rae.user_id}/role",
        json={"role": "interviewer", "company_id": str(uuid.uuid4())},
    )

    assert response.status_code == 422


# ---- the last admin ----------------------------------------------------------------------


def test_the_only_admin_cannot_be_demoted_or_deactivated(db: Session, acme: Company) -> None:
    for response in (
        acme.admin.set_role(acme.admin.user_id, "recruiter"),
        acme.admin.deactivate(acme.admin.user_id),
    ):
        assert response.status_code == 409
        assert response.json() == LAST_ADMIN

    assert audit_rows(db, "user.role_changed") == []
    assert audit_rows(db, "user.deactivated") == []
    assert acme.admin.get("/api/users").status_code == 200


def test_with_two_admins_one_may_step_down_but_then_the_other_is_protected(
    acme: Company,
) -> None:
    boss = acme.add("boss", "company_admin")

    assert boss.set_role(acme.admin.user_id, "recruiter").status_code == 200

    assert boss.set_role(boss.user_id, "recruiter").status_code == 409
    assert boss.deactivate(boss.user_id).status_code == 409


def test_a_deactivated_admin_does_not_count_as_one(acme: Company) -> None:
    boss = acme.add("boss", "company_admin")
    assert acme.admin.deactivate(boss.user_id).status_code == 200

    assert acme.admin.deactivate(acme.admin.user_id).status_code == 409
    assert acme.admin.set_role(acme.admin.user_id, "recruiter").status_code == 409


def test_another_companys_admins_do_not_count_for_this_one(acme: Company, globex: Company) -> None:
    # Globex has an admin, but Acme's only admin is still Acme's only admin.
    assert acme.admin.deactivate(acme.admin.user_id).status_code == 409


def test_an_admin_may_deactivate_themself_when_another_admin_remains(acme: Company) -> None:
    boss = acme.add("boss", "company_admin")

    assert acme.admin.deactivate(acme.admin.user_id).status_code == 200
    assert acme.admin.get("/api/users").status_code == 401  # their own session just ended
    assert boss.get("/api/users").status_code == 200


# ---- deactivating and reactivating -------------------------------------------------------


def test_deactivating_blocks_login_and_ends_open_sessions(
    acme: Company, browsers: list[TestClient]
) -> None:
    rae = acme.add("rae", "recruiter")
    assert rae.get("/api/auth/me").status_code == 200

    response = acme.admin.deactivate(rae.user_id)

    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert rae.get("/api/auth/me").status_code == 401  # the session she already had
    fresh = new_browser(browsers)
    login = fresh.post("/api/auth/login", json={"email": rae.email, "password": DEFAULT_PASSWORD})
    assert login.status_code == 401
    assert login.json() == {"detail": "Invalid email or password."}


def test_deactivating_keeps_the_users_data(db: Session, acme: Company) -> None:
    rae = acme.add("rae", "recruiter")

    acme.admin.deactivate(rae.user_id)

    stored = db.get(User, uuid.UUID(rae.user_id))
    assert stored is not None
    db.refresh(stored)
    assert stored.email == rae.email
    assert stored.is_active is False
    assert stored.deactivated_at is not None
    assert stored.password_hash is not None


def test_deactivation_and_reactivation_are_audited(db: Session, acme: Company) -> None:
    rae = acme.add("rae", "recruiter")

    acme.admin.deactivate(rae.user_id)
    acme.admin.reactivate(rae.user_id)

    (off,) = audit_rows(db, "user.deactivated")
    (on,) = audit_rows(db, "user.reactivated")
    assert off.old_value == {"is_active": True} and off.new_value == {"is_active": False}
    assert on.old_value == {"is_active": False} and on.new_value == {"is_active": True}
    assert str(off.entity_id) == str(on.entity_id) == rae.user_id


def test_repeating_an_action_changes_and_records_nothing_more(db: Session, acme: Company) -> None:
    rae = acme.add("rae", "recruiter")

    assert acme.admin.reactivate(rae.user_id).status_code == 200  # already active
    assert acme.admin.deactivate(rae.user_id).status_code == 200
    assert acme.admin.deactivate(rae.user_id).status_code == 200  # already inactive

    assert audit_rows(db, "user.reactivated") == []
    assert len(audit_rows(db, "user.deactivated")) == 1


def test_a_reactivated_user_can_log_in_again_with_their_old_password(
    acme: Company, browsers: list[TestClient]
) -> None:
    rae = acme.add("rae", "recruiter")
    acme.admin.deactivate(rae.user_id)

    acme.admin.reactivate(rae.user_id)

    fresh = new_browser(browsers)
    login = fresh.post("/api/auth/login", json={"email": rae.email, "password": DEFAULT_PASSWORD})
    assert login.status_code == 200


def test_old_sessions_stay_dead_after_reactivation(acme: Company) -> None:
    rae = acme.add("rae", "recruiter")
    acme.admin.deactivate(rae.user_id)

    acme.admin.reactivate(rae.user_id)

    assert rae.get("/api/auth/me").status_code == 401  # she must log in again


def test_the_change_and_its_audit_row_commit_together(
    db: Session, acme: Company, monkeypatch: pytest.MonkeyPatch
) -> None:
    rae = acme.add("rae", "recruiter")

    def failing_audit(*args: object, **kwargs: object) -> None:
        raise RuntimeError("audit write failed")

    # Patched where it is used: users.py imported the name, so that is the copy that runs.
    monkeypatch.setattr(users_service, "record_audit", failing_audit)
    quiet = TestClient(app, base_url="https://testserver", raise_server_exceptions=False)
    quiet.cookies.update(acme.admin.http.cookies)

    response = quiet.post(
        f"/api/users/{rae.user_id}/deactivate", headers={"X-CSRF-Token": acme.admin.csrf_token}
    )

    assert response.status_code == 500
    db.rollback()  # what the real server does when a request dies: nothing half-done survives
    stored = db.get(User, uuid.UUID(rae.user_id))
    assert stored is not None
    db.refresh(stored)
    assert stored.is_active is True
    assert rae.get("/api/auth/me").status_code == 200  # her session was not revoked either
