"""Candidate accounts: registering, and the profile a candidate keeps about themselves."""

from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.passwords import check_password_rules, hash_password
from app.models import CandidateProfile, Role, User
from app.services.companies import is_email_collision
from app.services.email_verification import issue_verification_email
from app.services.errors import EmailAlreadyRegistered
from app.services.users import email_is_taken, normalize_email

__all__ = ["is_email_collision", "register_candidate", "get_profile", "update_profile"]


def register_candidate(
    db: Session, *, full_name: str, email: str, password: str, now: datetime
) -> User:
    """Create a candidate account (no company) with its profile. The caller commits.

    Raises PasswordTooWeak, or EmailAlreadyRegistered (the caller must then roll back).
    """
    email = normalize_email(email)
    check_password_rules(password)
    # The friendly check. Two registrations at the same moment can both pass it; the unique index
    # on lower(email) is what actually guarantees one account per email.
    if email_is_taken(db, email):
        raise EmailAlreadyRegistered

    candidate = User(
        company_id=None,
        role=Role.CANDIDATE,
        email=email,
        full_name=full_name,
        password_hash=hash_password(password),
    )
    db.add(candidate)
    try:
        db.flush()
    except IntegrityError as error:
        if is_email_collision(error):
            raise EmailAlreadyRegistered from error
        raise
    db.add(CandidateProfile(user_id=candidate.id))
    db.flush()
    issue_verification_email(db, candidate, now)  # same transaction: no account, no email
    return candidate


def get_profile(db: Session, candidate: User) -> CandidateProfile:
    """The candidate's own profile. Created empty if the account has none yet."""
    profile = db.get(CandidateProfile, candidate.id)
    if profile is None:
        profile = CandidateProfile(user_id=candidate.id)
        db.add(profile)
        db.flush()
    return profile


def update_profile(
    db: Session, candidate: User, changes: dict[str, str | None]
) -> CandidateProfile:
    """Apply the fields that were sent. Everything is scoped to the caller: there is no id here."""
    profile = get_profile(db, candidate)
    if "full_name" in changes and changes["full_name"] is not None:
        candidate.full_name = changes["full_name"]
    if "phone" in changes:
        profile.phone = changes["phone"]
    if "location" in changes:
        profile.location = changes["location"]
    db.flush()
    return profile
