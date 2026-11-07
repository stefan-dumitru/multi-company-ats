"""The reset email: one link to choose a new password, and what to do if it was not you."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.auth import tokens
from app.config import get_app_base_url
from app.emails.base import Email
from app.emails.invitation import one_line
from app.services.password_reset import load_reset_email_context


def render_reset_password(db: Session, payload: dict[str, Any]) -> Email | None:
    context = load_reset_email_context(db, uuid.UUID(payload["user_token_id"]))
    if context is None:
        return None
    token_row, user = context
    if token_row.type != tokens.PASSWORD_RESET:
        return None
    if token_row.used_at is not None or token_row.expires_at <= datetime.now(UTC):
        return None  # used, replaced or expired since this was queued: do not mail a dead link
    if not user.is_active:
        return None

    link = (
        f"{get_app_base_url()}/reset-password?token="
        f"{tokens.make_token(tokens.PASSWORD_RESET, token_row.id)}"
    )
    body = (
        f"Hello {one_line(user.full_name)},\n\n"
        f"Someone asked to reset the password of your account. To choose a new one, open this "
        f"link:\n{link}\n\n"
        f"The link works once and expires in 1 hour. If you did not ask for this, ignore this "
        f"email: your password stays exactly as it is.\n"
    )
    return Email(to=user.email, subject="Reset your password", body=body)
