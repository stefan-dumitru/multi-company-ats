from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.passwords import check_password_rules, hash_password
from app.models import Company, Role, User
from app.services.email_verification import issue_verification_email
from app.services.errors import EmailAlreadyRegistered
from app.services.users import email_is_taken, normalize_email

# The name of the unique index on lower(users.email), see the first migration.
EMAIL_INDEX_NAME = "uq_users_email_lower"


def is_email_collision(error: IntegrityError) -> bool:
    """Whether this database error is "that email is taken", as opposed to some other problem.

    Only the former may be reported as a friendly failure; anything else is a bug that must show.
    """
    diagnostics = getattr(error.orig, "diag", None)
    return getattr(diagnostics, "constraint_name", None) == EMAIL_INDEX_NAME


def register_company(
    db: Session,
    *,
    company_name: str,
    full_name: str,
    email: str,
    password: str,
    now: datetime,
) -> User:
    """Create a company and its first admin. The caller commits, so it is all or nothing.

    Raises PasswordTooWeak, or EmailAlreadyRegistered (the caller must then roll back).
    """
    email = normalize_email(email)
    check_password_rules(password)
    # The friendly check. Two signups at the same moment can both pass it; the unique index below
    # is what actually guarantees one account per email.
    if email_is_taken(db, email):
        raise EmailAlreadyRegistered

    company = Company(name=company_name)
    db.add(company)
    db.flush()
    admin = User(
        company_id=company.id,
        role=Role.COMPANY_ADMIN,
        email=email,
        full_name=full_name,
        password_hash=hash_password(password),
    )
    db.add(admin)
    try:
        db.flush()
    except IntegrityError as error:
        if is_email_collision(error):
            raise EmailAlreadyRegistered from error
        raise
    issue_verification_email(db, admin, now)  # same transaction: no account, no email
    return admin
