"""Uploading, replacing and downloading a resume (security.md > File Upload Handling).

Real storage server, real database. The rules under test: the type is decided from the bytes, the
size limit is 5 MB, the stored key is generated and never holds the filename, nothing is written
unless the caller is allowed to upload, and a replaced resume is removed once nothing needs it.
"""

import io
import re
import uuid
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_storage_settings
from app.integrations import storage
from app.models import BackgroundJob, CandidateProfile, File, Role, User
from app.routers import profile as profile_router
from app.worker.handlers import HANDLERS
from app.worker.runner import run_one_job
from tests.browser import Browser
from tests.factories import make_company, make_user
from tests.test_resume_files import MINIMAL_PDF, make_docx

KEY_PATTERN = re.compile(r"^resumes/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
FIVE_MB = 5 * 1024 * 1024


def a_pdf(size: int | None = None) -> bytes:
    """A PDF-looking file, padded to `size` bytes when asked."""
    if size is None:
        return MINIMAL_PDF
    return MINIMAL_PDF + b"x" * (size - len(MINIMAL_PDF))


def candidate(db: Session, email: str = "cara@example.test", verified: bool = True) -> User:
    user = make_user(
        db, email=email, role=Role.CANDIDATE, company=None, full_name="Cara", verified=verified
    )
    db.commit()
    return user


def upload(browser: Browser, data: bytes | Iterator[bytes], filename: str = "cv.pdf") -> Any:
    return browser.send("PUT", f"/api/profile/resume?filename={quote(filename)}", content=data)


def bucket_keys() -> list[str]:
    settings = get_storage_settings()
    assert settings is not None
    listing = storage.client_for(settings).list_objects_v2(Bucket=settings.bucket)
    return sorted(item["Key"] for item in listing.get("Contents", []))


def stored_bytes(key: str) -> bytes:
    return b"".join(storage.open_object(key).chunks)


def file_count(db: Session) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(File)) or 0


def run_pending_jobs(db: Session) -> None:
    while run_one_job(db, HANDLERS):
        pass


# ---- the happy path ----------------------------------------------------------------------


def test_a_candidate_uploads_a_pdf(client: TestClient, db: Session, storage_bucket: str) -> None:
    user = candidate(db)
    browser = Browser(client, db, user)

    response = upload(browser, a_pdf(), "My CV.pdf")

    assert response.status_code == 200
    body = response.json()
    assert body["filename"] == "My CV.pdf" and body["size_bytes"] == len(MINIMAL_PDF)
    assert set(body) == {"filename", "size_bytes", "uploaded_at"}  # never the storage key
    file = db.scalars(select(File)).one()
    assert file.owner_user_id == user.id
    assert file.content_type == "application/pdf" and file.size_bytes == len(MINIMAL_PDF)
    assert file.original_filename == "My CV.pdf" and file.deleted_at is None
    assert bucket_keys() == [file.storage_key]
    assert stored_bytes(file.storage_key) == MINIMAL_PDF


def test_the_new_resume_becomes_the_profiles_current_one(
    client: TestClient, db: Session, storage_bucket: str
) -> None:
    user = candidate(db)
    browser = Browser(client, db, user)

    upload(browser, a_pdf())

    db.expire_all()
    profile = db.get(CandidateProfile, user.id)
    file = db.scalars(select(File)).one()
    assert profile is not None and profile.current_resume_file_id == file.id
    shown = browser.get("/api/profile").json()["resume"]
    assert shown["filename"] == "cv.pdf" and shown["size_bytes"] == len(MINIMAL_PDF)


def test_the_profile_has_no_resume_until_one_is_uploaded(
    client: TestClient, db: Session, storage_bucket: str
) -> None:
    browser = Browser(client, db, candidate(db))

    assert browser.get("/api/profile").json()["resume"] is None


def test_a_word_file_is_accepted(client: TestClient, db: Session, storage_bucket: str) -> None:
    browser = Browser(client, db, candidate(db))

    response = upload(browser, make_docx(), "cv.docx")

    assert response.status_code == 200
    file = db.scalars(select(File)).one()
    assert file.content_type.endswith("wordprocessingml.document")
    assert response.json()["filename"] == "cv.docx"


# ---- the type comes from the bytes -------------------------------------------------------


def test_a_program_pretending_to_be_a_pdf_is_refused_and_nothing_is_stored(
    client: TestClient, db: Session, storage_bucket: str
) -> None:
    browser = Browser(client, db, candidate(db))

    response = upload(browser, b"MZ\x90\x00" + b"\x00" * 200, "totally-a-resume.pdf")

    assert response.status_code == 422
    assert response.json()["code"] == "resume_type_unsupported"
    assert bucket_keys() == [] and file_count(db) == 0


def test_the_content_type_the_browser_claims_is_ignored(
    client: TestClient, db: Session, storage_bucket: str
) -> None:
    browser = Browser(client, db, candidate(db))

    lying = browser.client.put(
        "/api/profile/resume?filename=cv.pdf",
        content=b"just some text",
        headers={"X-CSRF-Token": browser.csrf, "Content-Type": "application/pdf"},
    )
    honest = browser.client.put(
        "/api/profile/resume?filename=cv.pdf",
        content=a_pdf(),
        headers={"X-CSRF-Token": browser.csrf, "Content-Type": "text/plain"},
    )

    assert lying.status_code == 422
    assert honest.status_code == 200


def test_a_real_pdf_with_a_dangerous_name_is_kept_but_renamed_safely(
    client: TestClient, db: Session, storage_bucket: str
) -> None:
    browser = Browser(client, db, candidate(db))

    response = upload(browser, a_pdf(), "cv.exe")

    assert response.status_code == 200
    assert response.json()["filename"] == "cv.exe.pdf"


@pytest.mark.parametrize("data", [b"", b"%PDF", b"PK\x03\x04 not really a zip"])
def test_empty_or_broken_files_are_refused(
    client: TestClient, db: Session, storage_bucket: str, data: bytes
) -> None:
    browser = Browser(client, db, candidate(db))

    response = upload(browser, data)

    assert response.status_code in (422,)
    assert bucket_keys() == [] and file_count(db) == 0


def test_an_empty_body_gets_its_own_message(
    client: TestClient, db: Session, storage_bucket: str
) -> None:
    browser = Browser(client, db, candidate(db))

    response = upload(browser, b"")

    assert response.json()["code"] == "resume_empty"


def test_a_zip_bomb_shaped_word_file_is_refused_without_being_unpacked(
    client: TestClient, db: Session, storage_bucket: str
) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<document/>")
        for number in range(1500):
            archive.writestr(f"word/e{number}.xml", "x")
    browser = Browser(client, db, candidate(db))

    response = upload(browser, buffer.getvalue(), "cv.docx")

    assert response.status_code == 422 and bucket_keys() == []


# ---- the size limit ----------------------------------------------------------------------


def test_a_file_of_exactly_five_megabytes_is_accepted(
    client: TestClient, db: Session, storage_bucket: str
) -> None:
    browser = Browser(client, db, candidate(db))

    response = upload(browser, a_pdf(FIVE_MB))

    assert response.status_code == 200 and response.json()["size_bytes"] == FIVE_MB


def test_one_byte_more_is_too_large_and_nothing_is_stored(
    client: TestClient, db: Session, storage_bucket: str
) -> None:
    browser = Browser(client, db, candidate(db))

    response = upload(browser, a_pdf(FIVE_MB + 1))

    assert response.status_code == 413
    assert response.json()["code"] == "resume_too_large"
    assert bucket_keys() == [] and file_count(db) == 0


def test_the_limit_holds_for_a_body_that_does_not_say_how_long_it_is(
    client: TestClient, db: Session, storage_bucket: str
) -> None:
    # No Content-Length: the server has to count as the body streams in and stop at the limit.
    def six_megabytes() -> Iterator[bytes]:
        yield MINIMAL_PDF
        for _ in range(6):
            yield b"x" * (1024 * 1024)

    browser = Browser(client, db, candidate(db))

    response = upload(browser, six_megabytes())

    assert response.status_code == 413
    assert bucket_keys() == [] and file_count(db) == 0


# ---- the stored key and the stored name --------------------------------------------------


def test_the_stored_key_is_generated_and_never_contains_the_filename(
    client: TestClient, db: Session, storage_bucket: str
) -> None:
    browser = Browser(client, db, candidate(db))

    upload(browser, a_pdf(), "very-secret-name-of-cara.pdf")

    file = db.scalars(select(File)).one()
    assert KEY_PATTERN.match(file.storage_key)
    assert "secret" not in file.storage_key and "cara" not in file.storage_key
    assert bucket_keys() == [file.storage_key]


def test_every_upload_gets_a_different_key(
    client: TestClient, db: Session, storage_bucket: str
) -> None:
    browser = Browser(client, db, candidate(db))

    upload(browser, a_pdf(), "same.pdf")
    upload(browser, a_pdf(), "same.pdf")

    keys = {file.storage_key for file in db.scalars(select(File))}
    assert len(keys) == 2


@pytest.mark.parametrize(
    ("sent", "stored"),
    [
        ("../../etc/passwd.pdf", "passwd.pdf"),
        ("C:\\Users\\me\\cv.pdf", "cv.pdf"),
        ("with\nnewline.pdf", "withnewline.pdf"),
        ("<img src=x onerror=alert(1)>.pdf", "<img src=x onerror=alert(1)>.pdf"),
    ],
)
def test_the_filename_is_display_metadata_and_is_cleaned(
    client: TestClient, db: Session, storage_bucket: str, sent: str, stored: str
) -> None:
    browser = Browser(client, db, candidate(db))

    response = upload(browser, a_pdf(), sent)

    assert response.json()["filename"] == stored
    assert db.scalars(select(File)).one().original_filename == stored
    assert all(KEY_PATTERN.match(key) for key in bucket_keys())


def test_the_filename_is_required_and_limited(
    client: TestClient, db: Session, storage_bucket: str
) -> None:
    browser = Browser(client, db, candidate(db))

    missing = browser.send("PUT", "/api/profile/resume", content=a_pdf())
    too_long = upload(browser, a_pdf(), "a" * 300 + ".pdf")

    assert missing.status_code == 422
    assert too_long.status_code == 422
    assert bucket_keys() == []


# ---- nothing is written unless the caller may upload -------------------------------------


def test_a_visitor_cannot_upload_and_nothing_is_written(
    client: TestClient, db: Session, storage_bucket: str
) -> None:
    response = client.put("/api/profile/resume?filename=cv.pdf", content=a_pdf())

    assert response.status_code == 401
    assert bucket_keys() == [] and file_count(db) == 0


def test_staff_cannot_upload_and_nothing_is_written(
    client: TestClient, db: Session, storage_bucket: str
) -> None:
    company = make_company(db, "Acme")
    admin = make_user(db, email="admin@acme.test", role=Role.COMPANY_ADMIN, company=company)
    db.commit()

    response = upload(Browser(client, db, admin), a_pdf())

    assert response.status_code == 403
    assert bucket_keys() == [] and file_count(db) == 0


def test_an_unverified_candidate_cannot_upload_and_nothing_is_written(
    client: TestClient, db: Session, storage_bucket: str
) -> None:
    browser = Browser(client, db, candidate(db, verified=False))

    response = upload(browser, a_pdf())

    assert response.status_code == 403 and response.json()["code"] == "email_not_verified"
    assert bucket_keys() == [] and file_count(db) == 0


def test_a_request_without_the_csrf_token_is_refused_and_nothing_is_written(
    client: TestClient, db: Session, storage_bucket: str
) -> None:
    browser = Browser(client, db, candidate(db))

    response = browser.client.put("/api/profile/resume?filename=cv.pdf", content=a_pdf())

    assert response.status_code == 403
    assert bucket_keys() == [] and file_count(db) == 0


def test_a_refused_request_never_reads_the_body_and_an_allowed_one_does(
    client: TestClient, db: Session, storage_bucket: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Authorization comes first: a huge file from a stranger must cost nothing. The body is read
    # by `read_limited_body`; it must not run at all for a request that is refused.
    reads: list[int] = []
    real = profile_router.read_limited_body

    async def spy(request: Any, limit: int) -> bytes:
        reads.append(1)
        return await real(request, limit)

    monkeypatch.setattr(profile_router, "read_limited_body", spy)

    visitor = client.put("/api/profile/resume?filename=cv.pdf", content=a_pdf())
    unverified = upload(
        Browser(client, db, candidate(db, "u@example.test", verified=False)), a_pdf()
    )
    assert (visitor.status_code, unverified.status_code) == (401, 403)
    assert reads == []

    allowed = upload(Browser(client, db, candidate(db, "ok@example.test")), a_pdf())
    assert allowed.status_code == 200 and reads == [1]


# ---- replacing ---------------------------------------------------------------------------


def test_a_second_upload_replaces_the_first_and_the_old_file_is_removed_later(
    client: TestClient, db: Session, storage_bucket: str
) -> None:
    user = candidate(db)
    browser = Browser(client, db, user)
    upload(browser, a_pdf(), "first.pdf")
    first = db.scalars(select(File)).one()

    upload(browser, make_docx(), "second.docx")

    db.expire_all()
    files = {file.original_filename: file for file in db.scalars(select(File))}
    profile = db.get(CandidateProfile, user.id)
    assert profile is not None and profile.current_resume_file_id == files["second.docx"].id
    assert len(bucket_keys()) == 2  # the old one is still there until the worker removes it
    jobs = list(db.scalars(select(BackgroundJob).where(BackgroundJob.type == "delete_file")))
    assert [job.payload["file_id"] for job in jobs] == [str(first.id)]

    run_pending_jobs(db)

    db.expire_all()
    assert bucket_keys() == [files["second.docx"].storage_key]
    removed = db.get(File, first.id)
    assert removed is not None and removed.deleted_at is not None
    assert browser.get("/api/profile").json()["resume"]["filename"] == "second.docx"


def test_the_first_upload_queues_no_cleanup(
    client: TestClient, db: Session, storage_bucket: str
) -> None:
    upload(Browser(client, db, candidate(db)), a_pdf())

    assert db.scalars(select(BackgroundJob).where(BackgroundJob.type == "delete_file")).all() == []


def test_a_failed_replacement_keeps_the_old_resume(
    client: TestClient, db: Session, storage_bucket: str
) -> None:
    user = candidate(db)
    browser = Browser(client, db, user)
    upload(browser, a_pdf(), "first.pdf")

    refused = upload(browser, b"not a resume at all", "second.pdf")

    assert refused.status_code == 422
    assert browser.get("/api/profile").json()["resume"]["filename"] == "first.pdf"
    assert len(bucket_keys()) == 1


# ---- the hourly cap ----------------------------------------------------------------------


def test_at_most_five_uploads_per_hour(
    client: TestClient, db: Session, storage_bucket: str
) -> None:
    browser = Browser(client, db, candidate(db))
    for number in range(5):
        assert upload(browser, a_pdf(), f"cv{number}.pdf").status_code == 200

    sixth = upload(browser, a_pdf(), "cv6.pdf")

    assert sixth.status_code == 429 and sixth.json()["code"] == "upload_limit"
    assert file_count(db) == 5 and len(bucket_keys()) == 5


def test_uploads_older_than_an_hour_do_not_count(
    client: TestClient, db: Session, storage_bucket: str
) -> None:
    user = candidate(db)
    browser = Browser(client, db, user)
    long_ago = datetime.now(UTC) - timedelta(hours=2)
    for number in range(5):
        db.add(
            File(
                owner_user_id=user.id,
                storage_key=f"resumes/{uuid.uuid4()}",
                original_filename=f"old{number}.pdf",
                content_type="application/pdf",
                size_bytes=10,
                uploaded_at=long_ago,
            )
        )
    db.commit()

    assert upload(browser, a_pdf()).status_code == 200


def test_the_cap_is_per_candidate(client: TestClient, db: Session, storage_bucket: str) -> None:
    busy = Browser(client, db, candidate(db, "busy@example.test"))
    for number in range(5):
        upload(busy, a_pdf(), f"cv{number}.pdf")

    other = Browser(client, db, candidate(db, "other@example.test"))

    assert upload(other, a_pdf()).status_code == 200


# ---- when storage is unavailable ---------------------------------------------------------


def test_with_storage_down_the_upload_fails_clearly_and_changes_nothing(
    client: TestClient, db: Session, storage_bucket: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = candidate(db)
    browser = Browser(client, db, user)
    monkeypatch.setenv("S3_ENDPOINT_URL", "http://127.0.0.1:1")

    response = upload(browser, a_pdf())

    assert response.status_code == 503
    assert response.json() == {
        "detail": "File storage is not available. Please try again later.",
        "code": "storage_unavailable",
    }
    assert file_count(db) == 0
    db.expire_all()
    profile = db.get(CandidateProfile, user.id)
    assert profile is None or profile.current_resume_file_id is None


def test_without_storage_settings_the_upload_says_the_same(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    browser = Browser(client, db, candidate(db))
    for name in ("S3_ENDPOINT_URL", "S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY"):
        monkeypatch.delenv(name, raising=False)

    response = upload(browser, a_pdf())

    assert response.status_code == 503 and response.json()["code"] == "storage_unavailable"


def test_if_the_database_fails_after_the_file_was_stored_the_file_is_removed(
    client: TestClient, db: Session, storage_bucket: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    browser = Browser(client, db, candidate(db))

    def failing_commit() -> None:
        raise RuntimeError("the database went away")

    with (
        monkeypatch.context() as scoped
    ):  # undone at the end of the block, the bucket setting stays
        scoped.setattr(db, "commit", failing_commit)
        with pytest.raises(RuntimeError):
            upload(browser, a_pdf())

    assert bucket_keys() == []  # no orphan left behind


# ---- downloading your own resume ---------------------------------------------------------


def test_a_candidate_downloads_their_own_resume_as_an_attachment(
    client: TestClient, db: Session, storage_bucket: str
) -> None:
    browser = Browser(client, db, candidate(db))
    upload(browser, a_pdf(), "My CV.pdf")

    response = browser.get("/api/profile/resume")

    assert response.status_code == 200
    assert response.content == MINIMAL_PDF
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert 'filename="My CV.pdf"' in response.headers["content-disposition"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "no-store" in response.headers["cache-control"]
    assert response.headers["content-length"] == str(len(MINIMAL_PDF))


def test_a_name_with_accents_is_downloadable(
    client: TestClient, db: Session, storage_bucket: str
) -> None:
    browser = Browser(client, db, candidate(db))
    upload(browser, a_pdf(), "résumé.pdf")

    header = browser.get("/api/profile/resume").headers["content-disposition"]

    assert "filename*=UTF-8''r%C3%A9sum%C3%A9.pdf" in header


def test_a_word_file_downloads_with_its_own_type(
    client: TestClient, db: Session, storage_bucket: str
) -> None:
    browser = Browser(client, db, candidate(db))
    upload(browser, make_docx(), "cv.docx")

    response = browser.get("/api/profile/resume")

    assert response.headers["content-type"].endswith("wordprocessingml.document")


def test_there_is_nothing_to_download_before_an_upload(
    client: TestClient, db: Session, storage_bucket: str
) -> None:
    assert Browser(client, db, candidate(db)).get("/api/profile/resume").status_code == 404


def test_each_candidate_gets_only_their_own_resume(
    client: TestClient, db: Session, storage_bucket: str
) -> None:
    cara = Browser(client, db, candidate(db, "cara@example.test"))
    upload(cara, a_pdf(), "cara.pdf")
    dan = Browser(client, db, candidate(db, "dan@example.test"))
    other_pdf = MINIMAL_PDF + b"dan's own"
    upload(dan, other_pdf, "dan.pdf")

    assert dan.get("/api/profile/resume").content == other_pdf
    cara_again = Browser(
        client, db, db.scalars(select(User).where(User.email == "cara@example.test")).one()
    )
    assert cara_again.get("/api/profile/resume").content == MINIMAL_PDF


def test_staff_and_visitors_cannot_use_the_candidate_download(
    client: TestClient, db: Session, storage_bucket: str
) -> None:
    company = make_company(db, "Acme")
    admin = make_user(db, email="admin@acme.test", role=Role.COMPANY_ADMIN, company=company)
    db.commit()

    assert Browser(client, db, admin).get("/api/profile/resume").status_code == 403
    client.cookies.clear()
    assert client.get("/api/profile/resume").status_code == 401


def test_a_download_with_storage_down_fails_clearly(
    client: TestClient, db: Session, storage_bucket: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    browser = Browser(client, db, candidate(db))
    upload(browser, a_pdf())
    monkeypatch.setenv("S3_ENDPOINT_URL", "http://127.0.0.1:1")

    response = browser.get("/api/profile/resume")

    assert response.status_code == 503 and response.json()["code"] == "storage_unavailable"


def test_a_resume_whose_object_has_vanished_is_simply_not_found(
    client: TestClient, db: Session, storage_bucket: str
) -> None:
    browser = Browser(client, db, candidate(db))
    upload(browser, a_pdf())
    storage.delete_object(db.scalars(select(File)).one().storage_key)

    assert browser.get("/api/profile/resume").status_code == 404
