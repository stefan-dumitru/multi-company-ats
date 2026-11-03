from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.auth.cookies import set_session_cookie
from app.auth.passwords import PasswordTooWeak
from app.auth.permissions import public_route
from app.auth.sessions import create_session
from app.db import get_db
from app.schemas.auth import SessionInfo, UserOut
from app.schemas.companies import RegisterCompanyRequest
from app.services.companies import register_company
from app.services.errors import EmailAlreadyRegistered

router = APIRouter(prefix="/api/companies", tags=["companies"])

# The same words whether the email is taken or not (functional.md). It cannot hide the difference
# completely until emails exist (Phase 3), but it does not state it either.
SIGNUP_FAILED = "We couldn't create this account. If you already have one, log in instead."


@router.post("", status_code=201, response_model=SessionInfo, dependencies=[Depends(public_route)])
def sign_up(
    payload: RegisterCompanyRequest, response: Response, db: Session = Depends(get_db)
) -> SessionInfo:
    now = datetime.now(UTC)
    try:
        admin = register_company(
            db,
            company_name=payload.company_name,
            full_name=payload.full_name,
            email=payload.email,
            password=payload.password,
        )
    except PasswordTooWeak as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except EmailAlreadyRegistered as error:
        db.rollback()  # drops the half-built company too
        raise HTTPException(status_code=400, detail=SIGNUP_FAILED) from error

    token, session = create_session(db, admin, now)
    db.commit()  # company, admin and session: one transaction
    set_session_cookie(response, token, admin.role)
    return SessionInfo(user=UserOut.model_validate(admin), csrf_token=session.csrf_token)
