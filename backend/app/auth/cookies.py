from fastapi import Response

from app.auth.sessions import SESSION_COOKIE_NAME, absolute_lifetime
from app.config import get_cookie_secure
from app.models import Role


def set_session_cookie(response: Response, token: str, role: Role) -> None:
    """Attach the login cookie, for every way of getting a session (login, signup, invitation)."""
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=int(absolute_lifetime(role).total_seconds()),
        httponly=True,  # JavaScript cannot read it
        secure=get_cookie_secure(),  # only sent over HTTPS
        samesite="lax",
        path="/",
    )
