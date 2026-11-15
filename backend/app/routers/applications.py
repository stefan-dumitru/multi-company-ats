import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.auth.permissions import Permission, require_permission
from app.db import get_db
from app.models import User
from app.pagination import Page, PageRequest, page_request
from app.responses import resume_download
from app.schemas.applications import ApplyRequest, MyApplicationOut
from app.services import applications as applications_service
from app.services.applications import ApplicationView

router = APIRouter(prefix="/api/applications", tags=["applications"])


def application_out(view: ApplicationView) -> MyApplicationOut:
    application = view.application
    return MyApplicationOut(
        id=application.id,
        job_id=application.job_id,
        job_title=view.job_title,
        company_name=view.company_name,
        stage=application.stage,
        applied_at=application.created_at,
        job_is_open=view.job_is_open,
    )


@router.post("", response_model=MyApplicationOut, status_code=201)
def apply(
    payload: ApplyRequest,
    response: Response,
    user: User = Depends(require_permission(Permission.CANDIDATE_PROFILE)),
    db: Session = Depends(get_db),
) -> MyApplicationOut:
    result = applications_service.apply_to_job(db, user, payload.job_id, datetime.now(UTC))
    out = application_out(applications_service.application_view(db, user, result.application.id))
    db.commit()  # the application, its history and audit rows and the email job: one transaction
    if not result.created:
        response.status_code = 200  # the candidate had already applied: this is that application
    return out


@router.get("", response_model=Page[MyApplicationOut])
def list_my_applications(
    page: PageRequest = Depends(page_request),
    user: User = Depends(require_permission(Permission.CANDIDATE_PROFILE)),
    db: Session = Depends(get_db),
) -> Page[MyApplicationOut]:
    views, total = applications_service.list_my_applications(db, user, page)
    items = [application_out(view) for view in views]
    return Page(items=items, total=total, page=page.page, page_size=page.page_size)


@router.post("/{application_id}/withdraw", response_model=MyApplicationOut)
def withdraw(
    application_id: uuid.UUID,
    user: User = Depends(require_permission(Permission.CANDIDATE_PROFILE)),
    db: Session = Depends(get_db),
) -> MyApplicationOut:
    applications_service.withdraw_application(db, user, application_id, datetime.now(UTC))
    out = application_out(applications_service.application_view(db, user, application_id))
    db.commit()
    return out


@router.post("/{application_id}/reactivate", response_model=MyApplicationOut)
def reactivate(
    application_id: uuid.UUID,
    user: User = Depends(require_permission(Permission.CANDIDATE_PROFILE)),
    db: Session = Depends(get_db),
) -> MyApplicationOut:
    applications_service.reactivate_application(db, user, application_id, datetime.now(UTC))
    out = application_out(applications_service.application_view(db, user, application_id))
    db.commit()
    return out


@router.get("/{application_id}/resume")
def download_applicant_resume(
    application_id: uuid.UUID,
    user: User = Depends(require_permission(Permission.VIEW_APPLICATIONS)),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    file, stored = applications_service.open_application_resume(db, user, application_id)
    return resume_download(file, stored)
