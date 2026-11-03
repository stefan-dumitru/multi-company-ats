"""The CI gate: every route must declare who may call it (security.md > Authorization).

A route with no declaration fails the build, so forgetting authorization cannot reach production.
"""

from fastapi import APIRouter, Depends, FastAPI
from fastapi.routing import APIRoute
from starlette.routing import BaseRoute

from app.auth.permissions import (
    PUBLIC,
    Permission,
    declared_access,
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


def test_only_known_non_api_routes_exist() -> None:
    # The check above only inspects APIRoute objects; a plain Starlette route would slip past it.
    others = {
        getattr(route, "path", "") for route in real_app.routes if not isinstance(route, APIRoute)
    }

    assert others <= EXPECTED_NON_API_PATHS


def test_a_route_without_a_declaration_is_caught() -> None:
    app = FastAPI()

    @app.get("/forgotten")
    def forgotten() -> dict[str, str]:
        return {"oops": "anyone can call me"}

    assert undeclared_routes(app) == ["GET /forgotten"]


def test_a_route_declared_in_an_included_router_counts() -> None:
    router = APIRouter()

    @router.get("/inner", dependencies=[Depends(public_route)])
    def inner() -> dict[str, str]:
        return {}

    app = FastAPI()
    app.include_router(router, prefix="/api")

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
