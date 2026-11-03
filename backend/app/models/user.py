import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Role(enum.StrEnum):
    COMPANY_ADMIN = "company_admin"
    RECRUITER = "recruiter"
    INTERVIEWER = "interviewer"
    CANDIDATE = "candidate"


STAFF_ROLES = (Role.COMPANY_ADMIN, Role.RECRUITER, Role.INTERVIEWER)


def role_column() -> Enum:
    """A role stored as text with a CHECK constraint, so the database rejects unknown values."""
    return Enum(
        Role,
        native_enum=False,
        length=20,
        create_constraint=True,
        name="role_is_known",
        values_callable=lambda roles: [role.value for role in roles],
    )


class User(Base):
    """One login account for everyone: staff and candidates share this table."""

    __tablename__ = "users"
    __table_args__ = (
        # One email is one account, whatever its capitalisation, across all companies.
        Index("uq_users_email_lower", func.lower(text("email")), unique=True),
        # Staff belong to exactly one company; candidates belong to none.
        CheckConstraint("(role = 'candidate') = (company_id IS NULL)", name="company_matches_role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("companies.id"))
    role: Mapped[Role] = mapped_column(role_column())
    email: Mapped[str] = mapped_column(String(320))
    full_name: Mapped[str] = mapped_column(String(200))
    # Null for accounts that can only sign in with Google (Phase 8).
    password_hash: Mapped[str | None] = mapped_column(String(255))
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    anonymized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
