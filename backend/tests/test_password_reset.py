"""Password reset (functional.md > Reset a forgotten password; security.md > Authentication).

Rules under test: asking for a link never reveals whether an address has an account; a link is
signed, single-use, expires after an hour and is limited to 3 per hour per user; a successful reset
logs the user out everywhere, voids other links, clears the login lockout and is audited without
secrets; and a weak password never burns the link.
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
from app.auth.passwords import verify_password
from app.auth.rate_limit import MAX_FAILURES_PER_EMAIL, record_failure
from app.auth.sessions import SESSION_COOKIE_NAME, create_session
from app.models import AuditLog, BackgroundJob, JobStatus, Role, User, UserToken
from app.services import password_reset
from app.worker import runner
from app.worker.handlers import HANDLERS
from tests import mailpit
from tests.factories import DEFAULT_PASSWORD, make_company, make_user

LINK = re.compile(r"https://ats\.test/reset-password\?token=(\S+)")
EMAIL = "ada@acme.test"
NEW_PASSWORD = "a brand new passphrase"
ANSWER = {
    "detail": "If an account exists for that address, we have sent a link to reset the password."
}


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
def ada(db: Session) -> User:
    user = make_user(
        db,
        email=EMAIL,
        role=Role.COMPANY_ADMIN,
        company=make_company(db),
        full_name="Ada Admin",
        password=DEFAULT_PASSWORD,
    )
    db.commit()
    return user


def forgot(client: TestClient, email: str = EMAIL):  # noqa: ANN201
    return client.post("/api/auth/forgot-password", json={"email": email})


def reset(client: TestClient, token: str, password: str = NEW_PASSWORD):  # noqa: ANN201
    return client.post("/api/auth/reset-password", json={"token": token, "password": password})


def reset_tokens(db: Session) -> list[UserToken]:
    db.expire_all()
    rows = db.scalars(select(UserToken).order_by(UserToken.created_at))
    return [row for row in rows if row.type == tokens.PASSWORD_RESET]


def jobs(db: Session, template: str) -> list[BackgroundJob]:
    db.expire_all()
    rows = db.scalars(select(BackgroundJob).order_by(BackgroundJob.created_at))
    return [job for job in rows if job.payload.get("template") == template]


def deliver_queued_emails(db: Session) -> None:
    moment = datetime.now(UTC) + timedelta(seconds=5)
    while runner.run_one_job(db, HANDLERS, lambda: moment):
        pass


def reset_messages() -> list[dict]:  # type: ignore[type-arg]
    return [m for m in mailpit.messages() if LINK.search(m["Text"])]


def emailed_token() -> str:
    match = LINK.search(reset_messages()[-1]["Text"])
    assert match is not None
    return match.group(1)


def log_in(client: TestClient, password: str = DEFAULT_PASSWORD, email: str = EMAIL):  # noqa: ANN201
    return client.post("/api/auth/login", json={"email": email, "password": password})


# ---- asking for a link --------------------------------------------------------------------


def test_the_answer_is_identical_for_unknown_known_and_deactivated_addresses(
    client: TestClient, db: Session, ada: User
) -> None:
    gone = make_user(db, email="gone@acme.test", role=Role.RECRUITER, company=make_company(db))
    gone.is_active = False
    db.commit()

    responses = [forgot(client, e) for e in ("nobody@acme.test", EMAIL, "gone@acme.test")]

    assert [r.status_code for r in responses] == [202, 202, 202]
    assert all(r.json() == ANSWER for r in responses)
    assert len({r.text for r in responses}) == 1  # byte for byte


def test_only_a_known_active_account_gets_a_link_and_one_queued_email(
    client: TestClient, db: Session, ada: User
) -> None:
    gone = make_user(db, email="gone@acme.test", role=Role.RECRUITER, company=make_company(db))
    gone.is_active = False
    db.commit()

    for address in ("nobody@acme.test", "gone@acme.test", EMAIL):
        forgot(client, address)

    (row,) = reset_tokens(db)
    assert row.user_id == ada.id
    assert row.expires_at - row.created_at == timedelta(hours=1)
    (job,) = jobs(db, "reset_password")
    assert job.payload == {"template": "reset_password", "user_token_id": str(row.id)}
    assert job.idempotency_key == f"password_reset:{row.id}"
    assert EMAIL not in json.dumps([job.payload, job.idempotency_key])  # ids only in the queue


def test_the_address_is_matched_ignoring_case_and_spaces(
    client: TestClient, db: Session, ada: User
) -> None:
    forgot(client, "  ADA@Acme.Test ")

    assert len(reset_tokens(db)) == 1


def test_a_malformed_address_is_a_validation_error_not_a_hint(client: TestClient) -> None:
    assert forgot(client, "not-an-address").status_code == 422


def test_candidates_and_unverified_users_can_reset_too(client: TestClient, db: Session) -> None:
    make_user(db, email="cand@x.test", role=Role.CANDIDATE, company=None, verified=False)
    db.commit()

    forgot(client, "cand@x.test")

    assert len(reset_tokens(db)) == 1


def test_at_most_three_links_per_hour_and_the_answer_does_not_change(
    client: TestClient, db: Session, ada: User
) -> None:
    answers = [forgot(client).json() for _ in range(5)]

    assert all(a == ANSWER for a in answers)  # the limit cannot be used to probe
    assert len(reset_tokens(db)) == 3
    assert len(jobs(db, "reset_password")) == 3


def test_the_limit_lifts_after_an_hour(client: TestClient, db: Session, ada: User) -> None:
    for _ in range(3):
        forgot(client)
    for row in reset_tokens(db):
        row.created_at = datetime.now(UTC) - timedelta(hours=1, minutes=1)
    db.commit()

    forgot(client)

    assert len(reset_tokens(db)) == 4


def test_asking_again_replaces_the_link_so_only_the_newest_works(
    client: TestClient, db: Session, ada: User
) -> None:
    forgot(client)
    deliver_queued_emails(db)
    old = emailed_token()
    mailpit.clear_inbox()
    forgot(client)
    deliver_queued_emails(db)

    assert reset(client, old).status_code == 400
    assert reset(client, emailed_token()).status_code == 204


# ---- the email ----------------------------------------------------------------------------


def test_the_email_has_the_link_the_deadline_and_what_to_do_if_it_was_not_you(
    client: TestClient, db: Session, ada: User
) -> None:
    forgot(client)

    deliver_queued_emails(db)

    (message,) = reset_messages()
    assert [to["Address"] for to in message["To"]] == [EMAIL]
    assert message["HTML"] == ""
    assert "1 hour" in message["Text"]
    assert "ignore this email" in message["Text"].lower()
    assert "Ada Admin" in message["Text"]


def test_no_email_goes_out_for_a_link_that_is_no_longer_good(
    client: TestClient, db: Session, ada: User
) -> None:
    forgot(client)
    (row,) = reset_tokens(db)
    row.used_at = datetime.now(UTC)  # used or replaced before the worker got to it
    db.commit()

    deliver_queued_emails(db)

    assert reset_messages() == []
    assert all(job.status == JobStatus.SUCCEEDED for job in jobs(db, "reset_password"))


def test_no_email_goes_out_for_an_account_deactivated_in_the_meantime(
    client: TestClient, db: Session, ada: User
) -> None:
    forgot(client)
    ada.is_active = False
    db.commit()

    deliver_queued_emails(db)

    assert reset_messages() == []


# ---- using the link -----------------------------------------------------------------------


def test_the_whole_story_request_email_new_password_login(
    client: TestClient, db: Session, ada: User
) -> None:
    forgot(client)
    deliver_queued_emails(db)

    response = reset(client, emailed_token())

    assert response.status_code == 204
    assert SESSION_COOKIE_NAME not in response.headers.get("set-cookie", "")  # no login by link
    assert log_in(client, NEW_PASSWORD).status_code == 200
    client.cookies.clear()
    assert log_in(client, DEFAULT_PASSWORD).status_code == 401


def test_the_new_password_is_stored_hashed_never_as_text(
    client: TestClient, db: Session, ada: User
) -> None:
    forgot(client)
    deliver_queued_emails(db)

    reset(client, emailed_token())

    db.refresh(ada)
    assert ada.password_hash is not None
    assert ada.password_hash.startswith("$argon2")
    assert NEW_PASSWORD not in ada.password_hash
    assert verify_password(ada.password_hash, NEW_PASSWORD)


def test_a_weak_password_is_refused_and_the_link_stays_usable(
    client: TestClient, db: Session, ada: User
) -> None:
    forgot(client)
    deliver_queued_emails(db)
    token = emailed_token()

    assert reset(client, token, "short").status_code == 422
    assert reset(client, token, NEW_PASSWORD).status_code == 204


def test_a_link_works_only_once(client: TestClient, db: Session, ada: User) -> None:
    forgot(client)
    deliver_queued_emails(db)
    token = emailed_token()

    assert reset(client, token).status_code == 204
    assert reset(client, token, "another new passphrase").status_code == 400


def test_an_expired_link_is_refused_and_changes_nothing(
    client: TestClient, db: Session, ada: User
) -> None:
    forgot(client)
    deliver_queued_emails(db)
    (row,) = reset_tokens(db)
    row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()

    assert reset(client, emailed_token()).status_code == 400
    assert log_in(client, DEFAULT_PASSWORD).status_code == 200  # the old password still works


def test_forged_misdirected_and_unknown_links_get_one_identical_refusal(
    client: TestClient, db: Session, ada: User
) -> None:
    forgot(client)
    (row,) = reset_tokens(db)
    attempts = [
        f"{row.id}.{'0' * 64}",  # right row, not signed by us
        tokens.make_token(tokens.EMAIL_VERIFICATION, row.id),  # signed, but for another purpose
        tokens.make_token(tokens.PASSWORD_RESET, uuid.uuid4()),  # signed, but no such row
        "garbage",
    ]

    responses = [reset(client, attempt) for attempt in attempts]

    assert [r.status_code for r in responses] == [400] * 4
    assert len({r.text for r in responses}) == 1


def test_a_deactivated_account_cannot_be_reset_and_keeps_its_password(
    client: TestClient, db: Session, ada: User
) -> None:
    forgot(client)
    deliver_queued_emails(db)
    token = emailed_token()
    ada.is_active = False
    db.commit()

    assert reset(client, token).status_code == 400
    db.refresh(ada)
    assert ada.password_hash is not None
    assert verify_password(ada.password_hash, DEFAULT_PASSWORD)


def test_everyone_is_logged_out_everywhere(client: TestClient, db: Session, ada: User) -> None:
    cookie, _ = create_session(db, ada, datetime.now(UTC))
    db.commit()
    client.cookies.set(SESSION_COOKIE_NAME, cookie)
    assert client.get("/api/auth/me").status_code == 200
    forgot(client)
    deliver_queued_emails(db)

    reset(client, emailed_token())

    assert client.get("/api/auth/me").status_code == 401  # a thief's session dies with the password


def test_other_unused_links_stop_working(client: TestClient, db: Session, ada: User) -> None:
    # Two live links can only exist if one was created without voiding the other; the reset must
    # still kill whatever is left.
    now = datetime.now(UTC)
    first = password_reset.issue_reset_link(db, ada, now)
    db.commit()
    other = UserTokenFactory.second_link(db, ada, now)

    assert reset(client, tokens.make_token(tokens.PASSWORD_RESET, first.id)).status_code == 204
    assert (
        reset(
            client, tokens.make_token(tokens.PASSWORD_RESET, other.id), "yet another one!!"
        ).status_code
        == 400
    )


def test_earlier_failed_logins_no_longer_lock_the_account(
    client: TestClient, db: Session, ada: User
) -> None:
    for _ in range(MAX_FAILURES_PER_EMAIL):
        record_failure(db, EMAIL, "203.0.113.9", datetime.now(UTC))
    db.commit()
    assert log_in(client).status_code == 429
    forgot(client)
    deliver_queued_emails(db)

    reset(client, emailed_token())

    assert log_in(client, NEW_PASSWORD).status_code == 200


def test_opening_the_link_proves_the_inbox_so_the_address_counts_as_verified(
    client: TestClient, db: Session
) -> None:
    user = make_user(
        db,
        email=EMAIL,
        role=Role.COMPANY_ADMIN,
        company=make_company(db),
        password=DEFAULT_PASSWORD,
        verified=False,
    )
    db.commit()
    forgot(client)
    deliver_queued_emails(db)

    reset(client, emailed_token())

    db.refresh(user)
    assert user.email_verified_at is not None


def test_the_reset_is_audited_without_any_secret(
    client: TestClient, db: Session, ada: User
) -> None:
    forgot(client)
    deliver_queued_emails(db)
    token = emailed_token()

    reset(client, token)

    (entry,) = db.scalars(select(AuditLog).where(AuditLog.action == "password_reset")).all()
    assert entry.entity_type == "user"
    assert entry.entity_id == ada.id
    assert entry.actor_user_id == ada.id
    assert entry.company_id == ada.company_id
    shown = json.dumps([entry.old_value, entry.new_value])
    assert NEW_PASSWORD not in shown and token not in shown


def test_a_candidate_with_no_company_is_audited_too(client: TestClient, db: Session) -> None:
    user = make_user(
        db, email="cand@x.test", role=Role.CANDIDATE, company=None, password=DEFAULT_PASSWORD
    )
    db.commit()
    forgot(client, "cand@x.test")
    deliver_queued_emails(db)

    reset(client, emailed_token())

    entry = db.scalars(select(AuditLog).where(AuditLog.action == "password_reset")).one()
    assert entry.actor_user_id == user.id and entry.company_id is None


def test_two_simultaneous_uses_of_one_link_succeed_only_once(
    client: TestClient, db: Session, ada: User, scratch_engine: Engine
) -> None:
    forgot(client)
    (row,) = reset_tokens(db)
    token = tokens.make_token(tokens.PASSWORD_RESET, row.id)
    outcomes: list[bool] = []
    lock = threading.Lock()
    start_together = threading.Barrier(2)

    def use_the_link() -> None:
        with Session(scratch_engine) as session:
            start_together.wait()
            worked = password_reset.reset_password(session, token, NEW_PASSWORD, datetime.now(UTC))
            if worked:
                session.commit()
            else:
                session.rollback()
            with lock:
                outcomes.append(worked)

    threads = [threading.Thread(target=use_the_link) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert sorted(outcomes) == [False, True]


# ---- the "your password was changed" notice ------------------------------------------------


def test_the_owner_is_told_their_password_was_changed(
    client: TestClient, db: Session, ada: User
) -> None:
    forgot(client)
    deliver_queued_emails(db)
    token = emailed_token()
    mailpit.clear_inbox()

    reset(client, token)
    deliver_queued_emails(db)

    (message,) = mailpit.messages()
    assert [to["Address"] for to in message["To"]] == [EMAIL]
    assert "password was changed" in message["Text"].lower()
    assert "UTC" in message["Text"]
    assert token not in message["Text"]  # the notice carries no link to act on
    assert message["HTML"] == ""


def test_a_failed_reset_sends_no_notice(client: TestClient, db: Session, ada: User) -> None:
    reset(client, "garbage")

    deliver_queued_emails(db)

    assert jobs(db, "password_changed") == []


class UserTokenFactory:
    """Makes a second live reset link by hand, which the normal flow never leaves behind."""

    @staticmethod
    def second_link(db: Session, user: User, now: datetime) -> UserToken:
        link = UserToken(
            user_id=user.id,
            type=tokens.PASSWORD_RESET,
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )
        db.add(link)
        db.commit()
        return link
