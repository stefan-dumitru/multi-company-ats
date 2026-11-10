"""Data access for departments. Every function takes the current user and filters by company."""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Department, User
from app.models.department import UNIQUE_NAME_INDEX
from app.pagination import PageRequest
from app.services.audit import record_audit
from app.services.errors import DuplicateDepartmentName, NotFoundError


def list_departments(
    db: Session, current_user: User, page: PageRequest, *, include_archived: bool
) -> tuple[list[Department], int]:
    """One page of the company's departments by name, and how many there are in all."""
    if current_user.company_id is None:
        return [], 0
    wanted = [Department.company_id == current_user.company_id]
    if not include_archived:
        wanted.append(Department.is_archived.is_(False))
    total = db.scalar(select(func.count()).select_from(Department).where(*wanted)) or 0
    rows = db.scalars(
        select(Department)
        .where(*wanted)
        # The id breaks ties, so a page never repeats or skips a row between requests.
        .order_by(func.lower(Department.name), Department.id)
        .limit(page.page_size)
        .offset(page.offset)
    )
    return list(rows), total


def get_department(db: Session, current_user: User, department_id: uuid.UUID) -> Department:
    if current_user.company_id is None:
        raise NotFoundError
    department = db.scalar(
        select(Department).where(
            Department.id == department_id, Department.company_id == current_user.company_id
        )
    )
    if department is None:
        raise NotFoundError
    return department


def _is_name_clash(error: IntegrityError) -> bool:
    diagnostics = getattr(error.orig, "diag", None)
    return diagnostics is not None and diagnostics.constraint_name == UNIQUE_NAME_INDEX


def _flush_or_report_duplicate(db: Session) -> None:
    """Write pending changes; a name clash becomes DuplicateDepartmentName.

    The unique index is the real guard (two admins creating "Sales" at the same moment both pass
    any check made beforehand). The savepoint keeps the clash from poisoning the caller's
    transaction.
    """
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError as error:
        if _is_name_clash(error):
            raise DuplicateDepartmentName from error
        raise


def create_department(db: Session, admin: User, name: str, now: datetime) -> Department:
    department = Department(company_id=admin.company_id, name=name)
    db.add(department)
    _flush_or_report_duplicate(db)
    record_audit(
        db,
        actor=admin,
        action="department.created",
        entity_type="department",
        entity_id=department.id,
        old_value=None,
        new_value={"name": name},
        now=now,
    )
    db.flush()
    return department


def rename_department(
    db: Session, admin: User, department_id: uuid.UUID, name: str, now: datetime
) -> Department:
    department = get_department(db, admin, department_id)
    if department.name == name:
        return department  # nothing to change, so nothing to record
    old_name = department.name
    department.name = name
    _flush_or_report_duplicate(db)
    record_audit(
        db,
        actor=admin,
        action="department.renamed",
        entity_type="department",
        entity_id=department.id,
        old_value={"name": old_name},
        new_value={"name": name},
        now=now,
    )
    db.flush()
    return department


def set_archived(
    db: Session, admin: User, department_id: uuid.UUID, archived: bool, now: datetime
) -> Department:
    department = get_department(db, admin, department_id)
    if department.is_archived == archived:
        return department  # already in that state: no change, no audit row
    department.is_archived = archived
    record_audit(
        db,
        actor=admin,
        action="department.archived" if archived else "department.unarchived",
        entity_type="department",
        entity_id=department.id,
        old_value={"is_archived": not archived},
        new_value={"is_archived": archived},
        now=now,
    )
    db.flush()
    return department
