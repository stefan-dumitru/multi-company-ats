"""Serving the built React app from the API's own origin (no CORS needed)."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import get_static_dir
from app.frontend import mount_frontend


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


def test_unknown_paths_are_404_not_the_app(client: TestClient) -> None:
    # Returning index.html for every unknown URL would hide mistyped API paths behind a 200.
    response = client.get("/does-not-exist")

    assert response.status_code == 404


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
