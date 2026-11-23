import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ExternalIdentity(Base):
    """A person's account at an outside sign-in provider, tied to their account here
    (data-model.md). Only Google today. `subject` is Google's own stable id for the person: unlike
    an email address it never changes, so it is what we recognize them by after the first time.

    Deleted with the user. Holds no token: signing in does not keep anything from Google."""

    __tablename__ = "external_identities"
    __table_args__ = (
        CheckConstraint("provider IN ('google')", name="provider_known"),
        # One Google account is one person here...
        UniqueConstraint("provider", "subject"),
        # ...and one person has at most one Google account linked.
        UniqueConstraint("user_id", "provider"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    provider: Mapped[str] = mapped_column(String(20))
    subject: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
