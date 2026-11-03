"""require_permission: default-deny authorization (security.md > Authorization).

These tests use a tiny app of their own, so they check the mechanism, not any real route.
"""

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth.permissions import ROLE_PERMISSIONS, Permission, require_permission
from app.auth.sessions import SESSION_COOKIE_NAME, create_session
from app.db import get_db
from app.models import Role, User
from tests.factories import make_company, make_user


def build_test_app(db: Session) -> FastAPI:
    app = FastAPI()
    app.dependency_overrides[get_db] = lambda: db

    @app.get("/anyone")
    def anyone(user: User = Depends(require_permission(Permission.ACCOUNT_SELF))) -> dict[str, str]:
        return {"email": user.email}

    @app.get("/admin-read")
    def admin_read(
        user: User = Depends(require_permission(Permission.MANAGE_USERS)),
    ) -> dict[str, str]:
        return {"email": user.email}

    @app.post("/admin-write")
    def admin_write(
        user: User = Depends(require_permission(Permission.MANAGE_USERS)),
    ) -> dict[str, str]:
        return {"email": user.email}

    return app


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    with TestClient(build_test_app(db), base_url="https://testserver") as test_client:
        yield test_client


def log_in_as(client: TestClient, db: Session, role: Role) -> str:
    """Create a user with this role, give the client their session cookie, return the CSRF token."""
    company = None if role == Role.CANDIDATE else make_company(db)
    user = make_user(db, email=f"{role.value}@example.com", role=role, company=company)
    token, session = create_session(db, user, datetime.now(UTC))
    db.commit()
    client.cookies.set(SESSION_COOKIE_NAME, token)
    return session.csrf_token


# ---- the permission table ----------------------------------------------------------------


def test_every_role_has_an_entry_in_the_table() -> None:
    # A role someone forgets to list would silently get nothing, so the omission must be loud.
    assert set(ROLE_PERMISSIONS) == set(Role)


def test_every_role_may_use_its_own_account() -> None:
    for role in Role:
        assert Permission.ACCOUNT_SELF in ROLE_PERMISSIONS[role]


def test_only_company_admins_manage_users() -> None:
    allowed = {role for role in Role if Permission.MANAGE_USERS in ROLE_PERMISSIONS[role]}

    assert allowed == {Role.COMPANY_ADMIN}


# ---- the dependency ----------------------------------------------------------------------


def test_no_session_is_401(client: TestClient) -> None:
    assert client.get("/anyone").status_code == 401
    assert client.get("/admin-read").status_code == 401


def test_a_role_with_the_permission_gets_in(client: TestClient, db: Session) -> None:
    log_in_as(client, db, Role.COMPANY_ADMIN)

    response = client.get("/admin-read")

    assert response.status_code == 200
    assert response.json() == {"email": "company_admin@example.com"}


@pytest.mark.parametrize("role", [Role.RECRUITER, Role.INTERVIEWER, Role.CANDIDATE])
def test_a_role_without_the_permission_is_403(client: TestClient, db: Session, role: Role) -> None:
    log_in_as(client, db, role)

    assert client.get("/admin-read").status_code == 403


@pytest.mark.parametrize("role", list(Role))
def test_every_role_can_reach_a_route_open_to_all_logged_in_users(
    client: TestClient, db: Session, role: Role
) -> None:
    log_in_as(client, db, role)

    assert client.get("/anyone").status_code == 200


def test_changing_data_needs_the_csrf_token(client: TestClient, db: Session) -> None:
    csrf_token = log_in_as(client, db, Role.COMPANY_ADMIN)

    assert client.post("/admin-write").status_code == 403
    assert client.post("/admin-write", headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert client.post("/admin-write", headers={"X-CSRF-Token": csrf_token}).status_code == 200


def test_reading_does_not_need_the_csrf_token(client: TestClient, db: Session) -> None:
    log_in_as(client, db, Role.COMPANY_ADMIN)

    assert client.get("/admin-read").status_code == 200


def test_a_denied_role_is_403_even_with_a_valid_csrf_token(client: TestClient, db: Session) -> None:
    csrf_token = log_in_as(client, db, Role.RECRUITER)

    response = client.post("/admin-write", headers={"X-CSRF-Token": csrf_token})

    assert response.status_code == 403


def test_a_deactivated_user_is_401(client: TestClient, db: Session) -> None:
    log_in_as(client, db, Role.COMPANY_ADMIN)
    db.query(User).update({"is_active": False})
    db.commit()

    assert client.get("/admin-read").status_code == 401


def test_a_permission_missing_from_the_table_is_denied(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Default deny: if a role's permissions vanish, nothing is allowed. Nothing falls through.
    log_in_as(client, db, Role.COMPANY_ADMIN)
    monkeypatch.setitem(ROLE_PERMISSIONS, Role.COMPANY_ADMIN, frozenset())

    assert client.get("/admin-read").status_code == 403
