"""Helpers that create rows for tests. They flush (so ids exist) but never commit."""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.passwords import hash_password
from app.models import Company, Role, User

DEFAULT_PASSWORD = "correct horse battery"


def verify_email_of(db: Session, email: str) -> None:
    """Mark an account made through the API as verified, as if its owner had clicked the link.

    For tests that are about something else and just need a user who is allowed in.
    """
    user = db.scalars(select(User).where(func.lower(User.email) == email.lower())).one()
    user.email_verified_at = datetime.now(UTC)
    db.commit()


def make_company(db: Session, name: str = "Acme") -> Company:
    company = Company(name=name)
    db.add(company)
    db.flush()
    return company


def make_user(
    db: Session,
    *,
    email: str,
    role: Role,
    company: Company | None,
    full_name: str = "Test User",
    password: str | None = None,
    verified: bool = True,
) -> User:
    user = User(
        email_verified_at=datetime.now(UTC) if verified else None,
        email=email,
        full_name=full_name,
        role=role,
        company_id=company.id if company else None,
        password_hash=hash_password(password) if password else None,
    )
    db.add(user)
    db.flush()
    return user
