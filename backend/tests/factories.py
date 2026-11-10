"""Helpers that create rows for tests. They flush (so ids exist) but never commit."""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.passwords import hash_password
from app.models import (
    Company,
    Department,
    Job,
    JobRecruiter,
    PostingStatus,
    Role,
    User,
)

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


def make_department(db: Session, company: Company, name: str = "Engineering") -> Department:
    department = Department(company_id=company.id, name=name)
    db.add(department)
    db.flush()
    return department


def make_job(
    db: Session,
    *,
    company: Company,
    department: Department,
    created_by: User,
    recruiters: list[User] | None = None,
    title: str = "Backend Engineer",
    location: str = "Remote",
    description: str = "Build and run our services.",
    status: PostingStatus = PostingStatus.DRAFT,
    opened_at: datetime | None = None,
) -> Job:
    """A job with the given recruiters assigned. Open and closed jobs get their timestamps."""
    now = datetime.now(UTC)
    job = Job(
        company_id=company.id,
        department_id=department.id,
        title=title,
        location=location,
        description=description,
        status=status,
        created_by=created_by.id,
        opened_at=None if status == PostingStatus.DRAFT else (opened_at or now),
        closed_at=now if status == PostingStatus.CLOSED else None,
    )
    db.add(job)
    db.flush()
    for recruiter in recruiters or []:
        db.add(JobRecruiter(job_id=job.id, user_id=recruiter.id, added_by=created_by.id))
    db.flush()
    return job
