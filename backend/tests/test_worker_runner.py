"""The worker loop (operations.md > Background Jobs & Queues).

Rules under test: a due job is run by its handler and marked done; a failing handler leaves the
job to retry later and never leaves half its database changes behind; asking the worker to stop
lets the current job finish; a database hiccup does not kill the worker; logs never carry
payloads.
"""

import json
import threading
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models import AuditLog, BackgroundJob, JobStatus
from app.worker import heartbeat, queue, runner
from app.worker.runner import Handler

NOW = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)


def clock() -> datetime:
    return NOW


def add_job(
    db: Session, key: str, *, type: str = "test", payload: dict[str, str] | None = None
) -> None:
    queue.enqueue(db, type=type, payload=payload or {"id": key}, idempotency_key=key, now=NOW)
    db.commit()


def reload(db: Session, key: str) -> BackgroundJob:
    db.expire_all()
    return db.scalars(select(BackgroundJob).where(BackgroundJob.idempotency_key == key)).one()


def fail_on_last_attempt(db: Session, key: str) -> None:
    job = reload(db, key)
    job.attempts = job.max_attempts - 1
    db.commit()


def always_fails(_db: Session, _job: BackgroundJob) -> None:
    raise RuntimeError("still broken")


# ---- one job ------------------------------------------------------------------------------


def test_a_due_job_is_handled_and_marked_succeeded(db: Session) -> None:
    add_job(db, "a", payload={"user_id": "u-1"})
    seen: list[dict[str, str]] = []

    ran = runner.run_one_job(db, {"test": lambda _db, job: seen.append(job.payload)}, clock)

    assert ran is True
    assert seen == [{"user_id": "u-1"}]
    job = reload(db, "a")
    assert job.status == JobStatus.SUCCEEDED
    assert job.attempts == 1


def test_with_nothing_due_nothing_runs(db: Session) -> None:
    assert runner.run_one_job(db, {}, clock) is False


def test_a_failing_handler_leaves_the_job_to_retry_later(db: Session) -> None:
    add_job(db, "a")

    def handler(_db: Session, _job: BackgroundJob) -> None:
        raise ConnectionError("SMTP is down")

    runner.run_one_job(db, {"test": handler}, clock)

    job = reload(db, "a")
    assert job.status == JobStatus.PENDING
    assert job.run_at == NOW + timedelta(minutes=1)
    assert job.last_error == "ConnectionError: SMTP is down"


def test_a_failing_handler_leaves_none_of_its_database_changes_behind(db: Session) -> None:
    add_job(db, "a")

    def handler(session: Session, _job: BackgroundJob) -> None:
        session.add(AuditLog(action="half-done", entity_type="test"))
        session.flush()
        raise RuntimeError("died after writing")

    runner.run_one_job(db, {"test": handler}, clock)

    assert db.scalars(select(AuditLog)).all() == []


def test_a_handler_that_broke_the_transaction_does_not_stop_the_failure_being_recorded(
    db: Session,
) -> None:
    add_job(db, "a")

    def handler(session: Session, _job: BackgroundJob) -> None:
        # The database refuses this row, which leaves the transaction unusable until rolled back.
        session.add(
            BackgroundJob(type="x", payload={}, idempotency_key="b", run_at=NOW, attempts=-1)
        )
        session.flush()

    runner.run_one_job(db, {"test": handler}, clock)

    assert reload(db, "a").status == JobStatus.PENDING


def test_a_job_type_nobody_handles_is_retried_not_dropped(db: Session) -> None:
    # During a deploy the web app can be newer than the worker. The job must wait, not vanish.
    add_job(db, "a", type="from_the_future")

    runner.run_one_job(db, {}, clock)

    job = reload(db, "a")
    assert job.status == JobStatus.PENDING
    assert job.last_error is not None and "from_the_future" in job.last_error


def test_the_last_failed_attempt_makes_the_job_failed(db: Session) -> None:
    add_job(db, "a")
    fail_on_last_attempt(db, "a")

    runner.run_one_job(db, {"test": always_fails}, clock)

    assert reload(db, "a").status == JobStatus.FAILED


# ---- logging ------------------------------------------------------------------------------


def test_the_log_line_names_the_job_and_outcome_but_never_the_payload(
    db: Session, caplog: pytest.LogCaptureFixture
) -> None:
    add_job(db, "a", payload={"email": "private.person@example.test"})

    with caplog.at_level("INFO", logger="ats.worker"):
        runner.run_one_job(db, {"test": always_fails}, clock)

    record = next(r for r in caplog.records if r.name == "ats.worker")
    assert record.__dict__["job_type"] == "test"
    assert record.__dict__["attempt"] == 1
    assert record.__dict__["outcome"] == "retry"
    assert "private.person" not in json.dumps([r.__dict__ for r in caplog.records], default=str)


def test_a_success_is_logged_as_succeeded(db: Session, caplog: pytest.LogCaptureFixture) -> None:
    add_job(db, "a")

    with caplog.at_level("INFO", logger="ats.worker"):
        runner.run_one_job(db, {"test": lambda _db, _job: None}, clock)

    outcomes = [r.__dict__["outcome"] for r in caplog.records if r.name == "ats.worker"]
    assert outcomes == ["succeeded"]


def test_giving_up_on_a_job_is_logged_as_an_error(
    db: Session, caplog: pytest.LogCaptureFixture
) -> None:
    add_job(db, "a")
    fail_on_last_attempt(db, "a")

    with caplog.at_level("INFO", logger="ats.worker"):
        runner.run_one_job(db, {"test": always_fails}, clock)

    record = next(r for r in caplog.records if r.name == "ats.worker")
    assert record.levelname == "ERROR"
    assert record.__dict__["outcome"] == "failed"


# ---- the loop -----------------------------------------------------------------------------


def run_loop_until_stopped(
    db: Session, stop: threading.Event, handlers: Mapping[str, Handler]
) -> None:
    runner.run_loop(
        db, stop, handlers, poll_seconds=0.01, clock=clock, schedule_hourly_maintenance=False
    )


def test_the_loop_drains_the_queue_then_stops_when_asked(db: Session) -> None:
    for number in range(3):
        add_job(db, f"job-{number}")
    stop = threading.Event()
    handled: list[str] = []

    def handler(_db: Session, job: BackgroundJob) -> None:
        handled.append(job.idempotency_key)
        if len(handled) == 3:
            stop.set()

    run_loop_until_stopped(db, stop, {"test": handler})

    assert sorted(handled) == ["job-0", "job-1", "job-2"]


def test_asking_the_worker_to_stop_lets_the_current_job_finish(db: Session) -> None:
    add_job(db, "first")
    add_job(db, "second")
    stop = threading.Event()

    def handler(_db: Session, _job: BackgroundJob) -> None:
        stop.set()  # the stop request arrives while this job is running

    run_loop_until_stopped(db, stop, {"test": handler})

    statuses = sorted(reload(db, key).status for key in ("first", "second"))
    assert statuses == [JobStatus.PENDING, JobStatus.SUCCEEDED]  # one finished whole, one untouched


def test_an_idle_loop_keeps_the_heartbeat_going(db: Session) -> None:
    stop = threading.Event()
    threading.Timer(0.2, stop.set).start()

    run_loop_until_stopped(db, stop, {})

    assert heartbeat.last_heartbeat(db) == NOW


def test_the_loop_stamps_its_heartbeat_with_the_deployment_it_runs_in(db: Session) -> None:
    stop = threading.Event()
    threading.Timer(0.2, stop.set).start()

    runner.run_loop(
        db,
        stop,
        {},
        poll_seconds=0.01,
        clock=clock,
        deployment_id="dep-7",
        schedule_hourly_maintenance=False,
    )

    assert heartbeat.worker_is_alive(db, NOW, deployment_id="dep-7") is True


def test_the_loop_rescues_jobs_a_dead_worker_left_running(db: Session) -> None:
    add_job(db, "a")
    queue.claim_next(db, NOW - queue.STUCK_AFTER - timedelta(minutes=1))  # taken, then abandoned
    stop = threading.Event()
    threading.Timer(0.2, stop.set).start()

    run_loop_until_stopped(db, stop, {})

    assert reload(db, "a").status == JobStatus.PENDING


def test_a_database_error_does_not_kill_the_worker(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_job(db, "a")
    stop = threading.Event()
    real_claim = queue.claim_next
    calls = {"count": 0}

    def flaky_claim(session: Session, now: datetime) -> BackgroundJob | None:
        calls["count"] += 1
        if calls["count"] == 1:
            raise OperationalError("SELECT", {}, Exception("connection lost"))
        return real_claim(session, now)

    monkeypatch.setattr(queue, "claim_next", flaky_claim)

    def handler(_db: Session, _job: BackgroundJob) -> None:
        stop.set()

    run_loop_until_stopped(db, stop, {"test": handler})

    assert reload(db, "a").status == JobStatus.SUCCEEDED
