"""Inviting staff to a company. Every function takes the current user and stays in their company."""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import tokens
from app.auth.passwords import check_password_rules, hash_password
from app.auth.sessions import hash_token
from app.models import Company, Invitation, Role, User
from app.services.companies import is_email_collision
from app.services.errors import EmailAlreadyRegistered, InvalidInvitation
from app.services.users import email_is_taken, normalize_email
from app.worker.queue import enqueue

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
    """Returns the invitation and its signed link token (shown to the admin once).

    Inviting an email again revokes the older link, so only the newest one works. The invitation
    email is queued here, in the same transaction: a rolled-back invitation sends nothing. The
    queue holds only the invitation's id; the worker rebuilds the link from it.
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

    # The id comes first because the link is signed over it.
    invitation_id = uuid.uuid4()
    token = tokens.make_token(tokens.INVITATION, invitation_id)
    invitation = Invitation(
        id=invitation_id,
        company_id=current_user.company_id,
        email=email,
        role=role,
        token_hash=hash_token(token),  # kept for the schema; the signature is what is checked
        invited_by=current_user.id,
        created_at=now,
        expires_at=now + INVITATION_LIFETIME,
    )
    db.add(invitation)
    db.flush()
    enqueue(
        db,
        type="send_email",
        payload={"template": "invitation", "invitation_id": str(invitation.id)},
        idempotency_key=f"invitation_email:{invitation.id}",
        now=now,
    )
    return invitation, token


def load_invitation_email_context(
    db: Session, invitation_id: uuid.UUID
) -> tuple[Invitation, Company, User] | None:
    """The invitation with its company and inviter, for the worker to write the email.

    A system-side lookup by id: there is no logged-in user here, and the id came from a job that
    the web app queued inside the inviting admin's own company.
    """
    row = db.execute(
        select(Invitation, Company, User)
        .join(Company, Company.id == Invitation.company_id)
        .join(User, User.id == Invitation.invited_by)
        .where(Invitation.id == invitation_id)
    ).first()
    return None if row is None else (row[0], row[1], row[2])


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
    invitation_id = tokens.read_token(tokens.INVITATION, token)
    invitation = None if invitation_id is None else db.get(Invitation, invitation_id)
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
