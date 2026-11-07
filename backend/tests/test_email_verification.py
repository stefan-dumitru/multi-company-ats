"""Email verification (functional.md > Company signup and onboarding; security.md > Authentication).

Signing up (or accepting an invitation) queues a verification email in the same transaction. The
emailed link is signed, single-use and expires after 24 hours. These tests run the real chain:
request, queue, worker, a real SMTP server (Mailpit), and then use the link from the mail.
"""

import json
import re
import threading
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.auth import tokens
from app.models import BackgroundJob, JobStatus, User, UserToken
from app.services import email_verification
from app.worker import runner
from app.worker.handlers import HANDLERS
from tests import mailpit
from tests.factories import DEFAULT_PASSWORD
from tests.test_invitations import accept, invite

LINK = re.compile(r"https://ats\.test/verify-email\?token=(\S+)")
EMAIL = "ada@acme.test"


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


def sign_up(client: TestClient, email: str = EMAIL) -> str:
    """Register a company; the client is logged in as its (unverified) admin. Returns CSRF."""
    response = client.post(
        "/api/companies",
        json={
            "company_name": "Acme",
            "full_name": "Ada Admin",
            "email": email,
            "password": DEFAULT_PASSWORD,
        },
    )
    assert response.status_code == 201
    return str(response.json()["csrf_token"])


def verification_tokens(db: Session) -> list[UserToken]:
    db.expire_all()
    return list(db.scalars(select(UserToken).order_by(UserToken.created_at)))


def jobs(db: Session) -> list[BackgroundJob]:
    db.expire_all()
    return list(db.scalars(select(BackgroundJob).order_by(BackgroundJob.created_at)))


def deliver_queued_emails(db: Session) -> None:
    moment = datetime.now(UTC) + timedelta(seconds=5)
    while runner.run_one_job(db, HANDLERS, lambda: moment):
        pass


def emailed_token() -> str:
    """The token in the newest verification email in the inbox."""
    for message in reversed(mailpit.messages()):
        match = LINK.search(message["Text"])
        if match:
            return match.group(1)
    raise AssertionError("no verification email in the inbox")


def verify(client: TestClient, token: str) -> int:
    return client.post("/api/auth/verify-email", json={"token": token}).status_code


def the_user(db: Session) -> User:
    db.expire_all()
    return db.scalars(select(User).where(User.email == EMAIL)).one()


# ---- signing up queues the email ----------------------------------------------------------


def test_a_new_admin_starts_unverified_and_one_verification_email_is_queued(
    client: TestClient, db: Session
) -> None:
    body = client.post(
        "/api/companies",
        json={
            "company_name": "Acme",
            "full_name": "Ada Admin",
            "email": EMAIL,
            "password": DEFAULT_PASSWORD,
        },
    ).json()

    assert body["user"]["email_verified_at"] is None
    (token_row,) = verification_tokens(db)
    assert token_row.type == tokens.EMAIL_VERIFICATION
    assert token_row.used_at is None
    assert token_row.expires_at - token_row.created_at == timedelta(hours=24)
    (job,) = jobs(db)
    assert job.type == "send_email"
    assert job.payload == {"template": "verify_email", "user_token_id": str(token_row.id)}
    assert job.idempotency_key == f"verify_email:{token_row.id}"
    stored = json.dumps([job.payload, job.idempotency_key])
    assert EMAIL not in stored  # the queue holds ids only


def test_a_signup_that_fails_queues_nothing(client: TestClient, db: Session) -> None:
    sign_up(client)
    client.cookies.clear()
    jobs_before = len(jobs(db))

    second = client.post(
        "/api/companies",
        json={
            "company_name": "Other",
            "full_name": "Ada Again",
            "email": EMAIL,
            "password": DEFAULT_PASSWORD,
        },
    )

    assert second.status_code == 400
    assert len(jobs(db)) == jobs_before
    assert len(verification_tokens(db)) == 1


# ---- the email and the link ---------------------------------------------------------------


def test_the_emailed_link_verifies_the_address_and_works_without_logging_in(
    client: TestClient, db: Session
) -> None:
    sign_up(client)
    deliver_queued_emails(db)
    (message,) = mailpit.messages()
    assert [to["Address"] for to in message["To"]] == [EMAIL]
    assert message["HTML"] == ""
    assert "24 hours" in message["Text"]
    assert "Ada Admin" in message["Text"]

    client.cookies.clear()  # clicking the link in a different browser than the one that signed up

    assert verify(client, emailed_token()) == 204
    assert the_user(db).email_verified_at is not None


def test_once_verified_the_session_that_signed_up_shows_it(client: TestClient, db: Session) -> None:
    sign_up(client)
    deliver_queued_emails(db)

    verify(client, emailed_token())

    assert client.get("/api/auth/me").json()["user"]["email_verified_at"] is not None


def test_a_link_works_only_once(client: TestClient, db: Session) -> None:
    sign_up(client)
    deliver_queued_emails(db)
    token = emailed_token()

    assert verify(client, token) == 204
    assert verify(client, token) == 400


def test_an_expired_link_is_refused_and_leaves_the_address_unverified(
    client: TestClient, db: Session
) -> None:
    sign_up(client)
    deliver_queued_emails(db)
    (row,) = verification_tokens(db)
    row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()

    assert verify(client, emailed_token()) == 400
    assert the_user(db).email_verified_at is None


def test_forged_and_misdirected_links_get_the_same_generic_refusal(
    client: TestClient, db: Session
) -> None:
    sign_up(client)
    (row,) = verification_tokens(db)
    attempts = [
        f"{row.id}.{'0' * 64}",  # right row, not signed by us
        tokens.make_token(tokens.PASSWORD_RESET, row.id),  # signed, but for another purpose
        tokens.make_token(tokens.EMAIL_VERIFICATION, uuid.uuid4()),  # signed, but no such row
        "garbage",
    ]

    responses = [
        client.post("/api/auth/verify-email", json={"token": attempt}) for attempt in attempts
    ]

    assert [r.status_code for r in responses] == [400] * 4
    assert len({r.text for r in responses}) == 1  # nothing tells the cases apart
    assert the_user(db).email_verified_at is None


def test_verifying_again_later_keeps_the_original_time(client: TestClient, db: Session) -> None:
    sign_up(client)
    deliver_queued_emails(db)
    first = emailed_token()
    verify(client, first)
    original = the_user(db).email_verified_at

    # A second, unused link (from a resend made before the first was clicked) still works but
    # must not rewrite the moment the address was proven.
    user = the_user(db)
    extra = email_verification.issue_verification_email(db, user, datetime.now(UTC))
    db.commit()
    assert verify(client, tokens.make_token(tokens.EMAIL_VERIFICATION, extra.id)) == 204

    assert the_user(db).email_verified_at == original


def test_two_simultaneous_uses_of_one_link_succeed_only_once(
    client: TestClient, db: Session, scratch_engine: Engine
) -> None:
    sign_up(client)
    (row,) = verification_tokens(db)
    outcomes: list[bool] = []
    outcomes_lock = threading.Lock()
    start_together = threading.Barrier(2)

    def use_the_link() -> None:
        with Session(scratch_engine) as session:
            start_together.wait()
            worked = email_verification.confirm_email(
                session, tokens.make_token(tokens.EMAIL_VERIFICATION, row.id), datetime.now(UTC)
            )
            session.commit()
            with outcomes_lock:
                outcomes.append(worked)

    threads = [threading.Thread(target=use_the_link) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sorted(outcomes) == [False, True]


# ---- sending the link again ---------------------------------------------------------------


def test_resending_replaces_the_link_and_only_the_newest_works(
    client: TestClient, db: Session
) -> None:
    csrf = sign_up(client)
    deliver_queued_emails(db)
    old = emailed_token()
    mailpit.clear_inbox()

    response = client.post("/api/auth/resend-verification", headers={"X-CSRF-Token": csrf})
    deliver_queued_emails(db)

    assert response.status_code == 204
    new = emailed_token()
    assert new != old
    assert verify(client, old) == 400
    assert verify(client, new) == 204


def test_resending_to_an_already_verified_account_does_nothing(
    client: TestClient, db: Session
) -> None:
    csrf = sign_up(client)
    deliver_queued_emails(db)
    verify(client, emailed_token())
    jobs_before = len(jobs(db))

    response = client.post("/api/auth/resend-verification", headers={"X-CSRF-Token": csrf})

    assert response.status_code == 204
    assert len(jobs(db)) == jobs_before
    assert len(verification_tokens(db)) == 1


def test_at_most_three_links_per_hour_so_nobody_can_flood_an_inbox(
    client: TestClient, db: Session
) -> None:
    csrf = sign_up(client)  # link 1
    headers = {"X-CSRF-Token": csrf}

    assert client.post("/api/auth/resend-verification", headers=headers).status_code == 204  # 2
    assert client.post("/api/auth/resend-verification", headers=headers).status_code == 204  # 3
    refused = client.post("/api/auth/resend-verification", headers=headers)

    assert refused.status_code == 429
    assert "try again" in refused.json()["detail"].lower()
    assert len(verification_tokens(db)) == 3  # the refused request created nothing
    assert len(jobs(db)) == 3


def test_the_limit_lifts_after_an_hour(client: TestClient, db: Session) -> None:
    csrf = sign_up(client)
    headers = {"X-CSRF-Token": csrf}
    client.post("/api/auth/resend-verification", headers=headers)
    client.post("/api/auth/resend-verification", headers=headers)
    for row in verification_tokens(db):
        row.created_at = datetime.now(UTC) - timedelta(hours=1, minutes=1)
    db.commit()

    assert client.post("/api/auth/resend-verification", headers=headers).status_code == 204


def test_resending_needs_a_login(client: TestClient) -> None:
    assert client.post("/api/auth/resend-verification").status_code == 401


def test_resending_needs_the_csrf_token(client: TestClient) -> None:
    sign_up(client)

    assert client.post("/api/auth/resend-verification").status_code == 403


# ---- invited staff verify too -------------------------------------------------------------


def test_an_invited_user_starts_unverified_and_gets_a_verification_email(
    client: TestClient, db: Session
) -> None:
    csrf = sign_up(client)
    # Verify the admin so they may invite.
    deliver_queued_emails(db)
    verify(client, emailed_token())
    mailpit.clear_inbox()
    invitation = invite(client, csrf, "rae@acme.test").json()
    deliver_queued_emails(db)  # sends the invitation email

    response = accept(client, invitation["token"])
    deliver_queued_emails(db)  # sends the verification email

    assert response.status_code == 201
    assert response.json()["user"]["email_verified_at"] is None
    templates = [job.payload["template"] for job in jobs(db)]
    assert templates.count("verify_email") == 2  # the admin's and the invitee's
    last = mailpit.messages()[-1]
    assert [to["Address"] for to in last["To"]] == ["rae@acme.test"]
    assert LINK.search(last["Text"]) is not None


# ---- the email is skipped when it no longer makes sense ------------------------------------


def test_no_email_is_sent_for_an_address_that_got_verified_in_the_meantime(
    client: TestClient, db: Session
) -> None:
    sign_up(client)
    (row,) = verification_tokens(db)
    user = the_user(db)
    user.email_verified_at = datetime.now(UTC)  # e.g. verified through a different link
    db.commit()

    deliver_queued_emails(db)

    assert mailpit.messages() == []
    assert all(job.status == JobStatus.SUCCEEDED for job in jobs(db))
    assert row.used_at is None


def test_no_email_is_sent_for_a_link_that_was_replaced_before_it_went_out(
    client: TestClient, db: Session
) -> None:
    csrf = sign_up(client)
    client.post("/api/auth/resend-verification", headers={"X-CSRF-Token": csrf})

    deliver_queued_emails(db)

    (message,) = mailpit.messages()  # only the newest link is mailed
    assert emailed_token() == LINK.search(message["Text"]).group(1)  # type: ignore[union-attr]
    newest = verification_tokens(db)[-1]
    assert tokens.read_token(tokens.EMAIL_VERIFICATION, emailed_token()) == newest.id
