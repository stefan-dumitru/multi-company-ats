"""The emails a candidate gets when their application moves or is rejected.

Like every email these go through the worker: the request queues a job holding ids and the stage;
the template builds the words when the job runs.
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
    ApplicationStage,
    BackgroundJob,
    JobStatus,
    PostingStatus,
    RejectionReason,
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


def setup(db: Session, title: str = "Backend Engineer") -> tuple[Application, User, User]:
    company = make_company(db, "Acme")
    admin = make_user(db, email="admin@acme.test", role=Role.COMPANY_ADMIN, company=company)
    recruiter = make_user(db, email="rec@acme.test", role=Role.RECRUITER, company=company)
    job = make_job(
        db,
        company=company,
        department=make_department(db, company),
        created_by=admin,
        recruiters=[recruiter],
        status=PostingStatus.OPEN,
        title=title,
    )
    candidate = make_candidate(db, email="cara@example.test", full_name="Cara Candidate")
    application = make_application(db, job=job, candidate=candidate)
    db.commit()
    return application, candidate, recruiter


def render(db: Session, template: str, application_id: Any, **extra: str) -> Any:
    payload = {"template": template, "application_id": str(application_id), **extra}
    return TEMPLATES[template](db, payload)


@pytest.mark.parametrize("stage", ["screening", "interview", "offer", "hired"])
def test_the_stage_email_goes_to_the_candidate_and_names_the_job_and_company(
    db: Session, stage: str
) -> None:
    application, candidate, _ = setup(db)

    email = render(db, "application_stage_changed", application.id, stage=stage)

    assert email is not None and email.to == candidate.email
    assert "Backend Engineer" in email.subject and "Acme" in email.subject
    assert "Cara Candidate" in email.body and "Backend Engineer" in email.body
    assert "https://ats.test/applications" in email.body


def test_each_stage_has_its_own_words(db: Session) -> None:
    application, _, _ = setup(db)

    bodies = {
        stage: render(db, "application_stage_changed", application.id, stage=stage).body
        for stage in ("screening", "interview", "offer", "hired")
    }

    assert len(set(bodies.values())) == 4


def test_the_stage_email_has_nothing_to_say_for_a_stage_that_is_not_a_milestone(
    db: Session,
) -> None:
    application, _, _ = setup(db)

    assert render(db, "application_stage_changed", application.id, stage="applied") is None
    assert render(db, "application_stage_changed", application.id, stage="nonsense") is None


def test_the_rejection_email_is_kind_and_gives_no_reason(db: Session) -> None:
    application, candidate, _ = setup(db)
    application.stage = ApplicationStage.REJECTED
    application.rejected_from_stage = ApplicationStage.INTERVIEW
    application.rejection_reason = RejectionReason.FAILED_INTERVIEW
    application.rejection_comment = "Internal: seemed arrogant"
    db.commit()

    email = render(db, "application_rejected", application.id)

    assert email is not None and email.to == candidate.email
    assert "Backend Engineer" in email.subject and "Acme" in email.subject
    text = email.subject + email.body
    assert "arrogant" not in text and "interview" not in text.lower()
    for reason in RejectionReason:
        assert reason.value not in text


def test_names_typed_by_people_cannot_reshape_the_email(db: Session) -> None:
    application, _, _ = setup(db, title="Engineer\r\nBcc: attacker@example.test")

    email = render(db, "application_stage_changed", application.id, stage="offer")

    assert email is not None and "\n" not in email.subject and "\r" not in email.subject


def test_there_is_nothing_to_send_for_an_application_that_does_not_exist(db: Session) -> None:
    assert render(db, "application_stage_changed", uuid.uuid4(), stage="offer") is None
    assert render(db, "application_rejected", uuid.uuid4()) is None


def test_the_whole_chain_delivers_one_email_per_change_through_the_worker(
    client: TestClient, db: Session
) -> None:
    application, candidate, recruiter = setup(db)
    browser = Browser(client, db, recruiter)
    moved = browser.send("POST", f"/api/applications/{application.id}/advance", json={"version": 1})
    rejected = browser.send(
        "POST",
        f"/api/applications/{application.id}/reject",
        json={"version": 2, "reason": "position_filled"},
    )
    assert moved.status_code == 200 and rejected.status_code == 200
    while runner.run_one_job(db, HANDLERS):
        pass

    db.expire_all()
    sent = [m for m in mailpit.messages() if candidate.email in str(m["To"])]
    assert len(sent) == 2
    assert all(job.status == JobStatus.SUCCEEDED for job in db.scalars(select(BackgroundJob)))
