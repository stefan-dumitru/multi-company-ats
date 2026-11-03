from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.auth.cookies import set_session_cookie
from app.auth.passwords import PasswordTooWeak
from app.auth.permissions import Permission, public_route, require_permission
from app.auth.sessions import create_session
from app.db import get_db
from app.models import Invitation, User
from app.schemas.auth import SessionInfo, UserOut
from app.schemas.invitations import (
    AcceptInvitationRequest,
    CreateInvitationRequest,
    InvitationCreated,
    InvitationOut,
)
from app.services import invitations as invitations_service
from app.services.errors import EmailAlreadyRegistered, InvalidInvitation

router = APIRouter(prefix="/api/invitations", tags=["invitations"])

# One answer for unknown, used, revoked and expired links: it must not help anyone guess tokens.
INVALID_LINK = "This invitation link is invalid or has expired."


def to_out(invitation: Invitation, now: datetime) -> InvitationOut:
    return InvitationOut(
        id=invitation.id,
        email=invitation.email,
        role=invitation.role,
        status=invitations_service.invitation_status(invitation, now),  # type: ignore[arg-type]
        created_at=invitation.created_at,
        expires_at=invitation.expires_at,
    )


@router.post("", status_code=201, response_model=InvitationCreated)
def create_invitation(
    payload: CreateInvitationRequest,
    admin: User = Depends(require_permission(Permission.MANAGE_USERS)),
    db: Session = Depends(get_db),
) -> InvitationCreated:
    now = datetime.now(UTC)
    try:
        invitation, token = invitations_service.create_invitation(
            db, admin, email=payload.email, role=payload.role, now=now
        )
    except EmailAlreadyRegistered as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="That email already has an account.") from error
    db.commit()
    return InvitationCreated(
        invitation=to_out(invitation, now),
        token=token,
        accept_path=f"/accept-invitation?token={token}",
    )


@router.get("", response_model=list[InvitationOut])
def list_invitations(
    admin: User = Depends(require_permission(Permission.MANAGE_USERS)),
    db: Session = Depends(get_db),
) -> list[InvitationOut]:
    now = datetime.now(UTC)
    return [
        to_out(invitation, now) for invitation in invitations_service.list_invitations(db, admin)
    ]


@router.post(
    "/accept",
    status_code=201,
    response_model=SessionInfo,
    dependencies=[Depends(public_route)],
)
def accept_invitation(
    payload: AcceptInvitationRequest, response: Response, db: Session = Depends(get_db)
) -> SessionInfo:
    now = datetime.now(UTC)
    try:
        user = invitations_service.accept_invitation(
            db,
            token=payload.token,
            full_name=payload.full_name,
            password=payload.password,
            now=now,
        )
    except PasswordTooWeak as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except InvalidInvitation as error:
        db.rollback()
        raise HTTPException(status_code=400, detail=INVALID_LINK) from error

    token, session = create_session(db, user, now)
    db.commit()  # the new user, the used-up invitation and the session: one transaction
    set_session_cookie(response, token, user.role)
    return SessionInfo(user=UserOut.model_validate(user), csrf_token=session.csrf_token)
