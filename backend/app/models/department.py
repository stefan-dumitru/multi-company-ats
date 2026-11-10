import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# The name of the unique index below; the service recognises a clash by it.
UNIQUE_NAME_INDEX = "uq_departments_company_name"


class Department(Base):
    """Groups a company's jobs. Archived rather than deleted once used (data-model.md)."""

    __tablename__ = "departments"
    __table_args__ = (
        # One name per company, whatever its capitalisation ("Sales" and "sales" are the same).
        Index(UNIQUE_NAME_INDEX, "company_id", func.lower(text("name")), unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    name: Mapped[str] = mapped_column(String(100))
    # Archived departments cannot be picked for new jobs; existing jobs keep pointing at them.
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
