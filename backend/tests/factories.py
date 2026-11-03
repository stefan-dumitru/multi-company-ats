"""Helpers that create rows for tests. They flush (so ids exist) but never commit."""

from sqlalchemy.orm import Session

from app.auth.passwords import hash_password
from app.models import Company, Role, User

DEFAULT_PASSWORD = "correct horse battery"


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
) -> User:
    user = User(
        email=email,
        full_name=full_name,
        role=role,
        company_id=company.id if company else None,
        password_hash=hash_password(password) if password else None,
    )
    db.add(user)
    db.flush()
    return user
