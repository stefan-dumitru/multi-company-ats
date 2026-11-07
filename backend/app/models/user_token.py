import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class UserToken(Base):
    """A single-use link sent to a user by email: verify the address, or reset the password.

    Nothing secret is stored: the link in the email is `<this row's id>.<signature>` (see
    auth/tokens.py), so a leaked database yields no usable links. What is stored is the state the
    signature cannot carry: whether the link was used, and when it expires.
    """

    __tablename__ = "user_tokens"
    __table_args__ = (
        CheckConstraint("type IN ('email_verification', 'password_reset')", name="type_is_known"),
        # "How many links did this user ask for lately?" (the hourly limit)
        Index("ix_user_tokens_user_id_type_created_at", "user_id", "type", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    type: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
