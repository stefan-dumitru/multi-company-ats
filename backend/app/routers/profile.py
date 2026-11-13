from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.permissions import Permission, require_permission
from app.db import get_db
from app.models import CandidateProfile, User
from app.schemas.candidates import ProfileOut, UpdateProfileRequest
from app.services import candidates as candidates_service

router = APIRouter(prefix="/api/profile", tags=["profile"])


def profile_out(user: User, profile: CandidateProfile) -> ProfileOut:
    return ProfileOut(
        full_name=user.full_name, email=user.email, phone=profile.phone, location=profile.location
    )


@router.get("", response_model=ProfileOut)
def read_profile(
    user: User = Depends(require_permission(Permission.CANDIDATE_PROFILE)),
    db: Session = Depends(get_db),
) -> ProfileOut:
    profile = candidates_service.get_profile(db, user)
    out = profile_out(user, profile)
    db.commit()  # keeps the empty profile row if this was the first time it was needed
    return out


@router.patch("", response_model=ProfileOut)
def update_profile(
    payload: UpdateProfileRequest,
    user: User = Depends(require_permission(Permission.CANDIDATE_PROFILE)),
    db: Session = Depends(get_db),
) -> ProfileOut:
    profile = candidates_service.update_profile(db, user, payload.changes())
    out = profile_out(user, profile)
    db.commit()
    return out
