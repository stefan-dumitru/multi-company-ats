"""The role x endpoint matrix (security.md > Authorization): who may call which route.

Two independent checks, so a mistake has to be made twice to slip through:

1. POLICY below is written by hand: for each route, the roles that should be let in.
   Every test compares the *running app* against it, so someone changing `ROLE_PERMISSIONS` or
   a route's declaration changes behaviour and trips these tests until the policy is updated on
   purpose, in a pull request a reviewer can read.
2. The matrix itself is generated from the app's real route table, so a new route cannot be
   forgotten: the test that compares the route table with POLICY fails until it is added.

Denial must happen before the request body is even looked at, so the requests need no valid
payloads: a route that answers 422 to a denied role would be leaking that it exists.
"""

import re
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth.permissions import (
    PUBLIC,
    ROLE_PERMISSIONS,
    Permission,
    declared_access,
    iter_api_routes,
)
from app.auth.sessions import SESSION_COOKIE_NAME, create_session
from app.main import app as real_app
from app.models import Role
from tests.factories import make_company, make_user

ADMIN_ONLY = frozenset({Role.COMPANY_ADMIN})
ADMIN_AND_RECRUITER = frozenset({Role.COMPANY_ADMIN, Role.RECRUITER})
EVERY_LOGGED_IN_ROLE = frozenset(Role)
# None means "public": anyone, logged in or not.
POLICY: dict[str, frozenset[Role] | None] = {
    "GET /health": None,
    "GET /ready": None,
    "GET /health/worker": None,
    "GET /health/jobs": None,
    "POST /api/auth/login": None,
    "GET /api/auth/me": EVERY_LOGGED_IN_ROLE,
    "POST /api/auth/logout": EVERY_LOGGED_IN_ROLE,
    "POST /api/auth/verify-email": None,
    "POST /api/auth/resend-verification": EVERY_LOGGED_IN_ROLE,
    "POST /api/auth/forgot-password": None,
    "POST /api/auth/reset-password": None,
    "POST /api/companies": None,
    "POST /api/invitations": ADMIN_ONLY,
    "GET /api/invitations": ADMIN_ONLY,
    "POST /api/invitations/accept": None,
    "GET /api/users": ADMIN_ONLY,
    "PATCH /api/users/{user_id}/role": ADMIN_ONLY,
    "POST /api/users/{user_id}/deactivate": ADMIN_ONLY,
    "POST /api/users/{user_id}/reactivate": ADMIN_ONLY,
    "GET /api/departments": ADMIN_AND_RECRUITER,
    "POST /api/departments": ADMIN_ONLY,
    "PATCH /api/departments/{department_id}": ADMIN_ONLY,
    "POST /api/departments/{department_id}/archive": ADMIN_ONLY,
    "POST /api/departments/{department_id}/unarchive": ADMIN_ONLY,
    "DELETE /api/departments/{department_id}": ADMIN_ONLY,
    "GET /api/public/jobs": None,
    "GET /api/public/jobs/{job_id}": None,
    "GET /api/recruiters": ADMIN_AND_RECRUITER,
    "GET /api/jobs": ADMIN_AND_RECRUITER,
    "POST /api/jobs": ADMIN_AND_RECRUITER,
    "GET /api/jobs/{job_id}": ADMIN_AND_RECRUITER,
    "PATCH /api/jobs/{job_id}": ADMIN_AND_RECRUITER,
    "POST /api/jobs/{job_id}/publish": ADMIN_AND_RECRUITER,
    "POST /api/jobs/{job_id}/close": ADMIN_AND_RECRUITER,
    "DELETE /api/jobs/{job_id}": ADMIN_AND_RECRUITER,
    "POST /api/jobs/{job_id}/recruiters": ADMIN_AND_RECRUITER,
    "DELETE /api/jobs/{job_id}/recruiters/{user_id}": ADMIN_AND_RECRUITER,
}


def real_routes() -> dict[str, APIRoute]:
    found: dict[str, APIRoute] = {}
    for route in iter_api_routes(real_app):
        for method in sorted(route.methods):
            found[f"{method} {route.path}"] = route
    return found


ROUTES = real_routes()


def concrete_path(template: str) -> str:
    """Fill every path parameter with a random id: the request must be refused (or not found)
    on its permission alone, whatever the id is."""
    for name in re.findall(r"\{([^}]+)\}", template):
        assert name.endswith("_id"), f"{template}: add a way to fill {{{name}}} to this test"
    return re.sub(r"\{[^}]+\}", lambda _match: str(uuid.uuid4()), template)


@pytest.fixture
def visitor(client: TestClient, db: Session) -> Iterator[TestClient]:
    yield client


def log_in_as(client: TestClient, db: Session, role: Role, *, verified: bool = True) -> str:
    """Give the client a brand-new session for a user with this role; return its CSRF token.

    A new session per call, because some routes (logout) end the session they are called with.
    """
    company = None if role == Role.CANDIDATE else make_company(db, f"Company of {uuid.uuid4().hex}")
    user = make_user(
        db, email=f"{uuid.uuid4().hex}@example.test", role=role, company=company, verified=verified
    )
    token, session = create_session(db, user, datetime.now(UTC))
    db.commit()
    client.cookies.clear()
    client.cookies.set(SESSION_COOKIE_NAME, token)
    return session.csrf_token


def call(client: TestClient, key: str, csrf_token: str | None = None) -> int:
    method, template = key.split(" ", 1)
    headers = {"X-CSRF-Token": csrf_token} if csrf_token else {}
    return client.request(method, concrete_path(template), headers=headers).status_code


# ---- the policy and the route table must agree -------------------------------------------


def test_every_route_has_a_policy_and_every_policy_has_a_route() -> None:
    routes, policy = set(ROUTES), set(POLICY)

    assert routes - policy == set(), "new route(s): add them to POLICY on purpose"
    assert policy - routes == set(), "POLICY lists route(s) that no longer exist"


def test_the_policy_matches_what_the_routes_declare() -> None:
    derived: dict[str, frozenset[Role] | None] = {}
    for key, route in ROUTES.items():
        (declared,) = declared_access(route)
        if declared is PUBLIC:
            derived[key] = None
        else:
            derived[key] = frozenset(
                role for role in Role if declared in ROLE_PERMISSIONS.get(role, frozenset())
            )

    assert derived == POLICY


# ---- the live matrix ---------------------------------------------------------------------


@pytest.mark.parametrize("key", sorted(ROUTES))
def test_not_logged_in(visitor: TestClient, key: str) -> None:
    status = call(visitor, key)

    if POLICY[key] is None:
        assert status not in (401, 403), f"{key} is public but answered {status}"
    else:
        assert status == 401, f"{key} answered {status} to a visitor who is not logged in"


@pytest.mark.parametrize("role", list(Role), ids=lambda role: role.value)
@pytest.mark.parametrize("key", sorted(ROUTES))
def test_each_role_on_each_route(client: TestClient, db: Session, key: str, role: Role) -> None:
    allowed = POLICY[key]
    csrf_token = log_in_as(client, db, role)

    status = call(client, key, csrf_token)

    if allowed is None or role in allowed:
        assert status not in (401, 403), f"{role.value} should reach {key} but got {status}"
    else:
        assert status == 403, f"{role.value} should be refused on {key} but got {status}"


# ---- the "unverified" dimension ----------------------------------------------------------
# A user whose email is not verified can log in and use their own account, nothing else.

NOT_VERIFIED_BODY = {"detail": "Verify your email first.", "code": "email_not_verified"}


@pytest.mark.parametrize("role", list(Role), ids=lambda role: role.value)
@pytest.mark.parametrize("key", sorted(ROUTES))
def test_each_role_on_each_route_while_unverified(
    client: TestClient, db: Session, key: str, role: Role
) -> None:
    allowed = POLICY[key]
    csrf_token = log_in_as(client, db, role, verified=False)
    method, template = key.split(" ", 1)

    response = client.request(method, concrete_path(template), headers={"X-CSRF-Token": csrf_token})

    if allowed is None:
        # Public routes do not care who you are.
        assert response.status_code not in (401, 403), f"{key} is public but answered it"
    elif role not in allowed:
        # Refused for the role, whatever the verification state; no misleading "verify" hint.
        assert response.status_code == 403
        assert response.json() != NOT_VERIFIED_BODY, f"{key} hinted at verification to {role.value}"
    elif declared_access(ROUTES[key]) == [Permission.ACCOUNT_SELF]:
        assert response.status_code not in (401, 403), f"unverified {role.value} lost {key}"
    else:
        assert response.status_code == 403
        assert response.json() == NOT_VERIFIED_BODY, f"{key} let an unverified {role.value} in"
