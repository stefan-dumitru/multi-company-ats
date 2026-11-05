"""Data access for users. Every function takes the current user and filters by their company.

This is the pattern for every company-scoped table (CLAUDE.md > Project-specific conventions):
routers never query these tables directly.
"""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.sessions import revoke_all_sessions
from app.models import Company, Role, User
from app.services.audit import record_audit
from app.services.errors import LastAdminError, NotFoundError


def list_company_users(db: Session, current_user: User) -> list[User]:
    # A candidate has no company: `company_id == None` must not match every other candidate.
    if current_user.company_id is None:
        return []
    statement = (
        select(User).where(User.company_id == current_user.company_id).order_by(User.created_at)
    )
    return list(db.scalars(statement))


def get_company_user(db: Session, current_user: User, user_id: uuid.UUID) -> User:
    if current_user.company_id is None:
        raise NotFoundError
    user = db.scalar(
        select(User).where(User.id == user_id, User.company_id == current_user.company_id)
    )
    if user is None:
        raise NotFoundError
    return user


def normalize_email(email: str) -> str:
    """Emails are compared case-insensitively, so they are stored trimmed and lowercase."""
    return email.strip().lower()


def email_is_taken(db: Session, email: str) -> bool:
    """Whether any account (staff or candidate, any company) already uses this email."""
    return (
        db.scalar(select(User.id).where(func.lower(User.email) == normalize_email(email)))
        is not None
    )


def _lock_company_and_check_admins(db: Session, admin: User, target: User) -> None:
    """Serialise changes to a company's admins, then make sure one admin would remain.

    Without the lock, two admins deactivating each other at the same moment would both see "the
    other one is still active" and leave the company with none. Locking the company row makes the
    second request wait, re-read, and be refused.
    """
    db.execute(select(Company.id).where(Company.id == admin.company_id).with_for_update())
    db.refresh(target)  # the state may have changed while we waited for the lock
    active_admins = db.scalar(
        select(func.count())
        .select_from(User)
        .where(
            User.company_id == admin.company_id,
            User.role == Role.COMPANY_ADMIN,
            User.is_active.is_(True),
        )
    )
    if target.role == Role.COMPANY_ADMIN and target.is_active and (active_admins or 0) <= 1:
        raise LastAdminError


def change_role(
    db: Session, current_user: User, user_id: uuid.UUID, new_role: Role, now: datetime
) -> User:
    """Give a company member another staff role. The caller commits."""
    user = get_company_user(db, current_user, user_id)
    if user.role == new_role:
        return user
    if user.role == Role.COMPANY_ADMIN:
        _lock_company_and_check_admins(db, current_user, user)
    old_role = user.role
    user.role = new_role
    record_audit(
        db,
        actor=current_user,
        action="user.role_changed",
        entity_type="user",
        entity_id=user.id,
        old_value={"role": old_role.value},
        new_value={"role": new_role.value},
        now=now,
    )
    db.flush()
    return user


def deactivate_user(db: Session, current_user: User, user_id: uuid.UUID, now: datetime) -> User:
    """Block a user's login and end their sessions, keeping everything they created."""
    user = get_company_user(db, current_user, user_id)
    if not user.is_active:
        return user
    _lock_company_and_check_admins(db, current_user, user)
    user.is_active = False
    user.deactivated_at = now
    revoke_all_sessions(db, user.id, now)
    record_audit(
        db,
        actor=current_user,
        action="user.deactivated",
        entity_type="user",
        entity_id=user.id,
        old_value={"is_active": True},
        new_value={"is_active": False},
        now=now,
    )
    db.flush()
    return user


def reactivate_user(db: Session, current_user: User, user_id: uuid.UUID, now: datetime) -> User:
    """Let a deactivated user log in again. Their old sessions stay revoked."""
    user = get_company_user(db, current_user, user_id)
    if user.is_active:
        return user
    user.is_active = True
    user.deactivated_at = None
    record_audit(
        db,
        actor=current_user,
        action="user.reactivated",
        entity_type="user",
        entity_id=user.id,
        old_value={"is_active": False},
        new_value={"is_active": True},
        now=now,
    )
    db.flush()
    return user
