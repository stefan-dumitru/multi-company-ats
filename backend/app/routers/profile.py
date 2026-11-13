from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.auth.permissions import Permission, require_permission
from app.db import get_db
from app.models import CandidateProfile, File, User
from app.schemas.candidates import ProfileOut, ResumeOut, UpdateProfileRequest
from app.services import candidates as candidates_service
from app.services import resumes as resumes_service
from app.services.errors import ResumeTooLarge
from app.services.resume_files import MAX_RESUME_BYTES, content_disposition

router = APIRouter(prefix="/api/profile", tags=["profile"])


def resume_out(file: File | None) -> ResumeOut | None:
    if file is None:
        return None
    return ResumeOut(
        filename=file.original_filename, size_bytes=file.size_bytes, uploaded_at=file.uploaded_at
    )


def profile_out(db: Session, user: User, profile: CandidateProfile) -> ProfileOut:
    return ProfileOut(
        full_name=user.full_name,
        email=user.email,
        phone=profile.phone,
        location=profile.location,
        resume=resume_out(resumes_service.current_resume(db, user)),
    )


@router.get("", response_model=ProfileOut)
def read_profile(
    user: User = Depends(require_permission(Permission.CANDIDATE_PROFILE)),
    db: Session = Depends(get_db),
) -> ProfileOut:
    profile = candidates_service.get_profile(db, user)
    out = profile_out(db, user, profile)
    db.commit()  # keeps the empty profile row if this was the first time it was needed
    return out


@router.patch("", response_model=ProfileOut)
def update_profile(
    payload: UpdateProfileRequest,
    user: User = Depends(require_permission(Permission.CANDIDATE_PROFILE)),
    db: Session = Depends(get_db),
) -> ProfileOut:
    profile = candidates_service.update_profile(db, user, payload.changes())
    out = profile_out(db, user, profile)
    db.commit()
    return out


async def read_limited_body(request: Request, limit: int) -> bytes:
    """The request body, refused as too large as soon as it is known to be (or has become) so."""
    declared = request.headers.get("content-length", "")
    if declared.isdecimal() and int(declared) > limit:
        raise ResumeTooLarge  # said in advance: not one byte of the body is read
    received = bytearray()
    async for chunk in request.stream():
        received.extend(chunk)
        if len(received) > limit:
            raise ResumeTooLarge  # no length was declared: stop counting at the limit
    return bytes(received)


async def resume_body(request: Request) -> bytes:
    return await read_limited_body(request, MAX_RESUME_BYTES)


@router.put("/resume", response_model=ResumeOut)
def upload_resume(
    filename: str = Query(min_length=1, max_length=255),
    # Order matters: FastAPI resolves these one after another, so a request that may not upload is
    # refused by the permission check before `resume_body` reads a single byte of the file.
    user: User = Depends(require_permission(Permission.CANDIDATE_PROFILE)),
    body: bytes = Depends(resume_body),
    db: Session = Depends(get_db),
) -> ResumeOut:
    file = resumes_service.store_resume(db, user, filename, body, datetime.now(UTC))
    out = resume_out(file)
    try:
        db.commit()  # the file record, the profile pointer and the cleanup job: one transaction
    except Exception:
        resumes_service.discard_stored_object(file.storage_key)
        raise
    assert out is not None
    return out


@router.get("/resume")
def download_resume(
    user: User = Depends(require_permission(Permission.CANDIDATE_PROFILE)),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    file, stored = resumes_service.open_current_resume(db, user)
    return StreamingResponse(
        stored.chunks,
        media_type=file.content_type,
        headers={
            "Content-Disposition": content_disposition(file.original_filename),
            "Content-Length": str(stored.size),
            # The file is only ever downloaded, never shown by the app, and the browser must not
            # guess a different type from the bytes.
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )
