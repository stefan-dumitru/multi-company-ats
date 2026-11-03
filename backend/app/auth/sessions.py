"""Server-side login sessions (security.md > Authentication).

The browser holds a random token in a cookie; the database holds only its SHA-256 hash. Every
function takes the current time as a parameter, so the timeouts can be tested without sleeping.
"""

import hashlib
import secrets
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models import Role, User, UserSession

SESSION_COOKIE_NAME = "ats_session"

# Idle timeout: how long without activity before the user must log in again.
STAFF_IDLE_TIMEOUT = timedelta(minutes=30)
CANDIDATE_IDLE_TIMEOUT = timedelta(days=7)
# Absolute lifetime: the session ends then, however active the user is.
STAFF_ABSOLUTE_LIFETIME = timedelta(hours=12)
CANDIDATE_ABSOLUTE_LIFETIME = timedelta(days=30)


def idle_timeout(role: Role) -> timedelta:
    return CANDIDATE_IDLE_TIMEOUT if role == Role.CANDIDATE else STAFF_IDLE_TIMEOUT


def absolute_lifetime(role: Role) -> timedelta:
    return CANDIDATE_ABSOLUTE_LIFETIME if role == Role.CANDIDATE else STAFF_ABSOLUTE_LIFETIME


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user: User, now: datetime) -> tuple[str, UserSession]:
    """Returns the cookie value (shown once, never stored) and the stored session."""
    token = secrets.token_urlsafe(32)
    session = UserSession(
        id=hash_token(token),
        user_id=user.id,
        csrf_token=secrets.token_urlsafe(32),
        created_at=now,
        last_seen_at=now,
        expires_at=now + absolute_lifetime(user.role),
    )
    db.add(session)
    db.flush()
    return token, session


def find_valid_session(db: Session, token: str, now: datetime) -> UserSession | None:
    """The session for this cookie value if it may still be used, and mark it as just seen."""
    if not token:
        return None
    session = db.get(UserSession, hash_token(token))
    if session is None or session.revoked_at is not None:
        return None
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        return None
    if now >= session.expires_at:
        return None
    if now - session.last_seen_at > idle_timeout(user.role):
        return None
    session.last_seen_at = now
    db.flush()
    return session


def revoke_session(session: UserSession, now: datetime) -> None:
    session.revoked_at = now


def revoke_all_sessions(db: Session, user_id: UUID, now: datetime) -> None:
    """Log a user out everywhere (deactivation, password change)."""
    db.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
