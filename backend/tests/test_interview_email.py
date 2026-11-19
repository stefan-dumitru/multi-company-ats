"""The emails about an interview: to each interviewer and to the candidate, on scheduling and on
cancelling. Like every email they go through the worker; times are always written in UTC."""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
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
    Company,
    Interview,
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
    make_interview,
    make_job,
    make_user,
)

WHEN = datetime(2026, 12, 3, 14, 30, tzinfo=UTC)


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


def setup(
    db: Session, *, job_title: str = "Backend Engineer", round_name: str = "Technical round"
) -> tuple[Interview, Application, User, User, User]:
    company = make_company(db, "Acme")
    admin = make_user(db, email="admin@acme.test", role=Role.COMPANY_ADMIN, company=company)
    recruiter = make_user(db, email="rec@acme.test", role=Role.RECRUITER, company=company)
    ivy = make_user(
        db, email="ivy@acme.test", role=Role.INTERVIEWER, company=company, full_name="Ivy Inman"
    )
    job = make_job(
        db,
        company=company,
        department=make_department(db, company),
        created_by=admin,
        recruiters=[recruiter],
        status=PostingStatus.OPEN,
        title=job_title,
    )
    cara = make_candidate(db, email="cara@example.test", full_name="Cara Candidate")
    application = make_application(db, job=job, candidate=cara, stage=ApplicationStage.INTERVIEW)
    interview = make_interview(
        db,
        application=application,
        scheduled_by=recruiter,
        interviewers=[ivy],
        scheduled_at=WHEN,
        round_name=round_name,
    )
    db.commit()
    return interview, application, recruiter, ivy, cara


def render(db: Session, template: str, interview_id: Any, recipient_id: Any) -> Any:
    payload = {
        "template": template,
        "interview_id": str(interview_id),
        "recipient_id": str(recipient_id),
    }
    return TEMPLATES[template](db, payload)


@pytest.mark.parametrize("template", ["interview_scheduled", "interview_cancelled"])
def test_the_interviewer_is_told_who_when_and_where(db: Session, template: str) -> None:
    interview, _application, _recruiter, ivy, _cara = setup(db)

    email = render(db, template, interview.id, ivy.id)

    assert email is not None and email.to == ivy.email
    text = email.subject + email.body
    assert "Technical round" in text and "Backend Engineer" in text
    assert "Cara Candidate" in text  # the interviewer needs to know who they will meet
    assert "Ivy Inman" in email.body
    assert "2026-12-03 14:30 UTC" in text  # the time, in UTC, and it says so
    assert "60 minutes" in email.body and "Room 4" in email.body
    assert "https://ats.test/interviews" in email.body


@pytest.mark.parametrize("template", ["interview_scheduled", "interview_cancelled"])
def test_the_candidate_is_told_when_and_where_but_not_who_judges_them(
    db: Session, template: str
) -> None:
    interview, _application, _recruiter, ivy, cara = setup(db)

    email = render(db, template, interview.id, cara.id)

    assert email is not None and email.to == cara.email
    text = email.subject + email.body
    assert "Technical round" in text and "Backend Engineer" in text and "Acme" in text
    assert "Cara Candidate" in email.body
    assert "2026-12-03 14:30 UTC" in text and "Room 4" in email.body
    assert "Ivy" not in text and ivy.email not in text  # who the interviewers are stays internal
    assert "https://ats.test/applications" in email.body


def test_scheduled_and_cancelled_emails_say_different_things(db: Session) -> None:
    interview, _application, _recruiter, _ivy, cara = setup(db)

    scheduled = render(db, "interview_scheduled", interview.id, cara.id)
    cancelled = render(db, "interview_cancelled", interview.id, cara.id)

    assert "cancel" in cancelled.subject.lower() and "cancel" not in scheduled.subject.lower()
    assert scheduled.body != cancelled.body


def test_names_typed_by_people_cannot_reshape_the_email(db: Session) -> None:
    interview, _application, _recruiter, ivy, _cara = setup(
        db, job_title="Engineer\r\nBcc: attacker@example.test", round_name="Round\nOne"
    )

    email = render(db, "interview_scheduled", interview.id, ivy.id)

    assert email is not None and "\n" not in email.subject and "\r" not in email.subject


def test_nobody_is_emailed_who_is_not_part_of_the_interview(db: Session) -> None:
    interview, _application, recruiter, _ivy, _cara = setup(db)
    company = db.get(Company, recruiter.company_id)
    assert company is not None
    stranger = make_user(db, email="stranger@acme.test", role=Role.INTERVIEWER, company=company)
    db.commit()

    assert render(db, "interview_scheduled", interview.id, stranger.id) is None
    assert render(db, "interview_scheduled", interview.id, uuid.uuid4()) is None


def test_there_is_nothing_to_send_for_an_interview_that_does_not_exist(db: Session) -> None:
    assert render(db, "interview_scheduled", uuid.uuid4(), uuid.uuid4()) is None
    assert render(db, "interview_cancelled", uuid.uuid4(), uuid.uuid4()) is None


def test_the_whole_chain_delivers_one_email_per_person_through_the_worker(
    client: TestClient, db: Session
) -> None:
    interview, application, recruiter, ivy, cara = setup(db)
    company = db.get(Company, recruiter.company_id)
    assert company is not None
    ian = make_user(
        db, email="ian@acme.test", role=Role.INTERVIEWER, company=company, full_name="Ian Ito"
    )
    db.commit()
    browser = Browser(client, db, recruiter)
    scheduled = browser.send(
        "POST",
        f"/api/applications/{application.id}/interviews",
        json={
            "round_name": "Final round",
            "scheduled_at": "2030-01-15T10:00:00+00:00",
            "duration_minutes": 45,
            "location": "Online",
            "interviewer_ids": [str(ivy.id), str(ian.id)],
        },
    )
    assert scheduled.status_code == 201
    cancelled = browser.send(
        "POST", f"/api/interviews/{scheduled.json()['id']}/cancel", json={"version": 1}
    )
    assert cancelled.status_code == 200
    while runner.run_one_job(db, HANDLERS):
        pass

    db.expire_all()
    inbox = mailpit.messages()
    for address in (ivy.email, ian.email, cara.email):
        mine = [m for m in inbox if address in str(m["To"])]
        assert len(mine) == 2, address  # scheduled, then cancelled
    assert all(job.status == JobStatus.SUCCEEDED for job in db.scalars(select(BackgroundJob)))
