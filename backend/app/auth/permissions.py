"""Who may do what. One table, default deny (security.md > Authorization).

Every route declares its access with `Depends(require_permission(...))` (logged-in users) or
`Depends(public_route)` (anyone). A test fails the build for a route that declares neither, and a
second one, built from `declared_access`, checks every role against every route.
"""

import enum

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from app.auth.current_user import get_current_session, get_current_user, verify_csrf
from app.models import Role, User, UserSession


class Permission(enum.StrEnum):
    # Use your own session: see who you are, log out. Every logged-in user has it.
    ACCOUNT_SELF = "account_self"
    MANAGE_USERS = "manage_users"


# A role that is missing from this table, or a permission missing from a role's set, means
# "denied". Nothing is allowed unless it is written down here.
ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.COMPANY_ADMIN: frozenset({Permission.ACCOUNT_SELF, Permission.MANAGE_USERS}),
    Role.RECRUITER: frozenset({Permission.ACCOUNT_SELF}),
    Role.INTERVIEWER: frozenset({Permission.ACCOUNT_SELF}),
    Role.CANDIDATE: frozenset({Permission.ACCOUNT_SELF}),
}


class PermissionCheck:
    """The dependency behind `require_permission`. A class (not a closure) so that the route
    audit below can recognise it and read which permission it demands."""

    def __init__(self, permission: Permission) -> None:
        self.permission = permission

    def __call__(
        self,
        request: Request,
        user: User = Depends(get_current_user),
        session: UserSession = Depends(get_current_session),
    ) -> User:
        # 401 (not logged in) is raised by the dependencies above; this is "logged in, but not
        # allowed".
        if self.permission not in ROLE_PERMISSIONS.get(user.role, frozenset()):
            raise HTTPException(status_code=403, detail="You do not have access to this.")
        verify_csrf(request, session)
        return user


def require_permission(permission: Permission) -> PermissionCheck:
    return PermissionCheck(permission)


def public_route() -> None:
    """Marks a route anyone may call, logged in or not. A deliberate, visible choice."""


class _Public(enum.Enum):
    PUBLIC = "public"


PUBLIC = _Public.PUBLIC


def _walk(dependant: Dependant) -> list[Permission | _Public]:
    found: list[Permission | _Public] = []
    if isinstance(dependant.call, PermissionCheck):
        found.append(dependant.call.permission)
    elif dependant.call is public_route:
        found.append(PUBLIC)
    for child in dependant.dependencies:
        found.extend(_walk(child))
    return found


def declared_access(route: APIRoute) -> list[Permission | _Public]:
    """Everything this route declares, however deep in its dependencies. Exactly one is correct."""
    return _walk(route.dependant)


def undeclared_routes(app: FastAPI) -> list[str]:
    """Routes that declare no access, or ambiguously more than one. Empty means all good."""
    problems = []
    for route in app.routes:
        if isinstance(route, APIRoute) and len(declared_access(route)) != 1:
            methods = ",".join(sorted(route.methods or []))
            problems.append(f"{methods} {route.path}")
    return problems
