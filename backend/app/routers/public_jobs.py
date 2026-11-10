import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.permissions import public_route
from app.db import get_db
from app.pagination import Page, PageRequest, page_request
from app.schemas.public_jobs import PublicJobOut, PublicJobSummaryOut
from app.services import public_jobs as public_jobs_service

router = APIRouter(prefix="/api/public/jobs", tags=["public jobs"])

MAX_TEXT_LENGTH = 200
# A NUL character cannot be stored or searched in Postgres text; refuse it at the door.
NO_NUL = r"^[^\x00]*$"


@router.get("", response_model=Page[PublicJobSummaryOut], dependencies=[Depends(public_route)])
def search_jobs(
    q: str | None = Query(default=None, max_length=MAX_TEXT_LENGTH, pattern=NO_NUL),
    location: str | None = Query(default=None, max_length=MAX_TEXT_LENGTH, pattern=NO_NUL),
    company_id: uuid.UUID | None = None,
    page: PageRequest = Depends(page_request),
    db: Session = Depends(get_db),
) -> Page[PublicJobSummaryOut]:
    # A box that holds only spaces means "no search", not "search for nothing".
    keywords = (q or "").strip() or None
    place = (location or "").strip() or None
    rows, total = public_jobs_service.search_open_jobs(
        db, page, keywords=keywords, location=place, company_id=company_id
    )
    items = [PublicJobSummaryOut(**vars(row)) for row in rows]
    return Page(items=items, total=total, page=page.page, page_size=page.page_size)


@router.get("/{job_id}", response_model=PublicJobOut, dependencies=[Depends(public_route)])
def read_job(job_id: uuid.UUID, db: Session = Depends(get_db)) -> PublicJobOut:
    return PublicJobOut(**vars(public_jobs_service.get_open_job(db, job_id)))
