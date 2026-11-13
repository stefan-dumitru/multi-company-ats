import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class CandidateProfile(Base):
    """Candidate-specific details, kept off `User` so staff rows stay clean (data-model.md).

    The resume pointer and the talent-pool opt-in join this table in the phases that use them.
    """

    __tablename__ = "candidate_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    phone: Mapped[str | None] = mapped_column(String(30))
    location: Mapped[str | None] = mapped_column(String(200))
