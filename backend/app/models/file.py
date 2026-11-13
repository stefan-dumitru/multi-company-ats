import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class File(Base):
    """Metadata for an uploaded resume kept in object storage (data-model.md > File).

    Immutable once uploaded: a "replacement" is a new row. The bytes live in the bucket under
    `storage_key`, which the app generates; the original name is display-only.
    """

    __tablename__ = "files"
    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="size_is_positive"),
        # "How many files did this person upload in the last hour?" (the upload limit)
        Index("ix_files_owner_user_id_uploaded_at", "owner_user_id", "uploaded_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    storage_key: Mapped[str] = mapped_column(String(200), unique=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Set once the object has been removed from storage.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
