"""Data access for users. Every function takes the current user and filters by their company.

This is the pattern for every company-scoped table (CLAUDE.md > Project-specific conventions):
routers never query these tables directly.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User
from app.services.errors import NotFoundError


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
