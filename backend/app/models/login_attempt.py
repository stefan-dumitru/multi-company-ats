import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class LoginAttempt(Base):
    """One failed login, kept so repeated guessing can be refused (rate limiting).

    The email is stored hashed: this table needs to count attempts per address, not to know it.
    """

    __tablename__ = "login_attempts"
    __table_args__ = (
        Index("ix_login_attempts_email_hash_attempted_at", "email_hash", "attempted_at"),
        Index("ix_login_attempts_ip_address_attempted_at", "ip_address", "attempted_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    email_hash: Mapped[str] = mapped_column(String(64))
    ip_address: Mapped[str] = mapped_column(String(45))  # long enough for an IPv6 address
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
