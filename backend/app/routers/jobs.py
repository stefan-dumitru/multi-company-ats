import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.auth.permissions import Permission, require_permission
from app.db import get_db
from app.models import PostingStatus, User
from app.pagination import Page, PageRequest, page_request
from app.schemas.jobs import (
    AssignRecruiterRequest,
    CreateJobRequest,
    DepartmentRef,
    JobOut,
    JobSummaryOut,
    RecruiterOut,
    UpdateJobRequest,
    VersionRequest,
)
from app.services import jobs as jobs_service
from app.services.jobs import JobDetail, JobSummary

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def summary_out(summary: JobSummary) -> JobSummaryOut:
    job = summary.job
    return JobSummaryOut(
        id=job.id,
        title=job.title,
        location=job.location,
        status=job.status,
        department_id=job.department_id,
        department_name=summary.department_name,
        created_at=job.created_at,
        opened_at=job.opened_at,
        closed_at=job.closed_at,
        version=job.version,
        needs_reassignment=summary.needs_reassignment,
    )


def job_out(detail: JobDetail) -> JobOut:
    job = detail.job
    return JobOut(
        id=job.id,
        title=job.title,
        location=job.location,
        description=job.description,
        status=job.status,
        department=DepartmentRef(
            id=detail.department.id,
            name=detail.department.name,
            is_archived=detail.department.is_archived,
        ),
        created_at=job.created_at,
        opened_at=job.opened_at,
        closed_at=job.closed_at,
        version=job.version,
        needs_reassignment=detail.needs_reassignment,
        recruiters=[
            RecruiterOut(
                id=person.id,
                full_name=person.full_name,
                email=person.email,
                is_active=person.is_active,
            )
            for person in detail.recruiters
        ],
    )


@router.get("", response_model=Page[JobSummaryOut])
def list_jobs(
    status: PostingStatus | None = None,
    department_id: uuid.UUID | None = None,
    page: PageRequest = Depends(page_request),
    user: User = Depends(require_permission(Permission.MANAGE_JOBS)),
    db: Session = Depends(get_db),
) -> Page[JobSummaryOut]:
    rows, total = jobs_service.list_jobs(db, user, page, status=status, department_id=department_id)
    items = [summary_out(row) for row in rows]
    return Page(items=items, total=total, page=page.page, page_size=page.page_size)


@router.post("", response_model=JobOut, status_code=201)
def create_job(
    payload: CreateJobRequest,
    user: User = Depends(require_permission(Permission.MANAGE_JOBS)),
    db: Session = Depends(get_db),
) -> JobOut:
    job = jobs_service.create_job(
        db,
        user,
        title=payload.title,
        location=payload.location,
        description=payload.description,
        department_id=payload.department_id,
        now=datetime.now(UTC),
    )
    out = job_out(jobs_service.job_detail(db, job))
    db.commit()  # the job, its first recruiter and the audit row: one transaction
    return out


@router.get("/{job_id}", response_model=JobOut)
def get_job(
    job_id: uuid.UUID,
    user: User = Depends(require_permission(Permission.MANAGE_JOBS)),
    db: Session = Depends(get_db),
) -> JobOut:
    return job_out(jobs_service.job_detail(db, jobs_service.get_job(db, user, job_id)))


@router.patch("/{job_id}", response_model=JobOut)
def update_job(
    job_id: uuid.UUID,
    payload: UpdateJobRequest,
    user: User = Depends(require_permission(Permission.MANAGE_JOBS)),
    db: Session = Depends(get_db),
) -> JobOut:
    job = jobs_service.update_job(
        db, user, job_id, payload.version, payload.changes(), datetime.now(UTC)
    )
    out = job_out(jobs_service.job_detail(db, job))
    db.commit()
    return out


@router.post("/{job_id}/publish", response_model=JobOut)
def publish_job(
    job_id: uuid.UUID,
    payload: VersionRequest,
    user: User = Depends(require_permission(Permission.MANAGE_JOBS)),
    db: Session = Depends(get_db),
) -> JobOut:
    job = jobs_service.publish_job(db, user, job_id, payload.version, datetime.now(UTC))
    out = job_out(jobs_service.job_detail(db, job))
    db.commit()
    return out


@router.post("/{job_id}/close", response_model=JobOut)
def close_job(
    job_id: uuid.UUID,
    payload: VersionRequest,
    user: User = Depends(require_permission(Permission.MANAGE_JOBS)),
    db: Session = Depends(get_db),
) -> JobOut:
    job = jobs_service.close_job(db, user, job_id, payload.version, datetime.now(UTC))
    out = job_out(jobs_service.job_detail(db, job))
    db.commit()
    return out


@router.delete("/{job_id}", status_code=204)
def delete_draft(
    job_id: uuid.UUID,
    user: User = Depends(require_permission(Permission.MANAGE_JOBS)),
    db: Session = Depends(get_db),
) -> Response:
    jobs_service.delete_draft(db, user, job_id, datetime.now(UTC))
    db.commit()
    return Response(status_code=204)


@router.post("/{job_id}/recruiters", response_model=JobOut)
def assign_recruiter(
    job_id: uuid.UUID,
    payload: AssignRecruiterRequest,
    user: User = Depends(require_permission(Permission.MANAGE_JOBS)),
    db: Session = Depends(get_db),
) -> JobOut:
    job = jobs_service.assign_recruiter(db, user, job_id, payload.user_id, datetime.now(UTC))
    out = job_out(jobs_service.job_detail(db, job))
    db.commit()
    return out


@router.delete("/{job_id}/recruiters/{user_id}", status_code=204)
def unassign_recruiter(
    job_id: uuid.UUID,
    user_id: uuid.UUID,
    user: User = Depends(require_permission(Permission.MANAGE_JOBS)),
    db: Session = Depends(get_db),
) -> Response:
    jobs_service.unassign_recruiter(db, user, job_id, user_id, datetime.now(UTC))
    db.commit()
    return Response(status_code=204)
