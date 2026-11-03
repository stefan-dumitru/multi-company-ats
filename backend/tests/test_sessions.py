"""Session rules (security.md): hashed ids, sliding idle timeout, absolute lifetime, revocation.

Time is passed in rather than read from the clock, so these tests never sleep.
"""

import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.auth.sessions import (
    create_session,
    find_valid_session,
    revoke_all_sessions,
    revoke_session,
)
from app.models import Role, User, UserSession
from tests.factories import make_company, make_user

START = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)


def staff_user(db: Session) -> User:
    company = make_company(db)
    return make_user(db, email="rec@example.com", role=Role.RECRUITER, company=company)


def candidate_user(db: Session) -> User:
    return make_user(db, email="cand@example.com", role=Role.CANDIDATE, company=None)


def test_the_database_stores_only_a_hash_of_the_cookie_value(db: Session) -> None:
    user = staff_user(db)

    token, session = create_session(db, user, START)

    assert session.id == hashlib.sha256(token.encode()).hexdigest()
    assert token not in (session.id, session.csrf_token)
    assert session.csrf_token != token


def test_every_session_gets_its_own_random_token(db: Session) -> None:
    user = staff_user(db)

    first, _ = create_session(db, user, START)
    second, _ = create_session(db, user, START)

    assert first != second


def test_a_fresh_session_is_found(db: Session) -> None:
    user = staff_user(db)
    token, _ = create_session(db, user, START)

    found = find_valid_session(db, token, START + timedelta(minutes=1))

    assert found is not None
    assert found.user_id == user.id


def test_an_unknown_or_empty_token_finds_nothing(db: Session) -> None:
    assert find_valid_session(db, "no-such-token", START) is None
    assert find_valid_session(db, "", START) is None


def test_staff_are_logged_out_after_30_idle_minutes(db: Session) -> None:
    user = staff_user(db)
    # Two sessions, because merely checking one counts as activity and would restart its timer.
    just_inside, _ = create_session(db, user, START)
    just_outside, _ = create_session(db, user, START)

    assert find_valid_session(db, just_inside, START + timedelta(minutes=29)) is not None
    assert find_valid_session(db, just_outside, START + timedelta(minutes=31)) is None


def test_activity_slides_the_idle_timeout(db: Session) -> None:
    user = staff_user(db)
    token, _ = create_session(db, user, START)

    # Seen every 20 minutes: never idle for 30, so the session keeps living...
    for minutes in (20, 40, 60, 80):
        assert find_valid_session(db, token, START + timedelta(minutes=minutes)) is not None

    # ...until 31 idle minutes pass.
    assert find_valid_session(db, token, START + timedelta(minutes=80 + 31)) is None


def test_staff_sessions_end_after_12_hours_however_active(db: Session) -> None:
    user = staff_user(db)
    token, _ = create_session(db, user, START)

    # Active every 20 minutes (so never idle) right up to 11 hours 40 minutes...
    for minutes in range(20, 11 * 60 + 41, 20):
        assert find_valid_session(db, token, START + timedelta(minutes=minutes)) is not None

    # ...and still refused at 12 hours 1 minute: only the absolute lifetime can explain that.
    assert find_valid_session(db, token, START + timedelta(hours=12, minutes=1)) is None


def test_candidates_stay_logged_in_for_7_idle_days(db: Session) -> None:
    user = candidate_user(db)
    token, _ = create_session(db, user, START)

    assert find_valid_session(db, token, START + timedelta(days=6)) is not None
    assert find_valid_session(db, token, START + timedelta(days=6) + timedelta(days=8)) is None


def test_candidate_sessions_end_after_30_days_however_active(db: Session) -> None:
    user = candidate_user(db)
    token, _ = create_session(db, user, START)

    moment = START
    for _ in range(4):
        moment += timedelta(days=6)
        assert find_valid_session(db, token, moment) is not None

    assert find_valid_session(db, token, START + timedelta(days=30, minutes=1)) is None


def test_a_revoked_session_is_refused(db: Session) -> None:
    user = staff_user(db)
    token, session = create_session(db, user, START)

    revoke_session(session, START + timedelta(minutes=1))

    assert find_valid_session(db, token, START + timedelta(minutes=2)) is None


def test_revoking_all_of_a_users_sessions_leaves_other_users_alone(db: Session) -> None:
    company = make_company(db)
    mine = make_user(db, email="a@example.com", role=Role.RECRUITER, company=company)
    other = make_user(db, email="b@example.com", role=Role.RECRUITER, company=company)
    token_one, _ = create_session(db, mine, START)
    token_two, _ = create_session(db, mine, START)
    other_token, _ = create_session(db, other, START)

    revoke_all_sessions(db, mine.id, START + timedelta(minutes=1))

    later = START + timedelta(minutes=2)
    assert find_valid_session(db, token_one, later) is None
    assert find_valid_session(db, token_two, later) is None
    assert find_valid_session(db, other_token, later) is not None


def test_a_deactivated_users_session_is_refused(db: Session) -> None:
    user = staff_user(db)
    token, _ = create_session(db, user, START)
    user.is_active = False
    db.flush()

    assert find_valid_session(db, token, START + timedelta(minutes=1)) is None


def test_finding_a_session_records_when_it_was_last_seen(db: Session) -> None:
    user = staff_user(db)
    token, session = create_session(db, user, START)
    seen_at = START + timedelta(minutes=10)

    find_valid_session(db, token, seen_at)

    stored = db.get(UserSession, session.id)
    assert stored is not None
    assert stored.last_seen_at == seen_at
