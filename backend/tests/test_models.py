"""Rules the database itself enforces (data-model.md), whatever the application code does."""

from datetime import UTC, datetime

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Company, Invitation, Role, User


def make_company(db: Session, name: str = "Acme") -> Company:
    company = Company(name=name)
    db.add(company)
    db.flush()
    return company


def make_user(
    db: Session, *, email: str, role: Role, company: Company | None, full_name: str = "Test User"
) -> User:
    user = User(
        email=email,
        full_name=full_name,
        role=role,
        company_id=company.id if company else None,
    )
    db.add(user)
    db.flush()
    return user


def test_the_models_match_the_migrations(scratch_engine: Engine) -> None:
    # If someone edits a model and forgets the migration (or the reverse), production would differ
    # from what the code expects. Alembic can diff the two; any difference fails the build.
    with scratch_engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)

    assert differences == []


def test_the_same_email_in_a_different_case_is_the_same_account(db: Session) -> None:
    company = make_company(db)
    make_user(db, email="Ada@Example.com", role=Role.RECRUITER, company=company)

    with pytest.raises(IntegrityError):
        make_user(db, email="ada@example.com", role=Role.INTERVIEWER, company=company)


def test_one_email_is_one_account_across_companies_and_candidates(db: Session) -> None:
    make_user(db, email="sam@example.com", role=Role.CANDIDATE, company=None)
    company = make_company(db)

    with pytest.raises(IntegrityError):
        make_user(db, email="sam@example.com", role=Role.RECRUITER, company=company)


@pytest.mark.parametrize("role", [Role.COMPANY_ADMIN, Role.RECRUITER, Role.INTERVIEWER])
def test_staff_must_belong_to_a_company(db: Session, role: Role) -> None:
    with pytest.raises(IntegrityError):
        make_user(db, email="staff@example.com", role=role, company=None)


def test_a_candidate_must_not_belong_to_a_company(db: Session) -> None:
    company = make_company(db)

    with pytest.raises(IntegrityError):
        make_user(db, email="cand@example.com", role=Role.CANDIDATE, company=company)


def test_a_new_user_is_active_and_unverified_by_default(db: Session) -> None:
    company = make_company(db)

    user = make_user(db, email="new@example.com", role=Role.COMPANY_ADMIN, company=company)
    db.refresh(user)

    assert user.is_active is True
    assert user.email_verified_at is None
    assert user.created_at.tzinfo is not None  # stored with a time zone (UTC), never naive


def _invitation(company: Company, inviter: User, email: str) -> Invitation:
    return Invitation(
        company_id=company.id,
        email=email,
        role=Role.RECRUITER,
        token_hash=f"hash-of-{email}-{datetime.now(UTC).timestamp()}",
        invited_by=inviter.id,
        expires_at=datetime.now(UTC),
    )


def test_only_one_pending_invitation_per_company_and_email(db: Session) -> None:
    company = make_company(db)
    admin = make_user(db, email="admin@example.com", role=Role.COMPANY_ADMIN, company=company)
    db.add(_invitation(company, admin, "new@example.com"))
    db.flush()

    with pytest.raises(IntegrityError):
        db.add(_invitation(company, admin, "NEW@example.com"))
        db.flush()


def test_a_revoked_invitation_can_be_replaced(db: Session) -> None:
    # Re-sending an invitation revokes the old link and creates a new one.
    company = make_company(db)
    admin = make_user(db, email="admin@example.com", role=Role.COMPANY_ADMIN, company=company)
    old = _invitation(company, admin, "new@example.com")
    db.add(old)
    db.flush()
    old.revoked_at = datetime.now(UTC)
    db.flush()

    db.add(_invitation(company, admin, "new@example.com"))
    db.flush()


def test_an_invitation_cannot_grant_the_candidate_role(db: Session) -> None:
    # Candidates register themselves; staff are the only people one can be invited as.
    company = make_company(db)
    admin = make_user(db, email="admin@example.com", role=Role.COMPANY_ADMIN, company=company)
    invitation = _invitation(company, admin, "cand@example.com")
    invitation.role = Role.CANDIDATE

    with pytest.raises(IntegrityError):
        db.add(invitation)
        db.flush()
