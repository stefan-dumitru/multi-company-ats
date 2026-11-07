"""The verification email: one link that proves the address is the user's."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.auth import tokens
from app.config import get_app_base_url
from app.emails.base import Email
from app.emails.invitation import one_line
from app.services.email_verification import load_verification_email_context


def render_verify_email(db: Session, payload: dict[str, Any]) -> Email | None:
    context = load_verification_email_context(db, uuid.UUID(payload["user_token_id"]))
    if context is None:
        return None
    token_row, user = context
    now = datetime.now(UTC)
    if token_row.used_at is not None or token_row.expires_at <= now:
        return None  # replaced, used or expired since this was queued: do not mail a dead link
    if user.email_verified_at is not None:
        return None  # already verified some other way

    link = (
        f"{get_app_base_url()}/verify-email?token="
        f"{tokens.make_token(tokens.EMAIL_VERIFICATION, token_row.id)}"
    )
    body = (
        f"Hello {one_line(user.full_name)},\n\n"
        f"Please confirm that this is your email address by opening this link:\n{link}\n\n"
        f"The link works once and expires in 24 hours. If you did not create an account, "
        f"you can ignore this email.\n"
    )
    return Email(to=user.email, subject="Confirm your email address", body=body)
