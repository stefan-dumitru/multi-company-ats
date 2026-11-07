"""The invitation email: who invited you, to what, and the link to accept."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.auth import tokens
from app.config import get_app_base_url
from app.emails.base import Email
from app.services.invitations import invitation_status, load_invitation_email_context


def one_line(text: str) -> str:
    """Names are typed by users: flatten any line breaks so they cannot reshape the email."""
    return " ".join(text.split())


def render_invitation(db: Session, payload: dict[str, Any]) -> Email | None:
    context = load_invitation_email_context(db, uuid.UUID(payload["invitation_id"]))
    if context is None:
        return None
    invitation, company, inviter = context
    if invitation_status(invitation, datetime.now(UTC)) != "pending":
        return None  # revoked, accepted or expired since this was queued: do not email a dead link

    token = tokens.make_token(tokens.INVITATION, invitation.id)
    link = f"{get_app_base_url()}/accept-invitation?token={token}"
    company_name = one_line(company.name)
    role = invitation.role.value.replace("_", " ")
    expires = invitation.expires_at.astimezone(UTC).strftime("%d %B %Y")
    body = (
        f"Hello,\n\n"
        f"{one_line(inviter.full_name)} invited you to join {company_name} on ATS as a {role}.\n\n"
        f"Accept the invitation and choose your password here:\n{link}\n\n"
        f"The link works once and expires on {expires} (UTC). If you were not expecting this "
        f"invitation, you can ignore this email.\n"
    )
    return Email(to=invitation.email, subject=f"You are invited to join {company_name}", body=body)
