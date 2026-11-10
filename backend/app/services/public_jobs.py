"""Reading jobs without being logged in (functional.md > Search).

This is the one place that reads company data without a current user, so it is deliberately
narrow: every query here is limited to jobs with status OPEN, and only the fields the public may
see are selected. A draft or closed job cannot be reached through this module, by search or by id.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, func, literal_column, select
from sqlalchemy.orm import Session

from app.models import Company, Department, Job, PostingStatus
from app.pagination import PageRequest
from app.services.errors import NotFoundError

EXCERPT_LENGTH = 300


@dataclass
class PublicJobSummary:
    id: uuid.UUID
    title: str
    location: str
    excerpt: str
    department_name: str
    company_id: uuid.UUID
    company_name: str
    opened_at: datetime | None


@dataclass
class PublicJob:
    id: uuid.UUID
    title: str
    location: str
    description: str
    department_name: str
    company_id: uuid.UUID
    company_name: str
    opened_at: datetime | None


def _keyword_query(text: str) -> ColumnElement[object]:
    """The user's words as a search query.

    `websearch_to_tsquery` reads what people expect from a search box (quoted phrases, `or`, a
    leading `-`) and never fails on odd input: it is not the raw query syntax. The language is
    written as a literal, matching the one the stored search column was built with.
    """
    return func.websearch_to_tsquery(literal_column("'english'"), text)


def search_open_jobs(
    db: Session,
    page: PageRequest,
    *,
    keywords: str | None,
    location: str | None,
    company_id: uuid.UUID | None,
) -> tuple[list[PublicJobSummary], int]:
    """One page of open jobs, best match first when searching, otherwise newest first."""
    wanted: list[ColumnElement[bool]] = [Job.status == PostingStatus.OPEN]
    if location is not None:
        # autoescape: a `%` or `_` typed by the visitor is just a character, not a wildcard.
        wanted.append(Job.location.icontains(location, autoescape=True))
    if company_id is not None:
        wanted.append(Job.company_id == company_id)

    order_by: list[Any] = []  # a mix of column and ordering expressions
    if keywords is not None:
        query = _keyword_query(keywords)
        wanted.append(Job.search_vector.op("@@")(query))
        order_by.append(func.ts_rank(Job.search_vector, query).desc())
    order_by += [Job.opened_at.desc().nulls_last(), Job.id]

    total = db.scalar(select(func.count()).select_from(Job).where(*wanted)) or 0
    rows = db.execute(
        select(
            Job.id,
            Job.title,
            Job.location,
            # Cut in the database, so a page of long descriptions is not carried over the wire.
            func.left(Job.description, EXCERPT_LENGTH),
            Department.name,
            Job.company_id,
            Company.name,
            Job.opened_at,
        )
        .join(Department, Department.id == Job.department_id)
        .join(Company, Company.id == Job.company_id)
        .where(*wanted)
        .order_by(*order_by)
        .limit(page.page_size)
        .offset(page.offset)
    )
    items = [
        PublicJobSummary(
            id, title, place, excerpt.rstrip(), department, company, company_name, opened
        )
        for id, title, place, excerpt, department, company, company_name, opened in rows
    ]
    return items, total


def get_open_job(db: Session, job_id: uuid.UUID) -> PublicJob:
    """One open job in full. A draft, a closed job and an unknown id are all just "not found"."""
    row = db.execute(
        select(
            Job.id,
            Job.title,
            Job.location,
            Job.description,
            Department.name,
            Job.company_id,
            Company.name,
            Job.opened_at,
        )
        .join(Department, Department.id == Job.department_id)
        .join(Company, Company.id == Job.company_id)
        .where(Job.id == job_id, Job.status == PostingStatus.OPEN)
    ).first()
    if row is None:
        raise NotFoundError
    return PublicJob(*row)
