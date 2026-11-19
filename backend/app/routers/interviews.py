import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.permissions import Permission, require_permission
from app.db import get_db
from app.models import User
from app.schemas.interviews import InterviewOut, ParticipantOut, ScheduleInterviewRequest
from app.schemas.jobs import VersionRequest
from app.services import interviews as interviews_service
from app.services.interviews import InterviewView

router = APIRouter(prefix="/api", tags=["interviews"])


def interview_out(view: InterviewView) -> InterviewOut:
    interview = view.interview
    return InterviewOut(
        id=interview.id,
        application_id=interview.application_id,
        round_name=interview.round_name,
        scheduled_at=interview.scheduled_at,
        duration_minutes=interview.duration_minutes,
        location=interview.location,
        status=interview.status,
        version=interview.version,
        calendar_sync_status=interview.calendar_sync_status,
        needs_reassignment=view.needs_reassignment,
        participants=[
            ParticipantOut(user_id=user_id, full_name=name, is_active=active)
            for user_id, name, active in view.participants
        ],
        created_at=interview.created_at,
    )


@router.get("/applications/{application_id}/interviews", response_model=list[InterviewOut])
def list_interviews(
    application_id: uuid.UUID,
    user: User = Depends(require_permission(Permission.VIEW_APPLICATIONS)),
    db: Session = Depends(get_db),
) -> list[InterviewOut]:
    return [
        interview_out(view) for view in interviews_service.list_interviews(db, user, application_id)
    ]


@router.post(
    "/applications/{application_id}/interviews", response_model=InterviewOut, status_code=201
)
def schedule_interview(
    application_id: uuid.UUID,
    payload: ScheduleInterviewRequest,
    user: User = Depends(require_permission(Permission.MANAGE_INTERVIEWS)),
    db: Session = Depends(get_db),
) -> InterviewOut:
    interview = interviews_service.schedule_interview(
        db,
        user,
        application_id,
        round_name=payload.round_name,
        scheduled_at=payload.scheduled_at,
        duration_minutes=payload.duration_minutes,
        location=payload.location,
        interviewer_ids=payload.interviewer_ids,
        now=datetime.now(UTC),
    )
    out = interview_out(interviews_service.interview_view(db, interview))
    db.commit()  # the interview, its interviewers, the audit row and the emails: one transaction
    return out


@router.post("/interviews/{interview_id}/cancel", response_model=InterviewOut)
def cancel_interview(
    interview_id: uuid.UUID,
    payload: VersionRequest,
    user: User = Depends(require_permission(Permission.MANAGE_INTERVIEWS)),
    db: Session = Depends(get_db),
) -> InterviewOut:
    interview = interviews_service.cancel_interview(
        db, user, interview_id, payload.version, datetime.now(UTC)
    )
    out = interview_out(interviews_service.interview_view(db, interview))
    db.commit()
    return out
