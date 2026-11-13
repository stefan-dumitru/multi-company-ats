from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.auth.cookies import set_session_cookie
from app.auth.passwords import PasswordTooWeak
from app.auth.permissions import public_route
from app.auth.sessions import create_session
from app.db import get_db
from app.schemas.auth import SessionInfo, UserOut
from app.schemas.candidates import RegisterCandidateRequest
from app.services.candidates import register_candidate
from app.services.errors import EmailAlreadyRegistered

router = APIRouter(prefix="/api/candidates", tags=["candidates"])

# The same words whether the email is taken or not, as for company signup (functional.md).
REGISTRATION_FAILED = "We couldn't create this account. If you already have one, log in instead."


@router.post("", status_code=201, response_model=SessionInfo, dependencies=[Depends(public_route)])
def register(
    payload: RegisterCandidateRequest, response: Response, db: Session = Depends(get_db)
) -> SessionInfo:
    now = datetime.now(UTC)
    try:
        candidate = register_candidate(
            db,
            full_name=payload.full_name,
            email=payload.email,
            password=payload.password,
            now=now,
        )
    except PasswordTooWeak as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except EmailAlreadyRegistered as error:
        db.rollback()
        raise HTTPException(status_code=400, detail=REGISTRATION_FAILED) from error

    token, session = create_session(db, candidate, now)
    db.commit()  # account, profile, verification email job and session: one transaction
    set_session_cookie(response, token, candidate.role)
    return SessionInfo(user=UserOut.model_validate(candidate), csrf_token=session.csrf_token)
