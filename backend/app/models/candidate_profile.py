import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class CandidateProfile(Base):
    """Candidate-specific details, kept off `User` so staff rows stay clean (data-model.md).

    The talent-pool opt-in joins this table in the phase that uses it.
    """

    __tablename__ = "candidate_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    # The resume shown to recruiters when the candidate applies from now on. Replacing it makes a
    # new File; the old one stays as long as an application still points at it.
    current_resume_file_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("files.id"))
    phone: Mapped[str | None] = mapped_column(String(30))
    location: Mapped[str | None] = mapped_column(String(200))
