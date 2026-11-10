"""Data access and rules for jobs. Every function takes the current user.

Who sees which job lives in one place, `_visible_to`: an admin sees every job of their company, a
recruiter only the jobs assigned to them, everybody else none (default deny). A job outside that
scope is "not found", never "forbidden".

Every change to an existing job first locks its row (`SELECT ... FOR UPDATE`). Two people acting on
the same job at the same moment therefore take turns, and the second one sees what the first did:
that is what makes the version check, "publish needs a recruiter" and "an open job keeps a
recruiter" safe against races.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, and_, delete, exists, false, func, select
from sqlalchemy.orm import Session

from app.models import Department, Job, JobRecruiter, PostingStatus, Role, User
from app.pagination import PageRequest
from app.services.audit import record_audit
from app.services.errors import (
    ArchivedDepartment,
    DraftCannotClose,
    InvalidDepartment,
    InvalidRecruiter,
    JobClosed,
    LastRecruiterError,
    NoRecruiter,
    NotFoundError,
    OnlyDraftsDeletable,
    VersionConflict,
)

EDITABLE_FIELDS = ("title", "location", "description", "department_id")


@dataclass
class JobSummary:
    job: Job
    department_name: str
    needs_reassignment: bool


@dataclass
class JobDetail:
    job: Job
    department: Department
    recruiters: list[User]
    needs_reassignment: bool


def _visible_to(user: User) -> list[ColumnElement[bool]]:
    """The WHERE conditions that restrict a jobs query to what this user may see."""
    # A candidate has no company: `company_id == None` must not match anything.
    if user.company_id is None:
        return [false()]
    in_company = Job.company_id == user.company_id
    if user.role == Role.COMPANY_ADMIN:
        return [in_company]
    if user.role == Role.RECRUITER:
        assigned = exists().where(JobRecruiter.job_id == Job.id, JobRecruiter.user_id == user.id)
        return [in_company, assigned]
    return [false()]


def _has_active_recruiter() -> ColumnElement[bool]:
    return exists().where(
        JobRecruiter.job_id == Job.id,
        JobRecruiter.user_id == User.id,
        User.is_active.is_(True),
    )


def _active_recruiter_count(db: Session, job_id: uuid.UUID, *, excluding: uuid.UUID | None) -> int:
    statement = (
        select(func.count())
        .select_from(JobRecruiter)
        .join(User, User.id == JobRecruiter.user_id)
        .where(JobRecruiter.job_id == job_id, User.is_active.is_(True))
    )
    if excluding is not None:
        statement = statement.where(JobRecruiter.user_id != excluding)
    return db.scalar(statement) or 0


def get_job(db: Session, user: User, job_id: uuid.UUID, *, lock: bool = False) -> Job:
    statement = select(Job).where(Job.id == job_id, *_visible_to(user))
    if lock:
        # populate_existing: if this row was loaded earlier in the session, take the values the
        # other transaction has just committed, not the stale copy.
        statement = statement.with_for_update(of=Job).execution_options(populate_existing=True)
    job = db.scalar(statement)
    if job is None:
        raise NotFoundError
    return job


def list_jobs(
    db: Session,
    user: User,
    page: PageRequest,
    *,
    status: PostingStatus | None,
    department_id: uuid.UUID | None,
) -> tuple[list[JobSummary], int]:
    """One page of the jobs this user may see, newest first, and how many there are in all."""
    wanted = _visible_to(user)
    if status is not None:
        wanted.append(Job.status == status)
    if department_id is not None:
        wanted.append(Job.department_id == department_id)
    total = db.scalar(select(func.count()).select_from(Job).where(*wanted)) or 0
    needs_reassignment = and_(Job.status != PostingStatus.CLOSED, ~_has_active_recruiter())
    rows = db.execute(
        select(Job, Department.name, needs_reassignment)
        .join(Department, Department.id == Job.department_id)
        .where(*wanted)
        # The id breaks ties, so a page never repeats or skips a row between requests.
        .order_by(Job.created_at.desc(), Job.id)
        .limit(page.page_size)
        .offset(page.offset)
    )
    return [JobSummary(job, name, flag) for job, name, flag in rows], total


def job_detail(db: Session, job: Job) -> JobDetail:
    """Everything the detail screen shows. `job` must already have passed `get_job`."""
    department = db.get(Department, job.department_id)
    assert department is not None  # the foreign key guarantees it
    recruiters = list(
        db.scalars(
            select(User)
            .join(JobRecruiter, JobRecruiter.user_id == User.id)
            .where(JobRecruiter.job_id == job.id)
            .order_by(JobRecruiter.added_at, User.id)
        )
    )
    has_active = any(recruiter.is_active for recruiter in recruiters)
    return JobDetail(
        job=job,
        department=department,
        recruiters=recruiters,
        needs_reassignment=job.status != PostingStatus.CLOSED and not has_active,
    )


def _usable_department(
    db: Session, user: User, department_id: uuid.UUID, *, keeping: uuid.UUID | None = None
) -> Department:
    """A department of the user's company that new work may be put in."""
    department = db.scalar(
        select(Department).where(
            Department.id == department_id, Department.company_id == user.company_id
        )
    )
    if department is None:
        raise InvalidDepartment
    # A job may stay in a department that was archived after the job chose it.
    if department.is_archived and department.id != keeping:
        raise ArchivedDepartment
    return department


def create_job(
    db: Session,
    user: User,
    *,
    title: str,
    location: str,
    description: str,
    department_id: uuid.UUID,
    now: datetime,
) -> Job:
    if user.company_id is None or user.role not in (Role.COMPANY_ADMIN, Role.RECRUITER):
        raise NotFoundError
    department = _usable_department(db, user, department_id)
    job = Job(
        company_id=user.company_id,
        department_id=department.id,
        title=title,
        location=location,
        description=description,
        status=PostingStatus.DRAFT,
        created_by=user.id,
    )
    db.add(job)
    db.flush()
    if user.role == Role.RECRUITER:
        # A recruiter who creates a job is its first recruiter. An admin is not a recruiter.
        db.add(JobRecruiter(job_id=job.id, user_id=user.id, added_by=user.id))
    record_audit(
        db,
        actor=user,
        action="job.created",
        entity_type="job",
        entity_id=job.id,
        old_value=None,
        new_value={"status": "draft", "department_id": str(department.id)},
        now=now,
    )
    db.flush()
    return job


def _check_version(job: Job, version: int) -> None:
    if job.version != version:
        raise VersionConflict


def update_job(
    db: Session, user: User, job_id: uuid.UUID, version: int, changes: dict[str, Any], now: datetime
) -> Job:
    job = get_job(db, user, job_id, lock=True)
    _check_version(job, version)
    if job.status == PostingStatus.CLOSED:
        raise JobClosed
    if "department_id" in changes:
        _usable_department(db, user, changes["department_id"], keeping=job.department_id)
    changed = [
        name for name in EDITABLE_FIELDS if name in changes and changes[name] != getattr(job, name)
    ]
    if not changed:
        return job  # nothing differs: no new version, no audit row
    for name in changed:
        setattr(job, name, changes[name])
    job.version += 1
    # Only the names of the fields: the text itself stays out of the audit log.
    record_audit(
        db,
        actor=user,
        action="job.updated",
        entity_type="job",
        entity_id=job.id,
        old_value=None,
        new_value={"fields": changed},
        now=now,
    )
    db.flush()
    return job


def publish_job(db: Session, user: User, job_id: uuid.UUID, version: int, now: datetime) -> Job:
    job = get_job(db, user, job_id, lock=True)
    if job.status == PostingStatus.OPEN:
        return job  # already open (a double click, or someone else got there first)
    if job.status == PostingStatus.CLOSED:
        raise JobClosed
    _check_version(job, version)
    if _active_recruiter_count(db, job.id, excluding=None) == 0:
        raise NoRecruiter
    job.status = PostingStatus.OPEN
    job.opened_at = now
    job.version += 1
    record_audit(
        db,
        actor=user,
        action="job.published",
        entity_type="job",
        entity_id=job.id,
        old_value={"status": "draft"},
        new_value={"status": "open"},
        now=now,
    )
    db.flush()
    return job


def close_job(db: Session, user: User, job_id: uuid.UUID, version: int, now: datetime) -> Job:
    job = get_job(db, user, job_id, lock=True)
    if job.status == PostingStatus.CLOSED:
        return job
    if job.status == PostingStatus.DRAFT:
        raise DraftCannotClose
    _check_version(job, version)
    job.status = PostingStatus.CLOSED
    job.closed_at = now
    job.version += 1
    record_audit(
        db,
        actor=user,
        action="job.closed",
        entity_type="job",
        entity_id=job.id,
        old_value={"status": "open"},
        new_value={"status": "closed"},
        now=now,
    )
    db.flush()
    return job


def delete_draft(db: Session, user: User, job_id: uuid.UUID, now: datetime) -> None:
    job = get_job(db, user, job_id, lock=True)
    if job.status != PostingStatus.DRAFT:
        raise OnlyDraftsDeletable
    record_audit(
        db,
        actor=user,
        action="job.deleted",
        entity_type="job",
        entity_id=job.id,
        old_value={"status": "draft"},
        new_value=None,
        now=now,
    )
    db.execute(delete(JobRecruiter).where(JobRecruiter.job_id == job.id))
    db.delete(job)
    db.flush()


def assign_recruiter(
    db: Session, user: User, job_id: uuid.UUID, recruiter_id: uuid.UUID, now: datetime
) -> Job:
    job = get_job(db, user, job_id, lock=True)
    recruiter = db.scalar(
        select(User).where(
            User.id == recruiter_id,
            User.company_id == user.company_id,
            User.role == Role.RECRUITER,
            User.is_active.is_(True),
        )
    )
    if recruiter is None:
        raise InvalidRecruiter
    if db.get(JobRecruiter, (job.id, recruiter.id)) is not None:
        return job  # already assigned: nothing to do
    db.add(JobRecruiter(job_id=job.id, user_id=recruiter.id, added_by=user.id))
    record_audit(
        db,
        actor=user,
        action="job.recruiter_added",
        entity_type="job",
        entity_id=job.id,
        old_value=None,
        new_value={"user_id": str(recruiter.id)},
        now=now,
    )
    db.flush()
    return job


def unassign_recruiter(
    db: Session, user: User, job_id: uuid.UUID, recruiter_id: uuid.UUID, now: datetime
) -> None:
    job = get_job(db, user, job_id, lock=True)
    link = db.get(JobRecruiter, (job.id, recruiter_id))
    if link is None:
        return  # not assigned: nothing to remove
    removed = db.get(User, recruiter_id)
    removing_an_active_recruiter = removed is not None and removed.is_active
    if (
        job.status == PostingStatus.OPEN
        and removing_an_active_recruiter
        and _active_recruiter_count(db, job.id, excluding=recruiter_id) == 0
    ):
        raise LastRecruiterError
    db.delete(link)
    record_audit(
        db,
        actor=user,
        action="job.recruiter_removed",
        entity_type="job",
        entity_id=job.id,
        old_value={"user_id": str(recruiter_id)},
        new_value=None,
        now=now,
    )
    db.flush()
