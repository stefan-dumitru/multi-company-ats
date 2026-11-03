"""Inviting staff to a company. Every function takes the current user and stays in their company."""

import secrets
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.passwords import check_password_rules, hash_password
from app.auth.sessions import hash_token
from app.models import Invitation, Role, User
from app.services.companies import is_email_collision
from app.services.errors import EmailAlreadyRegistered, InvalidInvitation
from app.services.users import email_is_taken, normalize_email

INVITATION_LIFETIME = timedelta(days=7)


def invitation_status(invitation: Invitation, now: datetime) -> str:
    if invitation.accepted_at is not None:
        return "accepted"
    if invitation.revoked_at is not None:
        return "revoked"
    if now >= invitation.expires_at:
        return "expired"
    return "pending"


def create_invitation(
    db: Session, current_user: User, *, email: str, role: Role, now: datetime
) -> tuple[Invitation, str]:
    """Returns the invitation and the link token, which is shown once and never stored.

    Inviting an email again revokes the older link, so only the newest one works.
    """
    if current_user.company_id is None:
        raise PermissionError("Only company staff can invite.")  # a bug in the caller, not input
    email = normalize_email(email)
    if email_is_taken(db, email):
        raise EmailAlreadyRegistered

    # Revoke every live invitation for this address, expired ones included: they still occupy the
    # "one live invitation per company and email" slot. Flush before inserting the new row.
    older = db.scalars(
        select(Invitation).where(
            Invitation.company_id == current_user.company_id,
            func.lower(Invitation.email) == email,
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
        )
    )
    for invitation in older:
        invitation.revoked_at = now
    db.flush()

    token = secrets.token_urlsafe(32)
    invitation = Invitation(
        company_id=current_user.company_id,
        email=email,
        role=role,
        token_hash=hash_token(token),
        invited_by=current_user.id,
        created_at=now,
        expires_at=now + INVITATION_LIFETIME,
    )
    db.add(invitation)
    db.flush()
    return invitation, token


def list_invitations(db: Session, current_user: User) -> list[Invitation]:
    if current_user.company_id is None:
        return []
    statement = (
        select(Invitation)
        .where(Invitation.company_id == current_user.company_id)
        .order_by(Invitation.created_at.desc())
    )
    return list(db.scalars(statement))


def accept_invitation(
    db: Session, *, token: str, full_name: str, password: str, now: datetime
) -> User:
    """Turn a valid link into a staff account. The caller commits.

    Raises InvalidInvitation for every kind of bad link, PasswordTooWeak for a weak password (the
    link stays usable), and InvalidInvitation again if the email got an account in the meantime.
    """
    invitation = db.scalar(select(Invitation).where(Invitation.token_hash == hash_token(token)))
    if invitation is None or invitation_status(invitation, now) != "pending":
        raise InvalidInvitation
    check_password_rules(password)
    if email_is_taken(db, invitation.email):
        raise InvalidInvitation

    user = User(
        company_id=invitation.company_id,
        role=invitation.role,
        email=invitation.email,
        full_name=full_name,
        password_hash=hash_password(password),
    )
    db.add(user)
    invitation.accepted_at = now
    try:
        db.flush()
    except IntegrityError as error:
        if is_email_collision(error):
            raise InvalidInvitation from error
        raise
    return user
