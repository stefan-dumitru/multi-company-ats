"""An interviewer's own interviews. Every route here is reached through the caller's assignment, so
an interview they are not on is "not found". Blind scoring lives in `services/scorecards.py`."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.auth.permissions import Permission, require_permission
from app.db import get_db
from app.models import Scorecard, User
from app.pagination import Page, PageRequest, page_request
from app.responses import resume_download
from app.schemas.scorecards import (
    CandidateInfoOut,
    InterviewFilter,
    MyInterviewDetailOut,
    MyInterviewOut,
    ScorecardOut,
    SubmitScorecardRequest,
)
from app.services import scorecards as scorecards_service

router = APIRouter(prefix="/api/my/interviews", tags=["my interviews"])


def scorecard_out(scorecard: Scorecard, author_name: str) -> ScorecardOut:
    return ScorecardOut(
        id=scorecard.id,
        interviewer_name=author_name,
        overall_rating=scorecard.overall_rating,
        technical_rating=scorecard.technical_rating,
        communication_rating=scorecard.communication_rating,
        problem_solving_rating=scorecard.problem_solving_rating,
        culture_fit_rating=scorecard.culture_fit_rating,
        feedback=scorecard.feedback,
        recommendation=scorecard.recommendation,
        submitted_at=scorecard.submitted_at,
    )


@router.get("", response_model=Page[MyInterviewOut])
def list_my_interviews(
    filter: InterviewFilter = InterviewFilter.ALL,  # noqa: A002 - the query parameter's name
    page: PageRequest = Depends(page_request),
    user: User = Depends(require_permission(Permission.INTERVIEWER_WORK)),
    db: Session = Depends(get_db),
) -> Page[MyInterviewOut]:
    rows, total = scorecards_service.list_my_interviews(db, user, page, filter, datetime.now(UTC))
    items = [
        MyInterviewOut(
            id=row.interview.id,
            round_name=row.interview.round_name,
            scheduled_at=row.interview.scheduled_at,
            duration_minutes=row.interview.duration_minutes,
            location=row.interview.location,
            status=row.interview.status,
            job_title=row.job_title,
            candidate_name=row.candidate_name,
            my_scorecard_submitted=row.my_scorecard_submitted,
        )
        for row in rows
    ]
    return Page(items=items, total=total, page=page.page, page_size=page.page_size)


@router.get("/{interview_id}", response_model=MyInterviewDetailOut)
def get_my_interview(
    interview_id: uuid.UUID,
    user: User = Depends(require_permission(Permission.INTERVIEWER_WORK)),
    db: Session = Depends(get_db),
) -> MyInterviewDetailOut:
    detail = scorecards_service.my_interview_detail(db, user, interview_id)
    interview = detail.interview
    candidate = detail.candidate
    return MyInterviewDetailOut(
        id=interview.id,
        round_name=interview.round_name,
        scheduled_at=interview.scheduled_at,
        duration_minutes=interview.duration_minutes,
        location=interview.location,
        status=interview.status,
        job_title=detail.job_title,
        candidate=None
        if candidate is None
        else CandidateInfoOut(
            name=candidate.name,
            email=candidate.email,
            phone=candidate.phone,
            location=candidate.location,
        ),
        my_scorecard=scorecard_out(*detail.my_scorecard) if detail.my_scorecard else None,
        others_visible=detail.my_scorecard is not None,
        others=[scorecard_out(scorecard, name) for scorecard, name in detail.others],
    )


@router.get("/{interview_id}/resume")
def download_resume(
    interview_id: uuid.UUID,
    user: User = Depends(require_permission(Permission.INTERVIEWER_WORK)),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    file, stored = scorecards_service.open_my_interview_resume(db, user, interview_id)
    return resume_download(file, stored)


@router.post("/{interview_id}/scorecard", response_model=ScorecardOut, status_code=201)
def submit_scorecard(
    interview_id: uuid.UUID,
    payload: SubmitScorecardRequest,
    user: User = Depends(require_permission(Permission.INTERVIEWER_WORK)),
    db: Session = Depends(get_db),
) -> ScorecardOut:
    scorecard, author_name = scorecards_service.submit_scorecard(
        db, user, interview_id, payload.model_dump(), datetime.now(UTC)
    )
    out = scorecard_out(scorecard, author_name)
    db.commit()  # the scorecard, its audit row and, if it was the last, the completion
    return out
