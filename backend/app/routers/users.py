import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.permissions import Permission, require_permission
from app.db import get_db
from app.models import User
from app.schemas.users import ChangeRoleRequest, ManagedUserOut
from app.services import users as users_service
from app.services.errors import LastAdminError

router = APIRouter(prefix="/api/users", tags=["users"])

LAST_ADMIN = "A company must keep at least one active admin."


@router.get("", response_model=list[ManagedUserOut])
def list_users(
    admin: User = Depends(require_permission(Permission.MANAGE_USERS)),
    db: Session = Depends(get_db),
) -> list[User]:
    return users_service.list_company_users(db, admin)


@router.patch("/{user_id}/role", response_model=ManagedUserOut)
def change_role(
    user_id: uuid.UUID,
    payload: ChangeRoleRequest,
    admin: User = Depends(require_permission(Permission.MANAGE_USERS)),
    db: Session = Depends(get_db),
) -> User:
    try:
        user = users_service.change_role(db, admin, user_id, payload.role, datetime.now(UTC))
    except LastAdminError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail=LAST_ADMIN) from error
    db.commit()  # the change and its audit row: one transaction
    return user


@router.post("/{user_id}/deactivate", response_model=ManagedUserOut)
def deactivate_user(
    user_id: uuid.UUID,
    admin: User = Depends(require_permission(Permission.MANAGE_USERS)),
    db: Session = Depends(get_db),
) -> User:
    try:
        user = users_service.deactivate_user(db, admin, user_id, datetime.now(UTC))
    except LastAdminError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail=LAST_ADMIN) from error
    db.commit()  # deactivation, revoked sessions and the audit row: one transaction
    return user


@router.post("/{user_id}/reactivate", response_model=ManagedUserOut)
def reactivate_user(
    user_id: uuid.UUID,
    admin: User = Depends(require_permission(Permission.MANAGE_USERS)),
    db: Session = Depends(get_db),
) -> User:
    user = users_service.reactivate_user(db, admin, user_id, datetime.now(UTC))
    db.commit()
    return user
