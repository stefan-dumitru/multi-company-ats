"""What staff can see of applications (functional.md > Candidate applies to a job).

The rules under test: an admin sees the applications of every job in their company, a recruiter
only of the jobs assigned to them, nobody else sees any; anything outside that is "not found"
(never "forbidden"); and the resume staff download is the one the candidate applied with, not
whatever they uploaded since.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.integrations import storage
from app.models import (
    Application,
    ApplicationStage,
    CandidateProfile,
    Company,
    File,
    Job,
    PostingStatus,
    Role,
    User,
)
from tests.browser import Browser
from tests.factories import (
    make_application,
    make_candidate,
    make_company,
    make_department,
    make_job,
    make_resume_file,
    make_user,
)
from tests.test_resume_files import MINIMAL_PDF

NOT_FOUND = {"detail": "Not found."}
LIST_FIELDS = {"id", "candidate_name", "candidate_email", "stage", "applied_at"}


@dataclass
class World:
    acme: Company
    admin: User
    recruiter: User  # assigned to `job`
    other_recruiter: User  # assigned to `other_job` only
    interviewer: User
    job: Job
    other_job: Job
    draft_job: Job
    cara: User
    dan: User
    eve: User
    cara_application: Application
    dan_application: Application  # withdrawn
    eve_application: Application  # on `other_job`
    globex_admin: User
    globex_application: Application


def store_resume(file: File, content: bytes) -> None:
    """Put real bytes behind a resume record (the factory makes the record only)."""
    storage.put_object(file.storage_key, content, file.content_type)


@pytest.fixture
def world(db: Session) -> World:
    acme, globex = make_company(db, "Acme"), make_company(db, "Globex")
    department = make_department(db, acme, "Engineering")
    admin = make_user(db, email="admin@acme.test", role=Role.COMPANY_ADMIN, company=acme)
    recruiter = make_user(db, email="rec@acme.test", role=Role.RECRUITER, company=acme)
    other_recruiter = make_user(db, email="rec2@acme.test", role=Role.RECRUITER, company=acme)
    interviewer = make_user(db, email="int@acme.test", role=Role.INTERVIEWER, company=acme)

    def job(title: str, recruiters: list[User], status: PostingStatus) -> Job:
        return make_job(
            db,
            company=acme,
            department=department,
            created_by=admin,
            recruiters=recruiters,
            status=status,
            title=title,
        )

    first_job = job("Backend Engineer", [recruiter], PostingStatus.OPEN)
    other_job = job("Designer", [other_recruiter], PostingStatus.OPEN)
    draft_job = job("Secret draft", [recruiter], PostingStatus.DRAFT)

    cara = make_candidate(db, email="cara@example.test", full_name="Cara Candidate")
    dan = make_candidate(db, email="dan@example.test", full_name="Dan Candidate")
    eve = make_candidate(db, email="eve@example.test", full_name="Eve Candidate")
    cara_application = make_application(db, job=first_job, candidate=cara)
    dan_application = make_application(
        db, job=first_job, candidate=dan, stage=ApplicationStage.WITHDRAWN
    )
    eve_application = make_application(db, job=other_job, candidate=eve)
    # Distinct, known times so the order ("newest first") is not an accident of insertion.
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for days, application in enumerate((cara_application, dan_application, eve_application)):
        application.created_at = base + timedelta(days=days)

    globex_admin = make_user(db, email="admin@globex.test", role=Role.COMPANY_ADMIN, company=globex)
    globex_job = make_job(
        db,
        company=globex,
        department=make_department(db, globex, "Platform"),
        created_by=globex_admin,
        recruiters=[],
        status=PostingStatus.OPEN,
    )
    globex_application = make_application(
        db, job=globex_job, candidate=make_candidate(db, email="gina@example.test")
    )
    db.commit()
    return World(
        acme,
        admin,
        recruiter,
        other_recruiter,
        interviewer,
        first_job,
        other_job,
        draft_job,
        cara,
        dan,
        eve,
        cara_application,
        dan_application,
        eve_application,
        globex_admin,
        globex_application,
    )


def applicants(browser: Browser, job: Job, query: str = "") -> list[dict[str, object]]:
    response = browser.get(f"/api/jobs/{job.id}/applications{query}")
    assert response.status_code == 200
    return list(response.json()["items"])


# ---- the list on a job ---------------------------------------------------------------------


def test_an_admin_sees_who_applied_to_a_job(client: TestClient, db: Session, world: World) -> None:
    response = Browser(client, db, world.admin).get(f"/api/jobs/{world.job.id}/applications")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2 and body["page"] == 1
    newest, oldest = body["items"]
    assert set(newest) == LIST_FIELDS
    assert newest["id"] == str(world.dan_application.id)
    assert newest["candidate_name"] == "Dan Candidate"
    assert newest["candidate_email"] == "dan@example.test"
    assert newest["stage"] == "withdrawn"  # staff see withdrawn applications, marked as such
    assert oldest["id"] == str(world.cara_application.id)
    assert oldest["stage"] == "applied"


def test_the_list_is_newest_first_and_paged(client: TestClient, db: Session, world: World) -> None:
    browser = Browser(client, db, world.admin)

    first = applicants(browser, world.job, "?page=1&page_size=1")
    second = applicants(browser, world.job, "?page=2&page_size=1")

    assert [row["id"] for row in first] == [str(world.dan_application.id)]
    assert [row["id"] for row in second] == [str(world.cara_application.id)]


def test_a_recruiter_sees_the_applicants_of_their_own_jobs(
    client: TestClient, db: Session, world: World
) -> None:
    rows = applicants(Browser(client, db, world.recruiter), world.job)

    assert {row["id"] for row in rows} == {
        str(world.cara_application.id),
        str(world.dan_application.id),
    }


def test_a_recruiter_gets_not_found_for_a_job_that_is_not_assigned_to_them(
    client: TestClient, db: Session, world: World
) -> None:
    browser = Browser(client, db, world.recruiter)

    response = browser.get(f"/api/jobs/{world.other_job.id}/applications")

    assert response.status_code == 404 and response.json() == NOT_FOUND


def test_a_job_nobody_applied_to_has_an_empty_list(
    client: TestClient, db: Session, world: World
) -> None:
    response = Browser(client, db, world.admin).get(f"/api/jobs/{world.draft_job.id}/applications")

    assert response.status_code == 200
    assert response.json()["items"] == [] and response.json()["total"] == 0


def test_an_unknown_job_is_not_found(client: TestClient, db: Session, world: World) -> None:
    response = Browser(client, db, world.admin).get(
        "/api/jobs/6f1c2d3e-0000-4000-8000-000000000000/applications"
    )

    assert response.status_code == 404 and response.json() == NOT_FOUND


def test_another_companys_admin_gets_not_found_for_the_list(
    client: TestClient, db: Session, world: World
) -> None:
    response = Browser(client, db, world.globex_admin).get(f"/api/jobs/{world.job.id}/applications")

    assert response.status_code == 404 and response.json() == NOT_FOUND


@pytest.mark.parametrize("who", ["interviewer", "cara"])
def test_interviewers_and_candidates_cannot_list_applicants(
    client: TestClient, db: Session, world: World, who: str
) -> None:
    user: User = getattr(world, who)

    response = Browser(client, db, user).get(f"/api/jobs/{world.job.id}/applications")

    assert response.status_code == 403


# ---- downloading the resume an application was made with -------------------------------------


def test_an_admin_downloads_the_resume_as_an_attachment(
    client: TestClient, db: Session, world: World, storage_bucket: str
) -> None:
    file = db.get(File, world.cara_application.resume_file_id)
    assert file is not None
    file.original_filename = "Cara CV.pdf"
    db.commit()
    store_resume(file, MINIMAL_PDF)

    response = Browser(client, db, world.admin).get(
        f"/api/applications/{world.cara_application.id}/resume"
    )

    assert response.status_code == 200
    assert response.content == MINIMAL_PDF
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert 'filename="Cara CV.pdf"' in response.headers["content-disposition"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "no-store" in response.headers["cache-control"]


def test_staff_get_the_resume_the_candidate_applied_with_not_a_newer_one(
    client: TestClient, db: Session, world: World, storage_bucket: str
) -> None:
    applied_with = db.get(File, world.cara_application.resume_file_id)
    assert applied_with is not None
    store_resume(applied_with, MINIMAL_PDF)
    newer = make_resume_file(db, world.cara, "newer.pdf")
    store_resume(newer, MINIMAL_PDF + b"the newer one")
    profile = db.get(CandidateProfile, world.cara.id)
    assert profile is not None
    profile.current_resume_file_id = newer.id
    db.commit()

    response = Browser(client, db, world.admin).get(
        f"/api/applications/{world.cara_application.id}/resume"
    )

    assert response.content == MINIMAL_PDF


def test_a_recruiter_downloads_the_resume_for_their_own_job_only(
    client: TestClient, db: Session, world: World, storage_bucket: str
) -> None:
    for application in (world.cara_application, world.eve_application):
        file = db.get(File, application.resume_file_id)
        assert file is not None
        store_resume(file, MINIMAL_PDF)
    browser = Browser(client, db, world.recruiter)

    own = browser.get(f"/api/applications/{world.cara_application.id}/resume")
    unassigned = browser.get(f"/api/applications/{world.eve_application.id}/resume")

    assert own.status_code == 200
    assert unassigned.status_code == 404 and unassigned.json() == NOT_FOUND


def test_another_companys_admin_gets_not_found_for_the_resume(
    client: TestClient, db: Session, world: World, storage_bucket: str
) -> None:
    file = db.get(File, world.cara_application.resume_file_id)
    assert file is not None
    store_resume(file, MINIMAL_PDF)

    response = Browser(client, db, world.globex_admin).get(
        f"/api/applications/{world.cara_application.id}/resume"
    )

    assert response.status_code == 404 and response.json() == NOT_FOUND


def test_an_unknown_application_is_not_found(
    client: TestClient, db: Session, world: World, storage_bucket: str
) -> None:
    response = Browser(client, db, world.admin).get(
        "/api/applications/6f1c2d3e-0000-4000-8000-000000000000/resume"
    )

    assert response.status_code == 404 and response.json() == NOT_FOUND


def test_a_resume_that_is_gone_from_storage_is_not_found(
    client: TestClient, db: Session, world: World, storage_bucket: str
) -> None:
    # The record exists but nothing was stored behind it.
    response = Browser(client, db, world.admin).get(
        f"/api/applications/{world.cara_application.id}/resume"
    )

    assert response.status_code == 404 and response.json() == NOT_FOUND


def test_without_storage_settings_the_download_says_storage_is_unavailable(
    client: TestClient, db: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("S3_ENDPOINT_URL", "S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY"):
        monkeypatch.delenv(name, raising=False)

    response = Browser(client, db, world.admin).get(
        f"/api/applications/{world.cara_application.id}/resume"
    )

    assert response.status_code == 503 and response.json()["code"] == "storage_unavailable"


@pytest.mark.parametrize("who", ["interviewer", "cara"])
def test_interviewers_and_candidates_cannot_download_an_applicants_resume(
    client: TestClient, db: Session, world: World, storage_bucket: str, who: str
) -> None:
    # Even the applicant: their own download is /api/profile/resume, a different route.
    user: User = getattr(world, who)

    response = Browser(client, db, user).get(
        f"/api/applications/{world.cara_application.id}/resume"
    )

    assert response.status_code == 403
