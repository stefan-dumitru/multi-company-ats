"""The notice sent after a password reset, so the owner learns at once if it was not them."""

import uuid
from datetime import UTC
from typing import Any

from sqlalchemy.orm import Session

from app.auth import tokens
from app.config import get_app_base_url
from app.emails.base import Email
from app.emails.invitation import one_line
from app.services.password_reset import load_reset_email_context


def render_password_changed(db: Session, payload: dict[str, Any]) -> Email | None:
    context = load_reset_email_context(db, uuid.UUID(payload["user_token_id"]))
    if context is None:
        return None
    token_row, user = context
    if token_row.type != tokens.PASSWORD_RESET or token_row.used_at is None or not user.is_active:
        return None

    changed_at = token_row.used_at.astimezone(UTC).strftime("%d %B %Y at %H:%M")
    body = (
        f"Hello {one_line(user.full_name)},\n\n"
        f"Your password was changed on {changed_at} (UTC), and you were logged "
        f"out everywhere.\n\n"
        f"If this was you, there is nothing to do. If it was not, someone had access to your "
        f"email. Reset your password again right away at {get_app_base_url()}/forgot-password "
        f"and tell your company admin.\n"
    )
    return Email(to=user.email, subject="Your password was changed", body=body)
