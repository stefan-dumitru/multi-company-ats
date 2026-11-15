"""Internal notes on an application: staff only, append-only.

Both functions reach the application through `reachable_application`, so a note can only be read
or written on a job the caller may see (an admin: the company's; a recruiter: assigned ones).
Writing is further limited to recruiters by the route's permission. The caller commits.
"""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Note, User
from app.pagination import PageRequest
from app.services.audit import record_audit
from app.services.pipeline import reachable_application


def list_notes(
    db: Session, user: User, application_id: uuid.UUID, page: PageRequest
) -> tuple[list[tuple[Note, str]], int]:
    """One page of an application's notes with their authors' names, newest first."""
    application = reachable_application(db, user, application_id, lock=False)
    total = (
        db.scalar(
            select(func.count()).select_from(Note).where(Note.application_id == application.id)
        )
        or 0
    )
    rows = db.execute(
        select(Note, User.full_name)
        .join(User, User.id == Note.author_id)
        .where(Note.application_id == application.id)
        # The id breaks ties, so a page never repeats or skips a row between requests.
        .order_by(Note.created_at.desc(), Note.id)
        .limit(page.page_size)
        .offset(page.offset)
    )
    return [(note, name) for note, name in rows], total


def add_note(
    db: Session, user: User, application_id: uuid.UUID, body: str, now: datetime
) -> tuple[Note, str]:
    application = reachable_application(db, user, application_id, lock=False)
    note = Note(
        application_id=application.id,
        company_id=application.company_id,
        author_id=user.id,
        body=body,
        created_at=now,
    )
    db.add(note)
    db.flush()
    record_audit(
        db,
        actor=user,
        action="note.added",
        entity_type="note",
        entity_id=note.id,
        old_value=None,
        # Where the note is, never what it says: the text is about a person.
        new_value={"application_id": str(application.id)},
        now=now,
    )
    return note, user.full_name
