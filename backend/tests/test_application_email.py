"""The "application received" email (functional.md > Candidate applies to a job).

The candidate is emailed through the worker, like every email: the request only queues a job that
holds the application's id; the template builds the words when the job runs.
"""

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.emails import TEMPLATES
from app.models import (
    Application,
    BackgroundJob,
    Company,
    Department,
    Job,
    JobStatus,
    PostingStatus,
    Role,
    User,
)
from app.worker import runner
from app.worker.handlers import HANDLERS
from tests import mailpit
from tests.browser import Browser
from tests.factories import (
    make_application,
    make_candidate,
    make_company,
    make_department,
    make_job,
    make_user,
)


@pytest.fixture(autouse=True)
def mail_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("SMTP_PORT", "1025")
    monkeypatch.setenv("SMTP_STARTTLS", "false")
    monkeypatch.setenv("EMAIL_FROM", "ATS <no-reply@ats.test>")
    monkeypatch.setenv("APP_BASE_URL", "https://ats.test")
    mailpit.clear_inbox()
    yield
    mailpit.clear_inbox()


def setup_application(
    db: Session, *, job_title: str = "Backend Engineer", company_name: str = "Acme"
) -> tuple[Application, User, Job]:
    company: Company = make_company(db, company_name)
    department: Department = make_department(db, company)
    admin = make_user(db, email="admin@acme.test", role=Role.COMPANY_ADMIN, company=company)
    job = make_job(
        db,
        company=company,
        department=department,
        created_by=admin,
        status=PostingStatus.OPEN,
        title=job_title,
    )
    candidate = make_candidate(db, email="cara@example.test", full_name="Cara Candidate")
    application = make_application(db, job=job, candidate=candidate)
    db.commit()
    return application, candidate, job


def render(db: Session, application_id: Any) -> Any:
    template = TEMPLATES["application_received"]
    return template(db, {"template": "application_received", "application_id": str(application_id)})


def test_the_email_goes_to_the_candidate_and_names_the_job_and_company(db: Session) -> None:
    application, candidate, _job = setup_application(db)

    email = render(db, application.id)

    assert email is not None
    assert email.to == candidate.email
    assert "Backend Engineer" in email.subject and "Acme" in email.subject
    assert "Cara Candidate" in email.body
    assert "Backend Engineer" in email.body and "Acme" in email.body


def test_the_email_links_to_the_candidates_own_page(db: Session) -> None:
    application, _candidate, _job = setup_application(db)

    email = render(db, application.id)

    assert email is not None and "https://ats.test/applications" in email.body
    # Nothing in the link identifies the application: it is the candidate's list, behind a login.
    assert str(application.id) not in email.body


def test_names_typed_by_people_cannot_reshape_the_email(db: Session) -> None:
    application, _candidate, _job = setup_application(
        db, job_title="Engineer\r\nBcc: attacker@example.test", company_name="Acme\nCorp"
    )

    email = render(db, application.id)

    assert email is not None
    assert "\n" not in email.subject and "\r" not in email.subject
    assert "Bcc: attacker@example.test" in email.subject  # kept as plain words, on one line


def test_there_is_nothing_to_send_for_an_application_that_does_not_exist(db: Session) -> None:
    assert render(db, uuid.uuid4()) is None


def test_the_whole_chain_delivers_one_email_through_the_worker(
    client: TestClient, db: Session
) -> None:
    _application, candidate, job = setup_application(db)
    # Apply for real, as a second candidate, so the email is queued by the request.
    dan = make_candidate(db, email="dan@example.test", full_name="Dan Candidate")
    db.commit()

    response = Browser(client, db, dan).send(
        "POST", "/api/applications", json={"job_id": str(job.id)}
    )
    assert response.status_code == 201
    while runner.run_one_job(db, HANDLERS):
        pass

    db.expire_all()
    sent = [m for m in mailpit.messages() if "dan@example.test" in str(m["To"])]
    assert len(sent) == 1
    assert "Backend Engineer" in sent[0]["Subject"]
    jobs = list(db.scalars(select(BackgroundJob)))
    assert all(job.status == JobStatus.SUCCEEDED for job in jobs)
    assert candidate.email not in str([m["To"] for m in mailpit.messages()])  # only Dan was told
