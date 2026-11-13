"""Tenant isolation (security.md > Authorization): company A can never see or touch company B.

This is the project's biggest security promise, so the test is built to resist being forgotten:

* Every route must be classified below. A new route that is not listed fails the guard test, which
  says what to do. "I forgot to write the isolation test" cannot reach production.
* Every id-based route is attacked as company A against company B's ids and must answer 404.
* Each attack has a *control*: the identical request against company A's own data must succeed.
  Without it, a typo in the request would make every attack "pass" for the wrong reason.
* After the attacks, company B's data is checked to be untouched.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.sessions import SESSION_COOKIE_NAME, create_session
from app.models import AuditLog, Department, Invitation, Job, PostingStatus, Role, User
from tests.factories import make_company, make_job, make_user
from tests.test_route_matrix import ROUTES

NOT_FOUND = {"detail": "Not found."}


@dataclass
class Tenant:
    """One company's world: staff, a pending invitation, departments and two jobs."""

    name: str
    company_id: uuid.UUID
    admin: User
    recruiter: User
    interviewer: User
    recruiter2: User  # assigned to nothing
    invitation: Invitation
    department: Department  # used by the jobs below
    spare_department: Department  # used by nothing, so it can be deleted
    job: Job  # a draft the first recruiter is assigned to
    open_job: Job  # open, same recruiter


def build_tenant(db: Session, name: str) -> Tenant:
    company = make_company(db, name)
    slug = name.lower()
    admin = make_user(db, email=f"admin@{slug}.test", role=Role.COMPANY_ADMIN, company=company)
    recruiter = make_user(db, email=f"rec@{slug}.test", role=Role.RECRUITER, company=company)
    interviewer = make_user(db, email=f"int@{slug}.test", role=Role.INTERVIEWER, company=company)
    recruiter2 = make_user(db, email=f"rec2@{slug}.test", role=Role.RECRUITER, company=company)
    invitation = Invitation(
        company_id=company.id,
        email=f"newcomer@{slug}.test",
        role=Role.RECRUITER,
        token_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        invited_by=admin.id,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    department = Department(company_id=company.id, name=f"Engineering of {name}")
    spare_department = Department(company_id=company.id, name=f"Spare of {name}")
    db.add_all([invitation, department, spare_department])
    db.flush()
    job = make_job(
        db, company=company, department=department, created_by=admin, recruiters=[recruiter]
    )
    open_job = make_job(
        db,
        company=company,
        department=department,
        created_by=admin,
        recruiters=[recruiter],
        status=PostingStatus.OPEN,
    )
    return Tenant(
        name,
        company.id,
        admin,
        recruiter,
        interviewer,
        recruiter2,
        invitation,
        department,
        spare_department,
        job,
        open_job,
    )


@pytest.fixture
def world(db: Session) -> tuple[Tenant, Tenant]:
    a, b = build_tenant(db, "Acme"), build_tenant(db, "Globex")
    db.commit()
    return a, b


def act_as_admin_of(client: TestClient, db: Session, tenant: Tenant) -> str:
    """Log the client in as this tenant's admin; return the CSRF token."""
    token, session = create_session(db, tenant.admin, datetime.now(UTC))
    db.commit()
    client.cookies.clear()
    client.cookies.set(SESSION_COOKIE_NAME, token)
    return session.csrf_token


# ---- the registry: every route is classified ---------------------------------------------


@dataclass(frozen=True)
class IdCase:
    """A route that takes the id of a company-scoped row."""

    key: str
    # Which row of a tenant the id comes from, and the body (if any) that makes it a valid request.
    target: Callable[[Tenant], Any]
    # The body may depend on the tenant whose row is addressed.
    json: dict[str, Any] | Callable[[Tenant], dict[str, Any]] | None = None
    path_param: str = "user_id"
    # For routes with a second id in the path.
    extra_params: Callable[[Tenant], dict[str, uuid.UUID]] | None = None
    ok_status: int = 200


ID_CASES = [
    IdCase("PATCH /api/users/{user_id}/role", lambda t: t.recruiter, {"role": "interviewer"}),
    IdCase("POST /api/users/{user_id}/deactivate", lambda t: t.recruiter),
    IdCase("POST /api/users/{user_id}/reactivate", lambda t: t.recruiter),
    IdCase(
        "PATCH /api/departments/{department_id}",
        lambda t: t.department,
        {"name": "Renamed"},
        path_param="department_id",
    ),
    IdCase(
        "POST /api/departments/{department_id}/archive",
        lambda t: t.department,
        path_param="department_id",
    ),
    IdCase(
        "POST /api/departments/{department_id}/unarchive",
        lambda t: t.department,
        path_param="department_id",
    ),
    IdCase(
        "DELETE /api/departments/{department_id}",
        lambda t: t.spare_department,
        path_param="department_id",
        ok_status=204,
    ),
    IdCase("GET /api/jobs/{job_id}", lambda t: t.job, path_param="job_id"),
    IdCase(
        "PATCH /api/jobs/{job_id}",
        lambda t: t.job,
        {"version": 1, "title": "Renamed"},
        path_param="job_id",
    ),
    IdCase("POST /api/jobs/{job_id}/publish", lambda t: t.job, {"version": 1}, path_param="job_id"),
    IdCase(
        "POST /api/jobs/{job_id}/close", lambda t: t.open_job, {"version": 1}, path_param="job_id"
    ),
    IdCase("DELETE /api/jobs/{job_id}", lambda t: t.job, path_param="job_id", ok_status=204),
    IdCase(
        "POST /api/jobs/{job_id}/recruiters",
        lambda t: t.job,
        lambda t: {"user_id": str(t.recruiter2.id)},
        path_param="job_id",
    ),
    IdCase(
        "DELETE /api/jobs/{job_id}/recruiters/{user_id}",
        lambda t: t.job,
        path_param="job_id",
        extra_params=lambda t: {"user_id": t.recruiter.id},
        ok_status=204,
    ),
]


@dataclass(frozen=True)
class ListCase:
    """A route that lists company-scoped rows: it must contain only the caller's own."""

    key: str
    ids_in_response: Callable[[Any], set[str]]
    own_ids: Callable[[Tenant], set[str]]


LIST_CASES = [
    ListCase(
        "GET /api/users",
        lambda body: {user["id"] for user in body},
        lambda t: {
            str(t.admin.id),
            str(t.recruiter.id),
            str(t.interviewer.id),
            str(t.recruiter2.id),
        },
    ),
    ListCase(
        "GET /api/invitations",
        lambda body: {invitation["id"] for invitation in body},
        lambda t: {str(t.invitation.id)},
    ),
    ListCase(
        "GET /api/departments",
        lambda body: {department["id"] for department in body["items"]},
        lambda t: {str(t.department.id), str(t.spare_department.id)},
    ),
    ListCase(
        "GET /api/recruiters",
        lambda body: {person["id"] for person in body["items"]},
        lambda t: {str(t.recruiter.id), str(t.recruiter2.id)},
    ),
    ListCase(
        "GET /api/jobs",
        lambda body: {job["id"] for job in body["items"]},
        lambda t: {str(t.job.id), str(t.open_job.id)},
    ),
]

# Routes that need no isolation case, and why. Adding a route here is a decision a reviewer sees.
NOT_COMPANY_SCOPED = {
    "GET /health": "no data",
    "GET /ready": "no data",
    "GET /health/worker": "no data",
    "GET /health/jobs": "no data",
    "POST /api/auth/login": "public; the user is found by their own credentials",
    "GET /api/auth/me": "returns the caller's own session only",
    "POST /api/auth/logout": "ends the caller's own session only",
    "POST /api/auth/verify-email": "public; the user is found by a signed link, no id taken",
    "POST /api/auth/resend-verification": "acts on the caller's own account only",
    "POST /api/auth/forgot-password": "public; takes an email, never an id; one answer for all",
    "POST /api/auth/reset-password": "public; the user is found by a signed link, no id taken",
    "POST /api/companies": "creates a new company; takes no existing id",
    "POST /api/invitations/accept": "public; the invitation is found by its secret token",
    "POST /api/invitations": "creates in the caller's own company; takes no foreign id "
    "(see test_inviting_does_not_disturb_another_companys_invitation)",
    "GET /api/public/jobs": "public by design: lists only OPEN jobs of every company, a fixed "
    "set of fields (see tests/test_public_jobs.py)",
    "GET /api/public/jobs/{job_id}": "public by design: an id returns the job only if it is "
    "OPEN, and the same 404 as for an unknown id otherwise (see tests/test_public_jobs.py)",
    "POST /api/candidates": "public; creates a new candidate account (no company); takes no "
    "existing id",
    "GET /api/profile": "acts on the caller's own profile only; takes no id (see "
    "test_one_candidate_cannot_change_another)",
    "PATCH /api/profile": "acts on the caller's own profile only; takes no id (see "
    "test_one_candidate_cannot_change_another)",
    "POST /api/jobs": "creates in the caller's own company; the department must be the caller's "
    "own (see test_a_department_of_another_company_unknown_or_archived_cannot_be_used)",
    "POST /api/departments": "creates in the caller's own company; the company comes from the "
    "session and a company id in the body is refused (see test_unknown_fields_are_refused)",
}


def test_every_route_is_classified_for_isolation() -> None:
    classified = (
        {case.key for case in ID_CASES}
        | {case.key for case in LIST_CASES}
        | set(NOT_COMPANY_SCOPED)
    )

    unclassified = set(ROUTES) - classified
    assert unclassified == set(), (
        f"New route(s) {sorted(unclassified)}: add an IdCase or ListCase (they touch company "
        "data) or a reasoned entry in NOT_COMPANY_SCOPED (they do not)."
    )
    assert classified - set(ROUTES) == set(), "the registry names route(s) that no longer exist"


# Routes with an id in the path that may deliberately be read by anyone. Each has its own tests
# that it exposes nothing but what is meant to be public.
PUBLIC_ROUTES_WITH_ID = {"GET /api/public/jobs/{job_id}"}


def test_a_route_with_a_path_id_must_have_an_id_case() -> None:
    # A path parameter is the classic way to ask for someone else's row.
    with_ids = {key for key in ROUTES if "{" in key} - PUBLIC_ROUTES_WITH_ID

    assert with_ids == {case.key for case in ID_CASES}


def test_the_exemption_for_public_routes_with_an_id_is_only_for_public_routes() -> None:
    from tests.test_route_matrix import POLICY

    assert PUBLIC_ROUTES_WITH_ID <= set(ROUTES)
    assert all(POLICY[key] is None for key in PUBLIC_ROUTES_WITH_ID)


# ---- the attacks -------------------------------------------------------------------------


def send(client: TestClient, case: IdCase, tenant: Tenant, csrf: str) -> Any:
    """Make the case's request against this tenant's row."""
    method, template = case.key.split(" ", 1)
    path = template.replace("{" + case.path_param + "}", str(case.target(tenant).id))
    if case.extra_params is not None:
        for name, value in case.extra_params(tenant).items():
            path = path.replace("{" + name + "}", str(value))
    body = case.json(tenant) if callable(case.json) else case.json
    return client.request(method, path, headers={"X-CSRF-Token": csrf}, json=body)


@pytest.mark.parametrize("case", ID_CASES, ids=lambda case: case.key)
def test_company_a_cannot_reach_company_bs_rows_by_id(
    client: TestClient, db: Session, world: tuple[Tenant, Tenant], case: IdCase
) -> None:
    a, b = world
    csrf = act_as_admin_of(client, db, a)

    response = send(client, case, b, csrf)

    assert response.status_code == 404
    assert response.json() == NOT_FOUND  # the same body as for an id that does not exist at all


@pytest.mark.parametrize("case", ID_CASES, ids=lambda case: case.key)
def test_the_same_request_works_on_the_callers_own_company(
    client: TestClient, db: Session, world: tuple[Tenant, Tenant], case: IdCase
) -> None:
    # The control: if this failed, the attack above would be "passing" because of a bad request.
    a, _ = world
    csrf = act_as_admin_of(client, db, a)

    response = send(client, case, a, csrf)

    assert response.status_code == case.ok_status


def test_the_attacks_left_company_b_untouched(
    client: TestClient, db: Session, world: tuple[Tenant, Tenant]
) -> None:
    a, b = world
    csrf = act_as_admin_of(client, db, a)

    for case in ID_CASES:
        send(client, case, b, csrf)

    db.expire_all()
    for member in (b.admin, b.recruiter, b.interviewer):
        stored = db.get(User, member.id)
        assert stored is not None
        assert stored.role == member.role and stored.is_active and stored.deactivated_at is None
    for untouched_job, expected_status in ((b.job, "draft"), (b.open_job, "open")):
        stored_job = db.get(Job, untouched_job.id)
        assert stored_job is not None
        assert stored_job.status == expected_status and stored_job.version == 1
        assert stored_job.title == untouched_job.title
    assert db.get(Department, b.spare_department.id) is not None
    stored_department = db.get(Department, b.department.id)
    assert stored_department is not None
    assert stored_department.name == f"Engineering of {b.name}"
    assert stored_department.is_archived is False
    audit_for_b = db.scalars(select(AuditLog).where(AuditLog.company_id == b.company_id)).all()
    assert audit_for_b == []


@pytest.mark.parametrize("case", LIST_CASES, ids=lambda case: case.key)
def test_lists_contain_only_the_callers_own_rows(
    client: TestClient, db: Session, world: tuple[Tenant, Tenant], case: ListCase
) -> None:
    a, b = world
    act_as_admin_of(client, db, a)
    method, path = case.key.split(" ", 1)

    response = client.request(method, path)

    assert response.status_code == 200
    ids = case.ids_in_response(response.json())
    assert ids == case.own_ids(a)  # all of A's (so the list is not just empty) and none of B's
    assert ids.isdisjoint(case.own_ids(b))


def test_inviting_does_not_disturb_another_companys_invitation(
    client: TestClient, db: Session, world: tuple[Tenant, Tenant]
) -> None:
    # Re-inviting an address revokes the older link. That must only ever touch the caller's own.
    a, b = world
    csrf = act_as_admin_of(client, db, a)

    response = client.post(
        "/api/invitations",
        json={"email": b.invitation.email, "role": "recruiter"},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 201
    db.expire_all()
    stored = db.get(Invitation, b.invitation.id)
    assert stored is not None
    assert stored.revoked_at is None and stored.accepted_at is None
