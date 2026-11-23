"""Signing in with Google. Public: the person is not signed in yet.

`/start` and `/callback` are GETs because the browser itself is sent to and from Google; they change
nothing before the sign-in is complete. They are protected by a signed state plus a cookie only the
starting browser has (see `services/google_login.py`). They only ever redirect to fixed addresses of
ours, never to one taken from the request.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth.cookies import set_session_cookie
from app.auth.permissions import public_route
from app.auth.sessions import create_session
from app.config import get_cookie_secure, get_google_settings
from app.db import get_db
from app.schemas.google_login import GoogleLoginConfigOut
from app.services import google_login
from app.services.google_login import GoogleLoginError

router = APIRouter(prefix="/api/auth/google", tags=["auth"], dependencies=[Depends(public_route)])

NONCE_COOKIE = "ats_google_nonce"
# The cookie is only ever needed by these two routes, so it is only ever sent to them.
NONCE_COOKIE_PATH = "/api/auth/google"
NONCE_COOKIE_SECONDS = int(google_login.MAX_STATE_AGE.total_seconds())


def _refused(reason: str) -> RedirectResponse:
    """Back to the login page with one of our short codes, never Google's text."""
    response = RedirectResponse(f"/login?google_error={reason}", status_code=303)
    _forget_nonce(response)
    return response


def _forget_nonce(response: RedirectResponse) -> None:
    response.delete_cookie(
        NONCE_COOKIE,
        path=NONCE_COOKIE_PATH,
        secure=get_cookie_secure(),
        httponly=True,
        samesite="lax",
    )


@router.get("/config", response_model=GoogleLoginConfigOut)
def get_config() -> GoogleLoginConfigOut:
    """Whether to show the button at all: only when this server has Google set up."""
    return GoogleLoginConfigOut(enabled=get_google_settings() is not None)


@router.get("/start")
def start() -> RedirectResponse:
    try:
        address, nonce = google_login.start_login(datetime.now(UTC))
    except GoogleLoginError as failure:
        return _refused(failure.reason)
    response = RedirectResponse(address, status_code=303)
    response.set_cookie(
        NONCE_COOKIE,
        nonce,
        max_age=NONCE_COOKIE_SECONDS,
        httponly=True,  # JavaScript has no use for it
        secure=get_cookie_secure(),
        samesite="lax",  # sent on the top-level navigation back from Google, and nothing else
        path=NONCE_COOKIE_PATH,
    )
    return response


@router.get("/callback")
def come_back_from_google(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    now = datetime.now(UTC)
    try:
        user = google_login.finish_login(
            db,
            now,
            code=code,
            state=state,
            error=error,
            nonce=request.cookies.get(NONCE_COOKIE),
        )
        user.last_login_at = now
        token, _session = create_session(db, user, now)
        db.commit()  # the account, its link, the audit row and the session: one transaction
    except GoogleLoginError as failure:
        db.rollback()
        return _refused(failure.reason)
    response = RedirectResponse("/", status_code=303)
    set_session_cookie(response, token, user.role)
    _forget_nonce(response)
    return response
