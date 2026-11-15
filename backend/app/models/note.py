import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

MAX_NOTE_LENGTH = 4000


class Note(Base):
    """An internal comment on an application (data-model.md > Note).

    Append-only: no edit, no delete. Staff only: no candidate-facing response ever includes one.
    """

    __tablename__ = "notes"
    __table_args__ = (
        CheckConstraint("length(btrim(body)) > 0", name="body_not_blank"),
        CheckConstraint(f"length(body) <= {MAX_NOTE_LENGTH}", name="body_not_too_long"),
        Index("ix_notes_application_id_created_at", "application_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id"))
    # Copied from the application, so a company's notes can be filtered by one column.
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
