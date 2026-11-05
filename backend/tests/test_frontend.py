"""Serving the built React app from the API's own origin (no CORS needed)."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import get_static_dir
from app.frontend import is_client_side_route, mount_frontend


@pytest.fixture
def built_frontend(tmp_path: Path) -> Path:
    (tmp_path / "index.html").write_text("<html><body>the app</body></html>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log('hi')")
    return tmp_path


@pytest.fixture
def client(built_frontend: Path) -> TestClient:
    api = FastAPI()

    @api.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    # Mounted last, as in app.main: the API routes above must win over the catch-all frontend.
    mount_frontend(api, built_frontend)
    return TestClient(api)


def test_root_serves_the_app(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "the app" in response.text


def test_assets_are_served(client: TestClient) -> None:
    response = client.get("/assets/app.js")

    assert response.status_code == 200
    assert "console.log" in response.text


def test_api_routes_are_not_shadowed_by_the_frontend(client: TestClient) -> None:
    response = client.get("/health")

    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize("path", ["/login", "/users", "/accept-invitation", "/users/123/edit"])
def test_client_side_routes_serve_the_app_so_refresh_and_shared_links_work(
    client: TestClient, path: str
) -> None:
    # The browser asks the server for /login on a refresh or a pasted link; only the React router
    # inside index.html knows what that page is.
    response = client.get(path)

    assert response.status_code == 200
    assert "the app" in response.text


@pytest.mark.parametrize("path", ["/api/nope", "/api/users/xyz/nope", "/api"])
def test_unknown_api_paths_stay_404_and_never_return_the_app(client: TestClient, path: str) -> None:
    # A mistyped API call must fail visibly, not get a 200 HTML page it cannot parse.
    response = client.get(path)

    assert response.status_code == 404
    assert "the app" not in response.text


@pytest.mark.parametrize("path", ["/assets/missing.js", "/favicon-missing.png", "/a/b/c.css"])
def test_missing_files_stay_404_instead_of_html_pretending_to_be_a_script(
    client: TestClient, path: str
) -> None:
    response = client.get(path)

    assert response.status_code == 404
    assert "the app" not in response.text


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("login", True),
        ("users/123", True),
        ("api", False),
        ("api/users", False),
        ("api\\users", False),  # the same path as Windows hands it to Starlette
        ("assets/app.js", False),
        ("assets\\app.js", False),
        ("v1.2/dashboard", True),  # a dot in a folder name is not a file extension
    ],
)
def test_which_paths_count_as_client_side_routes(path: str, expected: bool) -> None:
    assert is_client_side_route(path) is expected


def test_the_fallback_never_applies_to_changing_requests(client: TestClient) -> None:
    assert client.post("/login").status_code in (404, 405)


def test_path_traversal_cannot_read_files_outside_the_directory(
    client: TestClient, built_frontend: Path
) -> None:
    (built_frontend.parent / "secret.txt").write_text("top secret")

    response = client.get("/../secret.txt")

    assert "top secret" not in response.text


def test_missing_frontend_directory_fails_loudly(tmp_path: Path) -> None:
    # A typo in STATIC_DIR should stop startup, not silently serve no UI.
    with pytest.raises(RuntimeError, match="STATIC_DIR"):
        mount_frontend(FastAPI(), tmp_path / "nope")


def test_static_dir_is_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    # In local development Vite serves the UI, so the backend runs without a static directory.
    monkeypatch.delenv("STATIC_DIR", raising=False)

    assert get_static_dir() is None


def test_static_dir_is_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STATIC_DIR", "/app/static")

    assert get_static_dir() == Path("/app/static")
