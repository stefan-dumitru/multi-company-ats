"""The `send_email` job: the worker side of every email the app sends.

The payload names a template and holds ids only. The template looks up whatever it needs
(recipient, names, links) when the worker runs, so nothing private sits in the queue.
"""

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import emails
from app.emails import Email
from app.models import BackgroundJob, JobStatus
from app.worker import queue, runner
from app.worker.handlers import HANDLERS
from tests import mailpit

NOW = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def mail_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    # Independent of the developer's shell: always the local fake mail server.
    monkeypatch.setenv("SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("SMTP_PORT", "1025")
    monkeypatch.setenv("SMTP_STARTTLS", "false")
    monkeypatch.setenv("EMAIL_FROM", "ATS <no-reply@ats.test>")
    monkeypatch.setenv("APP_BASE_URL", "https://ats.test")
    mailpit.clear_inbox()
    yield
    mailpit.clear_inbox()


def welcome(_db: Session, payload: dict[str, str]) -> Email:
    return Email(to="sam@example.test", subject="Welcome", body=f"Hello, {payload['name_id']}.\n")


def queue_email(db: Session, template: str, key: str = "a") -> None:
    queue.enqueue(
        db,
        type="send_email",
        payload={"template": template, "name_id": "42"},
        idempotency_key=key,
        now=NOW,
    )
    db.commit()


def only_job(db: Session) -> BackgroundJob:
    db.expire_all()
    return db.scalars(select(BackgroundJob)).one()


def test_the_worker_knows_how_to_send_email() -> None:
    assert "send_email" in HANDLERS


def test_a_queued_email_is_rendered_and_delivered(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(emails.TEMPLATES, "welcome", welcome)
    queue_email(db, "welcome")

    runner.run_one_job(db, HANDLERS, lambda: NOW)

    assert only_job(db).status == JobStatus.SUCCEEDED
    (received,) = mailpit.messages()
    assert received["Subject"] == "Welcome"
    assert received["Text"].strip() == "Hello, 42."


def test_an_unknown_template_fails_the_job_with_its_name(db: Session) -> None:
    queue_email(db, "does_not_exist")

    runner.run_one_job(db, HANDLERS, lambda: NOW)

    job = only_job(db)
    assert job.status == JobStatus.PENDING
    assert job.last_error is not None and "does_not_exist" in job.last_error
    assert mailpit.messages() == []


def test_a_mail_server_outage_leaves_the_email_to_retry_later(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(emails.TEMPLATES, "welcome", welcome)
    monkeypatch.setenv("SMTP_PORT", "1")  # nothing listens there
    queue_email(db, "welcome")

    runner.run_one_job(db, HANDLERS, lambda: NOW)

    job = only_job(db)
    assert job.status == JobStatus.PENDING
    assert job.attempts == 1
    assert job.last_error is not None


def test_a_mail_outage_that_ends_lets_the_retry_deliver(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(emails.TEMPLATES, "welcome", welcome)
    queue_email(db, "welcome")
    monkeypatch.setenv("SMTP_PORT", "1")
    runner.run_one_job(db, HANDLERS, lambda: NOW)  # fails
    monkeypatch.setenv("SMTP_PORT", "1025")  # the server is back
    later = only_job(db).run_at

    runner.run_one_job(db, HANDLERS, lambda: later)

    assert only_job(db).status == JobStatus.SUCCEEDED
    assert len(mailpit.messages()) == 1


def test_missing_mail_settings_fail_the_job_with_the_setting_named(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(emails.TEMPLATES, "welcome", welcome)
    monkeypatch.delenv("SMTP_HOST")
    queue_email(db, "welcome")

    runner.run_one_job(db, HANDLERS, lambda: NOW)

    job = only_job(db)
    assert job.last_error is not None and "SMTP_HOST" in job.last_error


def test_queueing_the_same_email_twice_sends_it_once(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(emails.TEMPLATES, "welcome", welcome)
    queue_email(db, "welcome", key="same")
    queue_email(db, "welcome", key="same")

    while runner.run_one_job(db, HANDLERS, lambda: NOW):
        pass

    assert len(mailpit.messages()) == 1
