"""Proving that a user owns their email address (security.md > Authentication)."""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.auth import tokens
from app.models import User, UserToken
from app.services.errors import ResendLimitReached
from app.worker.queue import enqueue

VERIFICATION_LIFETIME = timedelta(hours=24)
# Stops anyone using "send it again" to flood somebody's inbox. Counts the first email too.
MAX_LINKS_PER_HOUR = 3
LIMIT_WINDOW = timedelta(hours=1)


def issue_verification_email(db: Session, user: User, now: datetime) -> UserToken:
    """Create a verification link for `user` and queue its email. The caller commits.

    Used when an account is created (no limit: it is the first link) and by the resend below.
    Older unused links are voided, so only the newest one works.
    """
    db.execute(
        update(UserToken)
        .where(
            UserToken.user_id == user.id,
            UserToken.type == tokens.EMAIL_VERIFICATION,
            UserToken.used_at.is_(None),
        )
        .values(used_at=now)
    )
    token = UserToken(
        id=uuid.uuid4(),
        user_id=user.id,
        type=tokens.EMAIL_VERIFICATION,
        created_at=now,
        expires_at=now + VERIFICATION_LIFETIME,
    )
    db.add(token)
    db.flush()
    enqueue(
        db,
        type="send_email",
        payload={"template": "verify_email", "user_token_id": str(token.id)},
        idempotency_key=f"verify_email:{token.id}",
        now=now,
    )
    return token


def resend_verification_email(db: Session, user: User, now: datetime) -> None:
    """Send the link again to an unverified user. Does nothing for a verified one.

    Raises ResendLimitReached after MAX_LINKS_PER_HOUR links within an hour.
    """
    if user.email_verified_at is not None:
        return
    recent_links = db.scalar(
        select(func.count())
        .select_from(UserToken)
        .where(
            UserToken.user_id == user.id,
            UserToken.type == tokens.EMAIL_VERIFICATION,
            UserToken.created_at > now - LIMIT_WINDOW,
        )
    )
    if (recent_links or 0) >= MAX_LINKS_PER_HOUR:
        raise ResendLimitReached
    issue_verification_email(db, user, now)


def confirm_email(db: Session, token: str, now: datetime) -> bool:
    """Use a verification link. True if it worked; False for any bad link, without saying why.

    The signature only proves we issued the link. "Not used yet" and "not expired" are decided by
    one UPDATE in the database, so two clicks at the same moment cannot both succeed. The caller
    commits.
    """
    token_id = tokens.read_token(tokens.EMAIL_VERIFICATION, token)
    if token_id is None:
        return False
    used = db.execute(
        update(UserToken)
        .where(
            UserToken.id == token_id,
            UserToken.type == tokens.EMAIL_VERIFICATION,
            UserToken.used_at.is_(None),
            UserToken.expires_at > now,
        )
        .values(used_at=now)
        .returning(UserToken.user_id)
    ).first()
    if used is None:
        return False
    # Only the first proof counts: a second link used later must not rewrite the time.
    db.execute(
        update(User)
        .where(User.id == used.user_id, User.email_verified_at.is_(None))
        .values(email_verified_at=now)
    )
    return True


def load_verification_email_context(
    db: Session, token_id: uuid.UUID
) -> tuple[UserToken, User] | None:
    """The token and its user, for the worker to write the email (a system-side lookup by id)."""
    row = db.execute(
        select(UserToken, User)
        .join(User, User.id == UserToken.user_id)
        .where(UserToken.id == token_id)
    ).first()
    return None if row is None else (row[0], row[1])
