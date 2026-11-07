"""Housekeeping (data-model.md > Data Retention): old technical rows are purged, on a schedule.

Rules under test: every table keeps what is recent or still in use and drops what is old, with the
boundary on the right side; history that must be kept (audit log, invitations) is never touched;
exactly one maintenance job is queued per hour however many workers run; and the real worker loop
schedules it and the purge really happens through the queue.
"""

import threading
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.auth import tokens
from app.models import (
    AuditLog,
    BackgroundJob,
    Invitation,
    JobStatus,
    LoginAttempt,
    Role,
    User,
    UserSession,
    UserToken,
)
from app.worker import maintenance, queue, runner
from app.worker.handlers import HANDLERS
from tests.factories import make_company, make_user

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


def ago(**period: float) -> datetime:
    return NOW - timedelta(**period)


def count(db: Session, model: type) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


def a_user(db: Session) -> User:
    return make_user(
        db,
        email=f"u{uuid.uuid4().hex[:6]}@acme.test",
        role=Role.RECRUITER,
        company=make_company(db),
    )


def a_session(db: Session, user: User, **fields: datetime | None) -> UserSession:
    defaults: dict[str, datetime | None] = {
        "created_at": ago(hours=1),
        "last_seen_at": ago(minutes=5),
        "expires_at": NOW + timedelta(hours=8),
        "revoked_at": None,
    }
    session = UserSession(
        id=uuid.uuid4().hex + uuid.uuid4().hex,
        user_id=user.id,
        csrf_token="x",
        **{**defaults, **fields},
    )
    db.add(session)
    db.flush()
    return session


def a_token(db: Session, user: User, **fields: datetime | None) -> UserToken:
    defaults: dict[str, datetime | None] = {
        "created_at": ago(hours=1),
        "expires_at": NOW + timedelta(hours=1),
        "used_at": None,
    }
    token = UserToken(user_id=user.id, type=tokens.PASSWORD_RESET, **{**defaults, **fields})
    db.add(token)
    db.flush()
    return token


def a_job(db: Session, status: JobStatus, finished_at: datetime | None) -> BackgroundJob:
    job = queue.enqueue(
        db, type="t", payload={}, idempotency_key=uuid.uuid4().hex, now=ago(days=200)
    )
    job.status = status
    job.finished_at = finished_at
    db.flush()
    return job


# ---- login attempts -----------------------------------------------------------------------


def test_login_attempts_older_than_a_day_are_purged_and_recent_ones_kept(db: Session) -> None:
    db.add_all(
        [
            LoginAttempt(
                email_hash="a", ip_address="1.1.1.1", attempted_at=ago(hours=24, minutes=1)
            ),
            LoginAttempt(
                email_hash="b", ip_address="1.1.1.1", attempted_at=ago(hours=23, minutes=59)
            ),
        ]
    )
    db.flush()

    result = maintenance.purge_old_rows(db, NOW)

    assert result["login_attempts"] == 1
    assert [row.email_hash for row in db.scalars(select(LoginAttempt))] == ["b"]


# ---- sessions -----------------------------------------------------------------------------


def test_sessions_are_purged_a_week_after_they_expired_or_were_revoked(db: Session) -> None:
    user = a_user(db)
    expired_long_ago = a_session(db, user, expires_at=ago(days=7, minutes=1))
    expired_lately = a_session(db, user, expires_at=ago(days=6, hours=23))
    revoked_long_ago = a_session(db, user, revoked_at=ago(days=7, minutes=1))
    revoked_lately = a_session(db, user, revoked_at=ago(days=6, hours=23))

    result = maintenance.purge_old_rows(db, NOW)

    assert result["sessions"] == 2
    kept = {row.id for row in db.scalars(select(UserSession))}
    assert kept == {expired_lately.id, revoked_lately.id}
    assert expired_long_ago.id not in kept and revoked_long_ago.id not in kept


def test_a_session_nobody_has_touched_for_a_month_is_purged(db: Session) -> None:
    user = a_user(db)
    dead = a_session(
        db, user, last_seen_at=ago(days=30, minutes=1), expires_at=NOW + timedelta(days=1)
    )
    idle_but_possible = a_session(
        db, user, last_seen_at=ago(days=29), expires_at=NOW + timedelta(days=1)
    )

    maintenance.purge_old_rows(db, NOW)

    kept = {row.id for row in db.scalars(select(UserSession))}
    assert kept == {idle_but_possible.id} and dead.id not in kept


def test_a_live_session_is_never_purged(db: Session) -> None:
    user = a_user(db)
    live = a_session(db, user)

    maintenance.purge_old_rows(db, NOW)

    assert db.get(UserSession, live.id) is not None


# ---- email links --------------------------------------------------------------------------


def test_links_are_purged_a_week_after_they_were_used_or_expired(db: Session) -> None:
    user = a_user(db)
    used_long_ago = a_token(db, user, used_at=ago(days=7, minutes=1))
    used_lately = a_token(db, user, used_at=ago(days=6, hours=23))
    expired_long_ago = a_token(db, user, expires_at=ago(days=7, minutes=1))
    expired_lately = a_token(db, user, expires_at=ago(days=6, hours=23))

    result = maintenance.purge_old_rows(db, NOW)

    assert result["user_tokens"] == 2
    kept = {row.id for row in db.scalars(select(UserToken))}
    assert kept == {used_lately.id, expired_lately.id}
    assert used_long_ago.id not in kept and expired_long_ago.id not in kept


def test_a_link_that_can_still_be_used_is_never_purged(db: Session) -> None:
    user = a_user(db)
    live = a_token(db, user)

    maintenance.purge_old_rows(db, NOW)

    assert db.get(UserToken, live.id) is not None


# ---- jobs ---------------------------------------------------------------------------------


def test_succeeded_jobs_are_purged_after_30_days(db: Session) -> None:
    old = a_job(db, JobStatus.SUCCEEDED, ago(days=30, minutes=1))
    recent = a_job(db, JobStatus.SUCCEEDED, ago(days=29))

    result = maintenance.purge_old_rows(db, NOW)

    assert result["background_jobs"] == 1
    kept = {row.id for row in db.scalars(select(BackgroundJob))}
    assert kept == {recent.id} and old.id not in kept


def test_failed_jobs_are_kept_longer_for_diagnosis(db: Session) -> None:
    thirty_one_days = a_job(db, JobStatus.FAILED, ago(days=31))
    ninety_one_days = a_job(db, JobStatus.FAILED, ago(days=90, minutes=1))

    maintenance.purge_old_rows(db, NOW)

    kept = {row.id for row in db.scalars(select(BackgroundJob))}
    assert kept == {thirty_one_days.id} and ninety_one_days.id not in kept


def test_jobs_that_are_waiting_or_running_are_never_purged(db: Session) -> None:
    pending = a_job(db, JobStatus.PENDING, None)
    running = a_job(db, JobStatus.RUNNING, None)

    maintenance.purge_old_rows(db, NOW)

    assert {row.id for row in db.scalars(select(BackgroundJob))} == {pending.id, running.id}


# ---- what must never be touched -----------------------------------------------------------


def test_history_is_never_purged(db: Session) -> None:
    user = a_user(db)
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="role_change",
            entity_type="user",
            entity_id=user.id,
            created_at=ago(days=1000),
        )
    )
    db.add(
        Invitation(
            company_id=user.company_id,
            email="old@acme.test",
            role=Role.RECRUITER,
            token_hash=uuid.uuid4().hex + uuid.uuid4().hex,
            invited_by=user.id,
            created_at=ago(days=1000),
            expires_at=ago(days=993),
        )
    )
    db.flush()

    maintenance.purge_old_rows(db, NOW)

    assert count(db, AuditLog) == 1  # append-only
    assert count(db, Invitation) == 1  # still shown in the admin's list
    assert count(db, User) == 1


def test_purging_twice_changes_nothing_the_second_time(db: Session) -> None:
    db.add(LoginAttempt(email_hash="a", ip_address="1.1.1.1", attempted_at=ago(days=3)))
    db.flush()
    first = maintenance.purge_old_rows(db, NOW)

    second = maintenance.purge_old_rows(db, NOW)

    assert first["login_attempts"] == 1
    assert second == {"login_attempts": 0, "sessions": 0, "user_tokens": 0, "background_jobs": 0}


# ---- scheduling ---------------------------------------------------------------------------


def maintenance_jobs(db: Session) -> list[BackgroundJob]:
    db.expire_all()
    rows = db.scalars(select(BackgroundJob).order_by(BackgroundJob.created_at))
    return [job for job in rows if job.type == "maintenance"]


def test_one_job_is_queued_per_hour_however_often_it_is_asked(db: Session) -> None:
    for minute in (0, 1, 30, 59):
        maintenance.schedule_maintenance(db, NOW.replace(hour=14, minute=minute))

    (job,) = maintenance_jobs(db)
    assert job.idempotency_key == "maintenance:2026-06-15T14"
    assert job.payload == {}


def test_the_next_hour_gets_its_own_job(db: Session) -> None:
    maintenance.schedule_maintenance(db, NOW.replace(hour=14, minute=59))
    maintenance.schedule_maintenance(db, NOW.replace(hour=15, minute=0))

    assert len(maintenance_jobs(db)) == 2


def test_two_workers_asking_at_the_same_moment_still_queue_one_job(
    db: Session, scratch_engine: Engine
) -> None:
    start_together = threading.Barrier(2)

    def ask() -> None:
        with Session(scratch_engine) as session:
            start_together.wait()
            maintenance.schedule_maintenance(session, NOW)

    threads = [threading.Thread(target=ask) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert len(maintenance_jobs(db)) == 1


def test_the_worker_knows_how_to_do_maintenance() -> None:
    assert "maintenance" in HANDLERS


def test_the_worker_loop_schedules_and_runs_the_purge_by_itself(db: Session) -> None:
    import threading as threads_module

    db.add(LoginAttempt(email_hash="old", ip_address="1.1.1.1", attempted_at=ago(days=3)))
    db.commit()
    stop = threads_module.Event()
    ran: list[str] = []

    def purge_then_stop(session: Session, job: BackgroundJob) -> None:
        HANDLERS["maintenance"](session, job)
        ran.append(job.idempotency_key)
        stop.set()

    runner.run_loop(
        db, stop, {"maintenance": purge_then_stop}, poll_seconds=0.01, clock=lambda: NOW
    )

    assert ran == ["maintenance:2026-06-15T12"]
    assert count(db, LoginAttempt) == 0
    assert maintenance_jobs(db)[0].status == JobStatus.SUCCEEDED


def test_the_log_line_reports_counts_and_nothing_else(db: Session, caplog) -> None:  # type: ignore[no-untyped-def]
    db.add(
        LoginAttempt(email_hash="secret-hash", ip_address="203.0.113.7", attempted_at=ago(days=3))
    )
    db.flush()
    job = queue.enqueue(db, type="maintenance", payload={}, idempotency_key="m", now=NOW)

    with caplog.at_level("INFO", logger="ats.worker"):
        HANDLERS["maintenance"](db, job)

    record = next(r for r in caplog.records if r.getMessage() == "maintenance finished")
    assert record.__dict__["login_attempts"] == 1
    logged = " ".join(str(v) for v in record.__dict__.values())
    assert "secret-hash" not in logged and "203.0.113.7" not in logged
