from datetime import UTC, datetime
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.current_user import get_current_session
from app.auth.passwords import hash_password, verify_password
from app.auth.permissions import Permission, public_route, require_permission
from app.auth.rate_limit import clear_failures, is_locked_out, record_failure
from app.auth.sessions import (
    SESSION_COOKIE_NAME,
    absolute_lifetime,
    create_session,
    revoke_session,
)
from app.config import get_cookie_secure
from app.db import get_db
from app.models import User, UserSession
from app.schemas.auth import LoginRequest, SessionInfo, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])

# One message for every kind of failed login, so the answer never reveals which emails exist.
INVALID_LOGIN = "Invalid email or password."
LOCKOUT_RETRY_SECONDS = 15 * 60


@lru_cache
def _dummy_hash() -> str:
    return hash_password("a password nobody has chosen")


@router.post("/login", response_model=SessionInfo, dependencies=[Depends(public_route)])
def login(
    payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)
) -> SessionInfo:
    now = datetime.now(UTC)
    email = payload.email.strip().lower()
    ip_address = request.client.host if request.client else "unknown"

    if is_locked_out(db, email, ip_address, now):
        raise HTTPException(
            status_code=429,
            detail="Too many failed attempts. Try again later.",
            headers={"Retry-After": str(LOCKOUT_RETRY_SECONDS)},
        )

    user = db.scalar(select(User).where(func.lower(User.email) == email))
    # Always check some hash, even for an unknown email, so a fast answer does not give it away.
    stored_hash = user.password_hash if user and user.password_hash else _dummy_hash()
    password_ok = verify_password(stored_hash, payload.password)

    if user is None or not password_ok or not user.is_active:
        # Unknown emails are counted too, otherwise the lockout would reveal which exist.
        record_failure(db, email, ip_address, now)
        db.commit()
        raise HTTPException(status_code=401, detail=INVALID_LOGIN)

    clear_failures(db, email)
    user.last_login_at = now
    token, session = create_session(db, user, now)
    db.commit()

    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=int(absolute_lifetime(user.role).total_seconds()),
        httponly=True,  # JavaScript cannot read it
        secure=get_cookie_secure(),  # only sent over HTTPS
        samesite="lax",
        path="/",
    )
    return SessionInfo(user=UserOut.model_validate(user), csrf_token=session.csrf_token)


@router.get("/me", response_model=SessionInfo)
def me(
    user: User = Depends(require_permission(Permission.ACCOUNT_SELF)),
    session: UserSession = Depends(get_current_session),
) -> SessionInfo:
    return SessionInfo(user=UserOut.model_validate(user), csrf_token=session.csrf_token)


@router.post(
    "/logout",
    status_code=204,
    dependencies=[Depends(require_permission(Permission.ACCOUNT_SELF))],
)
def logout(
    response: Response,
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> None:
    revoke_session(session, datetime.now(UTC))
    db.commit()
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
