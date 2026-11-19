"""A recruiter's Google Calendar connection. Recruiters only: they are the ones who schedule.

Every route acts on the caller's own connection and takes no id, so there is nothing of another
person's to reach. The way back from Google (`/callback`) is a GET because Google redirects the
browser to it; it is protected by the signed, recent, per-person `state` instead of a CSRF header.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth.permissions import Permission, require_permission
from app.db import get_db
from app.models import User
from app.schemas.calendar import CalendarStatusOut, ConnectOut
from app.services import calendar as calendar_service
from app.services.calendar import CalendarCallbackError

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


@router.get("", response_model=CalendarStatusOut)
def get_status(
    user: User = Depends(require_permission(Permission.MANAGE_INTERVIEWS)),
    db: Session = Depends(get_db),
) -> CalendarStatusOut:
    status = calendar_service.connection_status(db, user)
    return CalendarStatusOut(
        configured=status.configured, connected=status.connected, connected_at=status.connected_at
    )


@router.post("/connect", response_model=ConnectOut)
def start(
    user: User = Depends(require_permission(Permission.MANAGE_INTERVIEWS)),
) -> ConnectOut:
    return ConnectOut(url=calendar_service.start_connection(user, datetime.now(UTC)))


@router.get("/callback")
def come_back_from_google(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    user: User = Depends(require_permission(Permission.MANAGE_INTERVIEWS)),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        calendar_service.finish_connection(
            db, user, datetime.now(UTC), code=code, state=state, error=error
        )
        db.commit()  # the connection and its audit row: one transaction
        target = "/calendar?connected=1"
    except CalendarCallbackError as failure:
        db.rollback()
        target = f"/calendar?error={failure.reason}"  # a short code of ours, never Google's text
    return RedirectResponse(target, status_code=303)


@router.delete("/connection", status_code=204)
def disconnect(
    user: User = Depends(require_permission(Permission.MANAGE_INTERVIEWS)),
    db: Session = Depends(get_db),
) -> Response:
    calendar_service.disconnect(db, user, datetime.now(UTC))
    db.commit()
    return Response(status_code=204)
