"""The CI gate: every route must declare who may call it (security.md > Authorization).

A route with no declaration fails the build, so forgetting authorization cannot reach production.
"""

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.routing import APIRoute
from starlette.routing import BaseRoute

from app.auth.permissions import (
    PUBLIC,
    Permission,
    UnsupportedRouteSetup,
    declared_access,
    iter_api_routes,
    public_route,
    require_permission,
    undeclared_routes,
)
from app.main import app as real_app

# Routes that are not ours: FastAPI's own documentation pages, and the static frontend mount. Any
# other non-APIRoute appearing in the app must be added here on purpose.
EXPECTED_NON_API_PATHS = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc", ""}


def test_every_route_of_the_real_app_declares_its_access() -> None:
    assert undeclared_routes(real_app) == []


def test_the_gate_really_sees_the_routes_inside_the_routers() -> None:
    # FastAPI does not flatten included routers into the app's route list. A gate that only looked
    # at the top level would inspect /health and /ready and pass while checking nothing else.
    paths = {route.path for route in iter_api_routes(real_app)}

    assert {"/health", "/ready", "/api/auth/login", "/api/users", "/api/invitations"} <= paths


def test_the_real_app_has_nothing_the_audit_cannot_read() -> None:
    list(iter_api_routes(real_app))  # raises UnsupportedRouteSetup on anything unrecognised

    others = {
        getattr(route, "path", None)
        for route in real_app.routes
        if not isinstance(route, APIRoute) and hasattr(route, "path")
    }
    assert others <= EXPECTED_NON_API_PATHS


def test_a_route_without_a_declaration_is_caught() -> None:
    app = FastAPI()

    @app.get("/forgotten")
    def forgotten() -> dict[str, str]:
        return {"oops": "anyone can call me"}

    assert undeclared_routes(app) == ["GET /forgotten"]


def test_a_route_declared_in_an_included_router_counts() -> None:
    router = APIRouter(prefix="/api")

    @router.get("/inner", dependencies=[Depends(public_route)])
    def inner() -> dict[str, str]:
        return {}

    app = FastAPI()
    app.include_router(router)

    assert undeclared_routes(app) == []


def test_a_permission_declared_deep_in_a_dependency_counts() -> None:
    def wrapper(_user: object = Depends(require_permission(Permission.ACCOUNT_SELF))) -> None:
        return None

    app = FastAPI()

    @app.get("/wrapped", dependencies=[Depends(wrapper)])
    def wrapped() -> dict[str, str]:
        return {}

    assert undeclared_routes(app) == []


def test_declaring_both_public_and_a_permission_is_flagged_as_ambiguous() -> None:
    app = FastAPI()

    @app.get(
        "/confused",
        dependencies=[Depends(public_route), Depends(require_permission(Permission.ACCOUNT_SELF))],
    )
    def confused() -> dict[str, str]:
        return {}

    assert undeclared_routes(app) == ["GET /confused"]


def test_declared_access_reports_what_a_route_declares() -> None:
    app = FastAPI()

    @app.get("/open", dependencies=[Depends(public_route)])
    def open_route() -> dict[str, str]:
        return {}

    @app.get("/closed", dependencies=[Depends(require_permission(Permission.MANAGE_USERS))])
    def closed_route() -> dict[str, str]:
        return {}

    routes: dict[str, BaseRoute] = {getattr(r, "path", ""): r for r in app.routes}
    open_api, closed_api = routes["/open"], routes["/closed"]
    assert isinstance(open_api, APIRoute) and isinstance(closed_api, APIRoute)
    assert declared_access(open_api) == [PUBLIC]
    assert declared_access(closed_api) == [Permission.MANAGE_USERS]


def test_an_undeclared_route_inside_an_included_router_is_caught() -> None:
    router = APIRouter()

    @router.get("/hidden")
    def hidden() -> dict[str, str]:
        return {"oops": "anyone can call me"}

    app = FastAPI()
    app.include_router(router)

    assert undeclared_routes(app) == ["GET /hidden"]


def test_routers_included_inside_routers_are_followed_too() -> None:
    inner = APIRouter()

    @inner.get("/deep")
    def deep() -> dict[str, str]:
        return {}

    outer = APIRouter()
    outer.include_router(inner)
    app = FastAPI()
    app.include_router(outer)

    assert undeclared_routes(app) == ["GET /deep"]


def test_an_include_with_a_prefix_or_extra_dependencies_is_refused_not_skipped() -> None:
    # The audit cannot see what such an include adds, so it must stop rather than guess.
    router = APIRouter()

    @router.get("/x", dependencies=[Depends(public_route)])
    def route() -> dict[str, str]:
        return {}

    with_prefix = FastAPI()
    with_prefix.include_router(router, prefix="/v1")
    with_dependency = FastAPI()
    with_dependency.include_router(router, dependencies=[Depends(public_route)])

    for app in (with_prefix, with_dependency):
        with pytest.raises(UnsupportedRouteSetup):
            undeclared_routes(app)


def test_an_unrecognised_kind_of_route_is_refused_not_skipped() -> None:
    class Strange(BaseRoute):
        def matches(self, scope):  # type: ignore[no-untyped-def]
            return None, {}

        async def handle(self, scope, receive, send):  # type: ignore[no-untyped-def]
            return None

    app = FastAPI()
    app.router.routes.append(Strange())

    with pytest.raises(UnsupportedRouteSetup):
        undeclared_routes(app)
