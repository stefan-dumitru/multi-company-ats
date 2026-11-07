"""Choosing a new password after forgetting the old one (security.md > Authentication)."""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.auth import tokens
from app.auth.passwords import check_password_rules, hash_password
from app.auth.rate_limit import clear_failures
from app.auth.sessions import revoke_all_sessions
from app.models import User, UserToken
from app.services.audit import record_audit
from app.services.users import normalize_email
from app.worker.queue import enqueue

RESET_LIFETIME = timedelta(hours=1)
# Stops anyone using "forgot password" to flood somebody's inbox. Counts every link issued.
MAX_LINKS_PER_HOUR = 3
LIMIT_WINDOW = timedelta(hours=1)


def issue_reset_link(db: Session, user: User, now: datetime) -> UserToken:
    """Create a reset link for `user` and queue its email. The caller commits.

    Older unused reset links are voided, so only the newest one works.
    """
    db.execute(
        update(UserToken)
        .where(
            UserToken.user_id == user.id,
            UserToken.type == tokens.PASSWORD_RESET,
            UserToken.used_at.is_(None),
        )
        .values(used_at=now)
    )
    link = UserToken(
        id=uuid.uuid4(),
        user_id=user.id,
        type=tokens.PASSWORD_RESET,
        created_at=now,
        expires_at=now + RESET_LIFETIME,
    )
    db.add(link)
    db.flush()
    enqueue(
        db,
        type="send_email",
        payload={"template": "reset_password", "user_token_id": str(link.id)},
        idempotency_key=f"password_reset:{link.id}",
        now=now,
    )
    return link


def request_password_reset(db: Session, email: str, now: datetime) -> None:
    """Send a reset link if (and only if) an active account has this address.

    Returns nothing, whatever happened: the caller must answer identically in every case, or the
    answer would tell a stranger which addresses have accounts. The caller commits.
    """
    user = db.scalar(select(User).where(func.lower(User.email) == normalize_email(email)))
    if user is None or not user.is_active:
        return
    recent_links = db.scalar(
        select(func.count())
        .select_from(UserToken)
        .where(
            UserToken.user_id == user.id,
            UserToken.type == tokens.PASSWORD_RESET,
            UserToken.created_at > now - LIMIT_WINDOW,
        )
    )
    if (recent_links or 0) >= MAX_LINKS_PER_HOUR:
        return  # silently: saying "too many" would also say "this account exists"
    issue_reset_link(db, user, now)


def reset_password(db: Session, token: str, new_password: str, now: datetime) -> bool:
    """Use a reset link to set a new password. True if it worked; False for any bad link.

    Raises PasswordTooWeak *before* the link is touched, so a weak password does not burn it.
    The caller commits on True and rolls back on False (a rollback also undoes using the link when
    the account turns out to be inactive).
    """
    check_password_rules(new_password)
    token_id = tokens.read_token(tokens.PASSWORD_RESET, token)
    if token_id is None:
        return False
    # One UPDATE decides "unused and unexpired", so two simultaneous uses cannot both succeed.
    used = db.execute(
        update(UserToken)
        .where(
            UserToken.id == token_id,
            UserToken.type == tokens.PASSWORD_RESET,
            UserToken.used_at.is_(None),
            UserToken.expires_at > now,
        )
        .values(used_at=now)
        .returning(UserToken.user_id)
    ).first()
    if used is None:
        return False
    user = db.get(User, used.user_id)
    if user is None or not user.is_active:
        return False

    user.password_hash = hash_password(new_password)
    if user.email_verified_at is None:
        user.email_verified_at = now  # opening the link proved the inbox is theirs
    # Anyone who held a session (or another reset link) before this moment must not keep access.
    db.execute(
        update(UserToken)
        .where(
            UserToken.user_id == user.id,
            UserToken.type == tokens.PASSWORD_RESET,
            UserToken.used_at.is_(None),
        )
        .values(used_at=now)
    )
    revoke_all_sessions(db, user.id, now)
    clear_failures(db, user.email)  # earlier typos no longer lock the account
    record_audit(
        db,
        actor=user,
        action="password_reset",
        entity_type="user",
        entity_id=user.id,
        old_value=None,
        new_value=None,  # never the password or the link
        now=now,
    )
    enqueue(
        db,
        type="send_email",
        payload={"template": "password_changed", "user_token_id": str(token_id)},
        idempotency_key=f"password_changed:{token_id}",
        now=now,
    )
    return True


def load_reset_email_context(db: Session, token_id: uuid.UUID) -> tuple[UserToken, User] | None:
    """The link and its user, for the worker to write an email (a system-side lookup by id)."""
    row = db.execute(
        select(UserToken, User)
        .join(User, User.id == UserToken.user_id)
        .where(UserToken.id == token_id)
    ).first()
    return None if row is None else (row[0], row[1])
