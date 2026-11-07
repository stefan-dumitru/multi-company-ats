"""Invitation emails (functional.md > Invite and deactivate staff).

Inviting queues an email in the same transaction as the invitation; the worker sends it later,
rebuilding the link from the invitation's id. These tests run the real chain: request, queue,
worker, a real SMTP server (Mailpit), and then use the link from the delivered mail.
"""

import json
import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BackgroundJob, Invitation, JobStatus, Role
from app.services.invitations import create_invitation
from app.worker import runner
from app.worker.handlers import HANDLERS
from tests import mailpit
from tests.factories import make_company, make_user
from tests.test_invitations import accept, invite, sign_up_company

LINK = re.compile(r"https://ats\.test/accept-invitation\?token=(\S+)")


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


@pytest.fixture
def admin_csrf(client: TestClient, db: Session) -> str:
    return sign_up_company(client, db, "Acme", "admin@acme.test")


def jobs(db: Session) -> list[BackgroundJob]:
    """The invitation emails queued so far (signup and acceptance also queue verification mail)."""
    db.expire_all()
    everything = db.scalars(select(BackgroundJob).order_by(BackgroundJob.created_at))
    return [job for job in everything if job.payload["template"] == "invitation"]


def invitation_messages() -> list[dict[str, Any]]:
    """The invitation emails in the inbox, ignoring verification emails."""
    return [m for m in mailpit.messages() if "accept-invitation" in m["Text"]]


def send_queued_emails(db: Session, at: datetime | None = None) -> None:
    moment = at or datetime.now(UTC) + timedelta(seconds=5)
    while runner.run_one_job(db, HANDLERS, lambda: moment):
        pass


# ---- queueing -----------------------------------------------------------------------------


def test_inviting_queues_one_email_holding_only_ids(
    client: TestClient, db: Session, admin_csrf: str
) -> None:
    body = invite(client, admin_csrf, "rae@acme.test").json()

    (job,) = jobs(db)
    invitation_id = body["invitation"]["id"]
    assert job.type == "send_email"
    assert job.payload == {"template": "invitation", "invitation_id": invitation_id}
    assert job.idempotency_key == f"invitation_email:{invitation_id}"
    # Nothing secret and nothing personal in the queue.
    stored = json.dumps([job.payload, job.last_error, job.idempotency_key])
    assert body["token"] not in stored
    assert "rae@acme.test" not in stored


def test_an_invitation_that_is_refused_queues_no_email(
    client: TestClient, db: Session, admin_csrf: str
) -> None:
    response = invite(client, admin_csrf, "admin@acme.test")  # already has an account

    assert response.status_code == 409
    assert jobs(db) == []


def test_sending_a_new_link_queues_a_new_email(
    client: TestClient, db: Session, admin_csrf: str
) -> None:
    invite(client, admin_csrf, "rae@acme.test")
    invite(client, admin_csrf, "rae@acme.test")

    assert len(jobs(db)) == 2


# ---- delivery -----------------------------------------------------------------------------


def test_the_delivered_link_is_the_one_the_admin_was_shown_and_it_works(
    client: TestClient, db: Session, admin_csrf: str
) -> None:
    body = invite(client, admin_csrf, "rae@acme.test").json()

    send_queued_emails(db)

    (message,) = invitation_messages()
    assert [to["Address"] for to in message["To"]] == ["rae@acme.test"]
    assert "Acme" in message["Subject"]
    match = LINK.search(message["Text"])
    assert match is not None
    assert match.group(1) == body["token"]
    assert accept(client, match.group(1)).status_code == 201  # the emailed link really works


def test_the_email_says_who_invited_to_which_company_and_role_and_until_when(
    client: TestClient, db: Session, admin_csrf: str
) -> None:
    invite(client, admin_csrf, "rae@acme.test", role="interviewer")

    send_queued_emails(db)

    (message,) = invitation_messages()
    assert "Admin of Acme" in message["Text"]
    assert "Acme" in message["Text"]
    assert "interviewer" in message["Text"].lower()
    assert "UTC" in message["Text"]
    assert message["HTML"] == ""


def test_an_invitation_replaced_before_sending_only_emails_the_newest_link(
    client: TestClient, db: Session, admin_csrf: str
) -> None:
    invite(client, admin_csrf, "rae@acme.test")
    newest = invite(client, admin_csrf, "rae@acme.test").json()

    send_queued_emails(db)

    (message,) = invitation_messages()  # the revoked one's email was skipped, not sent
    match = LINK.search(message["Text"])
    assert match is not None and match.group(1) == newest["token"]
    assert all(job.status == JobStatus.SUCCEEDED for job in jobs(db))


def test_an_invitation_accepted_before_the_email_goes_out_sends_nothing(
    client: TestClient, db: Session, admin_csrf: str
) -> None:
    body = invite(client, admin_csrf, "rae@acme.test").json()
    assert accept(client, body["token"]).status_code == 201

    send_queued_emails(db)

    assert invitation_messages() == []


def test_an_invitation_that_expired_before_the_email_goes_out_sends_nothing(
    client: TestClient, db: Session, admin_csrf: str
) -> None:
    invite(client, admin_csrf, "rae@acme.test")
    invitation = db.scalars(select(Invitation)).one()
    invitation.expires_at = datetime.now(UTC) - timedelta(hours=1)
    db.commit()

    send_queued_emails(db)

    assert invitation_messages() == []


def test_a_mail_outage_does_not_undo_the_invitation(
    client: TestClient, db: Session, admin_csrf: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SMTP_PORT", "1")  # nothing listens there
    body = invite(client, admin_csrf, "rae@acme.test").json()

    send_queued_emails(db)

    (job,) = jobs(db)
    assert job.status == JobStatus.PENDING  # will retry
    assert db.scalars(select(Invitation)).one().revoked_at is None
    assert accept(client, body["token"]).status_code == 201  # the shown link works regardless


def test_typed_names_cannot_add_headers_or_markup_to_the_email(db: Session) -> None:
    company = make_company(db, "Evil\nBcc: spy@evil.test <b>Co</b>")
    admin = make_user(
        db, email="admin@evil.test", role=Role.COMPANY_ADMIN, company=company, full_name="A\r\nB"
    )
    create_invitation(db, admin, email="rae@evil.test", role=Role.RECRUITER, now=datetime.now(UTC))
    db.commit()

    send_queued_emails(db)

    (message,) = invitation_messages()
    assert "\n" not in message["Subject"]
    assert message["Bcc"] == []  # the injected "Bcc:" never became a header
    assert [to["Address"] for to in message["To"]] == ["rae@evil.test"]
    assert "<b>Co</b>" in message["Text"]  # shown literally, as plain text
