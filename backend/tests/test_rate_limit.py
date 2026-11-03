"""Login rate limiting (security.md): 5 failures per email and 20 per IP in 15 minutes."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.rate_limit import clear_failures, is_locked_out, record_failure

NOW = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)


def fail_times(
    db: Session, count: int, *, email: str = "a@example.com", ip: str = "1.1.1.1"
) -> None:
    for _ in range(count):
        record_failure(db, email, ip, NOW)
    db.flush()


def test_five_failures_are_allowed_and_the_sixth_attempt_is_refused(db: Session) -> None:
    fail_times(db, 4)
    assert is_locked_out(db, "a@example.com", "1.1.1.1", NOW) is False

    fail_times(db, 1)
    assert is_locked_out(db, "a@example.com", "1.1.1.1", NOW) is True


def test_the_lockout_ends_after_15_minutes(db: Session) -> None:
    fail_times(db, 5)

    assert is_locked_out(db, "a@example.com", "1.1.1.1", NOW + timedelta(minutes=14)) is True
    assert is_locked_out(db, "a@example.com", "1.1.1.1", NOW + timedelta(minutes=16)) is False


def test_the_email_is_compared_ignoring_case_and_spaces(db: Session) -> None:
    fail_times(db, 5, email="Ada@Example.com")

    assert is_locked_out(db, " ada@example.com ", "9.9.9.9", NOW) is True


def test_one_lockout_does_not_affect_other_addresses(db: Session) -> None:
    fail_times(db, 5, email="a@example.com", ip="1.1.1.1")

    assert is_locked_out(db, "someone-else@example.com", "2.2.2.2", NOW) is False


def test_an_ip_is_locked_out_after_20_failures_across_different_emails(db: Session) -> None:
    for number in range(19):
        record_failure(db, f"user{number}@example.com", "3.3.3.3", NOW)
    db.flush()
    assert is_locked_out(db, "fresh@example.com", "3.3.3.3", NOW) is False

    record_failure(db, "user19@example.com", "3.3.3.3", NOW)
    db.flush()
    assert is_locked_out(db, "fresh@example.com", "3.3.3.3", NOW) is True


def test_a_successful_login_clears_that_emails_failures(db: Session) -> None:
    fail_times(db, 4)

    clear_failures(db, "a@example.com")
    fail_times(db, 1)

    assert is_locked_out(db, "a@example.com", "1.1.1.1", NOW) is False


def test_the_database_never_stores_the_email_itself(db: Session) -> None:
    fail_times(db, 1, email="secret.person@example.com")

    stored = db.execute(text("SELECT email_hash FROM login_attempts")).scalar()
    assert stored is not None
    assert "secret" not in stored
