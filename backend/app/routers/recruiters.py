from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.permissions import Permission, require_permission
from app.db import get_db
from app.models import User
from app.pagination import Page, PageRequest, page_request
from app.schemas.jobs import RecruiterOut
from app.services import users as users_service

router = APIRouter(prefix="/api/recruiters", tags=["recruiters"])


@router.get("", response_model=Page[RecruiterOut])
def list_recruiters(
    page: PageRequest = Depends(page_request),
    user: User = Depends(require_permission(Permission.MANAGE_JOBS)),
    db: Session = Depends(get_db),
) -> Page[RecruiterOut]:
    """The people a job screen can offer when adding a recruiter. Admins and recruiters."""
    rows, total = users_service.list_company_recruiters(db, user, page)
    items = [RecruiterOut.model_validate(row, from_attributes=True) for row in rows]
    return Page(items=items, total=total, page=page.page, page_size=page.page_size)
