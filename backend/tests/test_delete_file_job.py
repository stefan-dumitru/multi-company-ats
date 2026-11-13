"""The worker job that removes a file from storage (replaced resumes).

It runs after the request, so it decides at that moment whether anything still needs the file: a
file that is still someone's current resume must never be deleted, whatever was queued.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations import storage
from app.models import BackgroundJob, CandidateProfile, File, JobStatus, Role
from app.worker import queue
from app.worker.handlers import HANDLERS
from app.worker.runner import run_one_job
from tests.factories import make_user

NOW = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)


def stored_file(db: Session, *, put: bool = True, owner_email: str = "cara@example.test") -> File:
    owner = make_user(db, email=owner_email, role=Role.CANDIDATE, company=None)
    key = f"resumes/{uuid.uuid4()}"
    if put:
        storage.put_object(key, b"%PDF-1.7 data", "application/pdf")
    file = File(
        owner_user_id=owner.id,
        storage_key=key,
        original_filename="cv.pdf",
        content_type="application/pdf",
        size_bytes=13,
        uploaded_at=NOW,
    )
    db.add(file)
    db.commit()
    return file


def queue_deletion(db: Session, file_id: uuid.UUID | str) -> BackgroundJob:
    job = queue.enqueue(
        db,
        type="delete_file",
        payload={"file_id": str(file_id)},
        idempotency_key=f"delete_file:{file_id}",
        now=NOW,
    )
    db.commit()
    return job


def object_exists(key: str) -> bool:
    try:
        storage.open_object(key).chunks.close()
    except storage.ObjectNotFound:
        return False
    return True


def test_a_file_nobody_needs_is_removed_from_storage_and_marked(
    db: Session, storage_bucket: str
) -> None:
    file = stored_file(db)
    queue_deletion(db, file.id)

    assert run_one_job(db, HANDLERS) is True

    db.expire_all()
    assert not object_exists(file.storage_key)
    reloaded = db.get(File, file.id)
    assert reloaded is not None and reloaded.deleted_at is not None
    assert db.scalars(select(BackgroundJob)).one().status == JobStatus.SUCCEEDED


def test_a_file_that_is_still_a_current_resume_is_never_removed(
    db: Session, storage_bucket: str
) -> None:
    file = stored_file(db)
    db.add(CandidateProfile(user_id=file.owner_user_id, current_resume_file_id=file.id))
    db.commit()
    queue_deletion(db, file.id)

    run_one_job(db, HANDLERS)

    db.expire_all()
    assert object_exists(file.storage_key)
    reloaded = db.get(File, file.id)
    assert reloaded is not None and reloaded.deleted_at is None


def test_running_it_twice_is_harmless(db: Session, storage_bucket: str) -> None:
    file = stored_file(db)
    queue_deletion(db, file.id)
    run_one_job(db, HANDLERS)
    db.expire_all()
    first_deleted_at = db.get(File, file.id).deleted_at  # type: ignore[union-attr]

    # A second job for the same file (a retry elsewhere, a duplicate): nothing changes.
    second = BackgroundJob(
        type="delete_file",
        payload={"file_id": str(file.id)},
        idempotency_key="another-key",
        run_at=NOW,
    )
    db.add(second)
    db.commit()
    run_one_job(db, HANDLERS)

    db.expire_all()
    assert db.get(File, file.id).deleted_at == first_deleted_at  # type: ignore[union-attr]
    assert db.get(BackgroundJob, second.id).status == JobStatus.SUCCEEDED  # type: ignore[union-attr]


def test_an_object_that_is_already_gone_still_counts_as_deleted(
    db: Session, storage_bucket: str
) -> None:
    file = stored_file(db, put=False)
    queue_deletion(db, file.id)

    run_one_job(db, HANDLERS)

    db.expire_all()
    reloaded = db.get(File, file.id)
    assert reloaded is not None and reloaded.deleted_at is not None


def test_a_job_for_a_file_that_does_not_exist_just_finishes(
    db: Session, storage_bucket: str
) -> None:
    queue_deletion(db, uuid.uuid4())

    run_one_job(db, HANDLERS)

    assert db.scalars(select(BackgroundJob)).one().status == JobStatus.SUCCEEDED


def test_when_storage_is_down_the_job_is_retried_and_the_file_is_not_marked(
    db: Session, storage_bucket: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = stored_file(db)
    queue_deletion(db, file.id)
    monkeypatch.setenv("S3_ENDPOINT_URL", "http://127.0.0.1:1")

    run_one_job(db, HANDLERS)

    db.expire_all()
    job = db.scalars(select(BackgroundJob)).one()
    assert job.status == JobStatus.PENDING and job.attempts == 1  # waiting for its next try
    reloaded = db.get(File, file.id)
    assert reloaded is not None and reloaded.deleted_at is None
