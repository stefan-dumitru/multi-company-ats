"""A test client logged in as one user, for tests that go through the real HTTP routes."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy.orm import Session

from app.auth.sessions import SESSION_COOKIE_NAME, create_session
from app.models import User


class Browser:
    """Logs `user` in on the shared test client. Make the next Browser to switch user."""

    def __init__(self, client: TestClient, db: Session, user: User) -> None:
        token, session = create_session(db, user, datetime.now(UTC))
        db.commit()
        client.cookies.clear()
        client.cookies.set(SESSION_COOKIE_NAME, token)
        self.client = client
        self.csrf = session.csrf_token

    def get(self, path: str) -> Response:
        return self.client.get(path)

    def send(self, method: str, path: str, **kwargs: object) -> Response:
        return self.client.request(
            method,
            path,
            headers={"X-CSRF-Token": self.csrf},
            **kwargs,  # type: ignore[arg-type]
        )
