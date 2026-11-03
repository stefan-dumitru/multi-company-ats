"""FastAPI dependencies that turn the session cookie into the logged-in user."""

import hmac
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth.sessions import SESSION_COOKIE_NAME, find_valid_session
from app.db import get_db
from app.models import User, UserSession

# Requests that only read. Everything else changes data and needs the CSRF token.
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def get_current_session(request: Request, db: Session = Depends(get_db)) -> UserSession:
    token = request.cookies.get(SESSION_COOKIE_NAME, "")
    session = find_valid_session(db, token, datetime.now(UTC))
    if session is None:
        raise HTTPException(status_code=401, detail="Not logged in.")
    # find_valid_session moved the "last seen" time; keep it, or the idle timeout never slides.
    db.commit()
    return session


def get_current_user(
    session: UserSession = Depends(get_current_session), db: Session = Depends(get_db)
) -> User:
    user = db.get(User, session.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Not logged in.")
    return user


def verify_csrf(request: Request, session: UserSession) -> None:
    """Reject a state-changing request that does not echo the session's CSRF token.

    A malicious site can make the browser send our cookie, but it cannot read the token, so it
    cannot add this header.
    """
    if request.method in SAFE_METHODS:
        return
    sent = request.headers.get("X-CSRF-Token", "")
    if not hmac.compare_digest(sent, session.csrf_token):
        raise HTTPException(status_code=403, detail="Missing or invalid CSRF token.")
