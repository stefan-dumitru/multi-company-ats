"""A candidate's resume: storing a new one, reading the current one, and cleaning up old ones.

The order in `store_resume` matters. Everything that can be refused is refused first (type, limit),
and only then is the object written to storage; the database rows follow, and the caller commits.
If that commit fails, the caller removes the object again (`discard_stored_object`), so a failure
never leaves a file that nothing points at.
"""

import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.integrations import storage
from app.models import CandidateProfile, File, User
from app.services.candidates import get_profile
from app.services.errors import (
    NotFoundError,
    ResumeEmpty,
    ResumeTypeUnsupported,
    UploadLimitReached,
)
from app.services.resume_files import clean_filename, detect_resume_type
from app.worker.queue import enqueue

logger = logging.getLogger(__name__)

UPLOADS_PER_HOUR = 5
KEY_PREFIX = "resumes/"


def _uploads_in_the_last_hour(db: Session, user: User, now: datetime) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(File)
            .where(File.owner_user_id == user.id, File.uploaded_at >= now - timedelta(hours=1))
        )
        or 0
    )


def store_resume(db: Session, user: User, filename: str, data: bytes, now: datetime) -> File:
    """Check the file, write it to storage, and make it the candidate's current resume.

    Raises ResumeEmpty, ResumeTypeUnsupported, UploadLimitReached, or a storage error (nothing is
    changed in that case). The caller commits, and calls `discard_stored_object` if that fails.
    """
    if not data:
        raise ResumeEmpty
    content_type = detect_resume_type(data)
    if content_type is None:
        raise ResumeTypeUnsupported
    if _uploads_in_the_last_hour(db, user, now) >= UPLOADS_PER_HOUR:
        raise UploadLimitReached

    # Generated here and never derived from the filename, so a name cannot reach the bucket.
    key = f"{KEY_PREFIX}{uuid.uuid4()}"
    storage.put_object(key, data, content_type)

    file = File(
        owner_user_id=user.id,
        storage_key=key,
        original_filename=clean_filename(filename, content_type),
        content_type=content_type,
        size_bytes=len(data),
        uploaded_at=now,
    )
    db.add(file)
    db.flush()

    profile = get_profile(db, user)
    replaced_id = profile.current_resume_file_id
    profile.current_resume_file_id = file.id
    if replaced_id is not None:
        # Removing the old object is the worker's job, after this commit. It re-checks at that
        # moment whether anything still needs it, so an application that snapshotted it keeps it.
        enqueue(
            db,
            type="delete_file",
            payload={"file_id": str(replaced_id)},
            idempotency_key=f"delete_file:{replaced_id}",
            now=now,
        )
    db.flush()
    return file


def discard_stored_object(key: str) -> None:
    """Best effort after a failed commit: an object nothing points at is harmless, only untidy."""
    try:
        storage.delete_object(key)
    except storage.StorageError:
        logger.warning("Could not remove an unreferenced resume object after a failed save")


def current_resume(db: Session, user: User) -> File | None:
    """The candidate's current resume record, or None."""
    profile = db.get(CandidateProfile, user.id)
    if profile is None or profile.current_resume_file_id is None:
        return None
    return db.get(File, profile.current_resume_file_id)


def open_current_resume(db: Session, user: User) -> tuple[File, storage.StoredObject]:
    """The record and the bytes of the candidate's own current resume. NotFoundError if none."""
    file = current_resume(db, user)
    if file is None:
        raise NotFoundError
    try:
        return file, storage.open_object(file.storage_key)
    except storage.ObjectNotFound as error:
        logger.error("A resume record points at an object that is not in storage")
        raise NotFoundError from error


def file_is_in_use(db: Session, file_id: uuid.UUID) -> bool:
    """Whether anything still needs this file. Grows when applications start to point at files."""
    current = db.scalar(
        select(CandidateProfile.user_id).where(CandidateProfile.current_resume_file_id == file_id)
    )
    return current is not None


def delete_file_if_unused(db: Session, file_id: uuid.UUID, now: datetime) -> bool:
    """Remove a file's object from storage if nothing needs it. Returns whether it was removed.

    Safe to run twice. Raises a storage error when storage is down, so the worker retries later.
    """
    file = db.get(File, file_id)
    if file is None or file.deleted_at is not None:
        return False
    if file_is_in_use(db, file.id):
        return False
    storage.delete_object(file.storage_key)  # a missing object is fine: the goal is "gone"
    file.deleted_at = now
    return True
