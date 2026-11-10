import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.permissions import Permission, require_permission
from app.db import get_db
from app.models import Department, User
from app.pagination import Page, PageRequest, page_request
from app.schemas.departments import DepartmentNameRequest, DepartmentOut
from app.services import departments as departments_service
from app.services.errors import DuplicateDepartmentName

router = APIRouter(prefix="/api/departments", tags=["departments"])

DUPLICATE_NAME = "A department with this name already exists."


@router.get("", response_model=Page[DepartmentOut])
def list_departments(
    include_archived: bool = False,
    page: PageRequest = Depends(page_request),
    user: User = Depends(require_permission(Permission.VIEW_DEPARTMENTS)),
    db: Session = Depends(get_db),
) -> Page[DepartmentOut]:
    rows, total = departments_service.list_departments(
        db, user, page, include_archived=include_archived
    )
    items = [DepartmentOut.model_validate(row) for row in rows]
    return Page(items=items, total=total, page=page.page, page_size=page.page_size)


@router.post("", response_model=DepartmentOut, status_code=201)
def create_department(
    payload: DepartmentNameRequest,
    admin: User = Depends(require_permission(Permission.MANAGE_DEPARTMENTS)),
    db: Session = Depends(get_db),
) -> Department:
    try:
        department = departments_service.create_department(
            db, admin, payload.name, datetime.now(UTC)
        )
    except DuplicateDepartmentName as error:
        db.rollback()
        raise HTTPException(status_code=409, detail=DUPLICATE_NAME) from error
    db.commit()  # the department and its audit row: one transaction
    return department


@router.patch("/{department_id}", response_model=DepartmentOut)
def rename_department(
    department_id: uuid.UUID,
    payload: DepartmentNameRequest,
    admin: User = Depends(require_permission(Permission.MANAGE_DEPARTMENTS)),
    db: Session = Depends(get_db),
) -> Department:
    try:
        department = departments_service.rename_department(
            db, admin, department_id, payload.name, datetime.now(UTC)
        )
    except DuplicateDepartmentName as error:
        db.rollback()
        raise HTTPException(status_code=409, detail=DUPLICATE_NAME) from error
    db.commit()
    return department


@router.post("/{department_id}/archive", response_model=DepartmentOut)
def archive_department(
    department_id: uuid.UUID,
    admin: User = Depends(require_permission(Permission.MANAGE_DEPARTMENTS)),
    db: Session = Depends(get_db),
) -> Department:
    department = departments_service.set_archived(db, admin, department_id, True, datetime.now(UTC))
    db.commit()
    return department


@router.post("/{department_id}/unarchive", response_model=DepartmentOut)
def unarchive_department(
    department_id: uuid.UUID,
    admin: User = Depends(require_permission(Permission.MANAGE_DEPARTMENTS)),
    db: Session = Depends(get_db),
) -> Department:
    department = departments_service.set_archived(
        db, admin, department_id, False, datetime.now(UTC)
    )
    db.commit()
    return department
