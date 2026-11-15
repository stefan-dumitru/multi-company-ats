"""Helpers that create rows for tests. They flush (so ids exist) but never commit."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.passwords import hash_password
from app.models import (
    Application,
    ApplicationStage,
    ApplicationStageHistory,
    CandidateProfile,
    Company,
    Department,
    File,
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


def make_resume_file(db: Session, owner: User, name: str = "cv.pdf") -> File:
    """A resume record (no object in storage: tests that download one put the bytes themselves)."""
    file = File(
        owner_user_id=owner.id,
        storage_key=f"resumes/{uuid.uuid4()}",
        original_filename=name,
        content_type="application/pdf",
        size_bytes=100,
        uploaded_at=datetime.now(UTC),
    )
    db.add(file)
    db.flush()
    return file


def make_candidate(
    db: Session,
    *,
    email: str,
    full_name: str = "Test Candidate",
    resume: bool = True,
    verified: bool = True,
) -> User:
    """A candidate with a profile, and (unless told otherwise) a resume on file."""
    candidate = make_user(
        db, email=email, role=Role.CANDIDATE, company=None, full_name=full_name, verified=verified
    )
    profile = CandidateProfile(user_id=candidate.id)
    db.add(profile)
    db.flush()
    if resume:
        profile.current_resume_file_id = make_resume_file(db, candidate).id
        db.flush()
    return candidate


def make_application(
    db: Session,
    *,
    job: Job,
    candidate: User,
    stage: ApplicationStage = ApplicationStage.APPLIED,
    resume_file: File | None = None,
) -> Application:
    """An application as it would exist after applying (and, for `withdrawn`, after withdrawing)."""
    now = datetime.now(UTC)
    file = resume_file or make_resume_file(db, candidate)
    application = Application(
        job_id=job.id,
        company_id=job.company_id,
        candidate_id=candidate.id,
        resume_file_id=file.id,
        stage=stage,
        stage_before_withdrawal=ApplicationStage.APPLIED
        if stage == ApplicationStage.WITHDRAWN
        else None,
        created_at=now,
        updated_at=now,
    )
    db.add(application)
    db.flush()
    db.add(
        ApplicationStageHistory(
            application_id=application.id,
            from_stage=None,
            to_stage=ApplicationStage.APPLIED,
            changed_by=candidate.id,
            changed_at=now,
        )
    )
    db.flush()
    return application
