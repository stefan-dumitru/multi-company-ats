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
from app.schemas.applications import (
    ApplicationDetailOut,
    ApplyRequest,
    CreateNoteRequest,
    HistoryEntryOut,
    MyApplicationOut,
    NoteOut,
    RejectionOut,
    RejectRequest,
)
from app.schemas.jobs import VersionRequest
from app.services import applications as applications_service
from app.services import notes as notes_service
from app.services import pipeline as pipeline_service
from app.services.applications import ApplicationView
from app.services.pipeline import NEXT_STAGE, ApplicationDetail

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
    job_id: uuid.UUID | None = None,
    page: PageRequest = Depends(page_request),
    user: User = Depends(require_permission(Permission.CANDIDATE_PROFILE)),
    db: Session = Depends(get_db),
) -> Page[MyApplicationOut]:
    views, total = applications_service.list_my_applications(db, user, page, job_id=job_id)
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


def detail_out(detail: ApplicationDetail) -> ApplicationDetailOut:
    application = detail.application
    rejection = None
    if application.rejection_reason is not None and application.rejected_from_stage is not None:
        rejection = RejectionOut(
            from_stage=application.rejected_from_stage,
            reason=application.rejection_reason,
            comment=application.rejection_comment,
        )
    return ApplicationDetailOut(
        id=application.id,
        job_id=application.job_id,
        job_title=detail.job_title,
        candidate_name=detail.candidate_name,
        candidate_email=detail.candidate_email,
        candidate_phone=detail.candidate_phone,
        candidate_location=detail.candidate_location,
        stage=application.stage,
        next_stage=NEXT_STAGE.get(application.stage),
        version=application.version,
        applied_at=application.created_at,
        rejection=rejection,
        history=[
            HistoryEntryOut(
                from_stage=entry.from_stage,
                to_stage=entry.to_stage,
                changed_by_name=entry.changed_by_name,
                changed_at=entry.changed_at,
            )
            for entry in detail.history
        ],
    )


@router.get("/{application_id}", response_model=ApplicationDetailOut)
def get_application(
    application_id: uuid.UUID,
    user: User = Depends(require_permission(Permission.VIEW_APPLICATIONS)),
    db: Session = Depends(get_db),
) -> ApplicationDetailOut:
    return detail_out(pipeline_service.get_application_detail(db, user, application_id))


@router.post("/{application_id}/advance", response_model=ApplicationDetailOut)
def advance_application(
    application_id: uuid.UUID,
    payload: VersionRequest,
    user: User = Depends(require_permission(Permission.MANAGE_APPLICATIONS)),
    db: Session = Depends(get_db),
) -> ApplicationDetailOut:
    pipeline_service.advance_application(
        db, user, application_id, payload.version, datetime.now(UTC)
    )
    out = detail_out(pipeline_service.get_application_detail(db, user, application_id))
    db.commit()  # the move, its history and audit rows and the candidate's email: one transaction
    return out


@router.post("/{application_id}/reject", response_model=ApplicationDetailOut)
def reject_application(
    application_id: uuid.UUID,
    payload: RejectRequest,
    user: User = Depends(require_permission(Permission.MANAGE_APPLICATIONS)),
    db: Session = Depends(get_db),
) -> ApplicationDetailOut:
    pipeline_service.reject_application(
        db,
        user,
        application_id,
        payload.version,
        payload.reason,
        payload.comment,
        datetime.now(UTC),
    )
    out = detail_out(pipeline_service.get_application_detail(db, user, application_id))
    db.commit()
    return out


@router.get("/{application_id}/notes", response_model=Page[NoteOut])
def list_notes(
    application_id: uuid.UUID,
    page: PageRequest = Depends(page_request),
    user: User = Depends(require_permission(Permission.VIEW_APPLICATIONS)),
    db: Session = Depends(get_db),
) -> Page[NoteOut]:
    rows, total = notes_service.list_notes(db, user, application_id, page)
    items = [
        NoteOut(id=note.id, author_name=name, body=note.body, created_at=note.created_at)
        for note, name in rows
    ]
    return Page(items=items, total=total, page=page.page, page_size=page.page_size)


@router.post("/{application_id}/notes", response_model=NoteOut, status_code=201)
def add_note(
    application_id: uuid.UUID,
    payload: CreateNoteRequest,
    user: User = Depends(require_permission(Permission.MANAGE_APPLICATIONS)),
    db: Session = Depends(get_db),
) -> NoteOut:
    note, author_name = notes_service.add_note(
        db, user, application_id, payload.body, datetime.now(UTC)
    )
    out = NoteOut(id=note.id, author_name=author_name, body=note.body, created_at=note.created_at)
    db.commit()  # the note and its audit row: one transaction
    return out
