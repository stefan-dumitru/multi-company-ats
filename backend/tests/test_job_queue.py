"""The background job queue (operations.md > Background Jobs & Queues).

Rules under test: a job is taken by exactly one worker; failures retry with growing delays and then
stop; a retried or double-queued action produces one job; a job queued inside a transaction exists
only if that transaction commits.
"""

import threading
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import BackgroundJob
from app.worker import queue
from app.worker.queue import JobStatus

NOW = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)


def add_job(
    db: Session, key: str, *, run_at: datetime = NOW, payload: dict[str, str] | None = None
):
    job = queue.enqueue(
        db, type="test", payload=payload or {"id": key}, idempotency_key=key, now=NOW, run_at=run_at
    )
    db.flush()
    return job


def job_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(BackgroundJob)) or 0


# ---- queueing ----------------------------------------------------------------------------


def test_a_new_job_waits_to_be_taken_with_its_attempts_still_at_zero(db: Session) -> None:
    job = add_job(db, "welcome:1", payload={"user_id": "u-1"})

    assert job.status == JobStatus.PENDING
    assert job.attempts == 0
    assert job.max_attempts == 5
    assert job.run_at == NOW
    assert job.payload == {"user_id": "u-1"}
    assert job.locked_at is None and job.finished_at is None and job.last_error is None


def test_queueing_the_same_key_twice_gives_one_job(db: Session) -> None:
    # A retried request, or a double click, must not send two emails.
    first = add_job(db, "invitation_email:abc")
    second = add_job(db, "invitation_email:abc")

    assert second.id == first.id
    assert job_count(db) == 1


def test_different_keys_are_different_jobs(db: Session) -> None:
    add_job(db, "a")
    add_job(db, "b")

    assert job_count(db) == 2


def test_a_job_queued_in_a_rolled_back_transaction_does_not_exist(db: Session) -> None:
    # The business change and its email are one unit: no change, no email.
    add_job(db, "welcome:1")

    db.rollback()

    assert job_count(db) == 0


def test_queueing_never_commits_for_the_caller(db: Session, scratch_engine: Engine) -> None:
    add_job(db, "welcome:1")

    with Session(scratch_engine) as other:
        assert job_count(other) == 0  # not visible to anyone else until the caller commits
    db.commit()
    with Session(scratch_engine) as other:
        assert job_count(other) == 1


def test_a_job_can_be_scheduled_for_later(db: Session) -> None:
    later = NOW + timedelta(hours=1)

    job = add_job(db, "reminder", run_at=later)

    assert job.run_at == later


# ---- taking jobs -------------------------------------------------------------------------


def test_taking_a_job_marks_it_running_and_counts_the_attempt(db: Session) -> None:
    add_job(db, "a")

    job = queue.claim_next(db, NOW)

    assert job is not None
    assert job.status == JobStatus.RUNNING
    assert job.attempts == 1
    assert job.locked_at == NOW


def test_a_job_that_is_taken_cannot_be_taken_again(db: Session) -> None:
    add_job(db, "a")
    assert queue.claim_next(db, NOW) is not None

    assert queue.claim_next(db, NOW) is None


def test_nothing_due_means_nothing_taken(db: Session) -> None:
    assert queue.claim_next(db, NOW) is None


def test_a_job_scheduled_for_later_is_not_taken_early(db: Session) -> None:
    add_job(db, "later", run_at=NOW + timedelta(minutes=5))

    assert queue.claim_next(db, NOW + timedelta(minutes=4)) is None
    assert queue.claim_next(db, NOW + timedelta(minutes=5)) is not None


def test_the_job_due_longest_ago_goes_first(db: Session) -> None:
    add_job(db, "newer", run_at=NOW - timedelta(minutes=1))
    add_job(db, "oldest", run_at=NOW - timedelta(minutes=30))
    add_job(db, "middle", run_at=NOW - timedelta(minutes=10))

    taken = [queue.claim_next(db, NOW), queue.claim_next(db, NOW), queue.claim_next(db, NOW)]

    assert [job.idempotency_key for job in taken if job] == ["oldest", "middle", "newer"]


def test_finished_and_failed_jobs_are_never_taken(db: Session) -> None:
    done = add_job(db, "done")
    broken = add_job(db, "broken")
    done.status, broken.status = JobStatus.SUCCEEDED, JobStatus.FAILED
    db.flush()

    assert queue.claim_next(db, NOW) is None


# ---- finishing and failing ---------------------------------------------------------------


def test_a_successful_job_is_marked_succeeded(db: Session) -> None:
    add_job(db, "a")
    job = queue.claim_next(db, NOW)
    assert job is not None

    queue.complete(db, job, NOW + timedelta(seconds=2))

    assert job.status == JobStatus.SUCCEEDED
    assert job.finished_at == NOW + timedelta(seconds=2)
    assert job.locked_at is None


def test_a_failed_attempt_is_retried_later_with_a_growing_delay(db: Session) -> None:
    add_job(db, "a")
    expected_delays = [60, 300, 1800, 7200]  # seconds, the default schedule
    clock = NOW

    for attempt, delay in enumerate(expected_delays, start=1):
        job = queue.claim_next(db, clock)
        assert job is not None and job.attempts == attempt
        queue.fail(db, job, "SMTP down", clock)
        assert job.status == JobStatus.PENDING
        assert job.run_at == clock + timedelta(seconds=delay)
        assert job.locked_at is None
        clock = job.run_at


def test_after_the_last_attempt_the_job_stays_failed_with_its_reason(db: Session) -> None:
    add_job(db, "a")
    clock = NOW
    job = None
    for _ in range(5):
        job = queue.claim_next(db, clock)
        assert job is not None
        queue.fail(db, job, "SMTP refused the message", clock)
        clock = clock + timedelta(days=1)

    assert job is not None
    assert job.status == JobStatus.FAILED
    assert job.attempts == 5
    assert job.last_error == "SMTP refused the message"
    assert job.finished_at is not None
    assert queue.claim_next(db, clock + timedelta(days=30)) is None  # never tried again


def test_a_long_error_message_is_cut_short(db: Session) -> None:
    add_job(db, "a")
    job = queue.claim_next(db, NOW)
    assert job is not None

    queue.fail(db, job, "x" * 5000, NOW)

    assert job.last_error is not None
    assert len(job.last_error) == queue.MAX_ERROR_LENGTH


def test_the_retry_delays_can_be_shortened_for_a_local_demo(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JOB_BACKOFF_SECONDS", "1,2,3,4")
    add_job(db, "a")
    job = queue.claim_next(db, NOW)
    assert job is not None

    queue.fail(db, job, "down", NOW)

    assert job.run_at == NOW + timedelta(seconds=1)


@pytest.mark.parametrize("bad", ["", "abc", "10,-5", "0", "1,,2"])
def test_a_nonsense_delay_setting_stops_the_program_instead_of_being_guessed(
    db: Session, monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    monkeypatch.setenv("JOB_BACKOFF_SECONDS", bad)
    add_job(db, "a")
    job = queue.claim_next(db, NOW)
    assert job is not None

    with pytest.raises(RuntimeError, match="JOB_BACKOFF_SECONDS"):
        queue.fail(db, job, "down", NOW)


def test_a_short_delay_list_reuses_its_last_value(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JOB_BACKOFF_SECONDS", "7")
    add_job(db, "a")
    clock = NOW
    for _ in range(3):
        job = queue.claim_next(db, clock)
        assert job is not None
        queue.fail(db, job, "down", clock)
        assert job.run_at == clock + timedelta(seconds=7)
        clock = job.run_at


# ---- jobs that were abandoned half way ---------------------------------------------------


def test_a_job_stuck_running_is_put_back_in_the_queue(db: Session) -> None:
    # The worker died after taking it: nobody will ever finish it unless we notice.
    add_job(db, "a")
    job = queue.claim_next(db, NOW)
    assert job is not None

    recovered = queue.requeue_stuck(db, NOW + queue.STUCK_AFTER + timedelta(seconds=1))

    assert recovered == 1
    assert job.status == JobStatus.PENDING
    assert job.attempts == 1  # the lost attempt still counts, so a poison job cannot loop forever
    assert job.last_error is not None and "stopped responding" in job.last_error


def test_a_job_that_has_only_just_been_taken_is_left_alone(db: Session) -> None:
    add_job(db, "a")
    job = queue.claim_next(db, NOW)
    assert job is not None

    recovered = queue.requeue_stuck(db, NOW + queue.STUCK_AFTER - timedelta(seconds=1))

    assert recovered == 0
    assert job.status == JobStatus.RUNNING


def test_a_stuck_job_on_its_last_attempt_fails_instead_of_looping(db: Session) -> None:
    add_job(db, "a")
    clock = NOW
    for _ in range(4):
        job = queue.claim_next(db, clock)
        assert job is not None
        queue.fail(db, job, "down", clock)
        clock = job.run_at
    last = queue.claim_next(db, clock)  # the fifth and final attempt
    assert last is not None and last.attempts == 5

    queue.requeue_stuck(db, clock + queue.STUCK_AFTER + timedelta(seconds=1))

    assert last.status == JobStatus.FAILED


# ---- the database's own rules ------------------------------------------------------------


def test_the_database_refuses_an_unknown_status(db: Session) -> None:
    job = add_job(db, "a")
    job.status = "paused"  # type: ignore[assignment]

    with pytest.raises(IntegrityError):
        db.flush()


def test_the_database_refuses_a_negative_attempt_count(db: Session) -> None:
    job = add_job(db, "a")
    job.attempts = -1

    with pytest.raises(IntegrityError):
        db.flush()


# ---- many workers at once ----------------------------------------------------------------


def test_a_job_that_another_worker_is_holding_is_skipped_not_waited_for(
    db: Session, scratch_engine: Engine
) -> None:
    # This is what SKIP LOCKED means. Worker 1 has locked job A but not finished the paperwork.
    add_job(db, "a", run_at=NOW - timedelta(minutes=2))
    add_job(db, "b", run_at=NOW - timedelta(minutes=1))
    db.commit()

    with Session(scratch_engine) as worker_one, Session(scratch_engine) as worker_two:
        # If SKIP LOCKED ever went missing, worker two would wait forever; make that fail fast.
        worker_two.execute(text("SET lock_timeout = '2s'"))
        held = queue.lock_next_due(worker_one, NOW)  # locked, deliberately not committed
        assert held is not None and held.idempotency_key == "a"

        taken_by_two = queue.claim_next(worker_two, NOW)

        assert taken_by_two is not None
        assert taken_by_two.idempotency_key == "b"  # skipped A instead of waiting for it
        assert queue.claim_next(worker_two, NOW) is None  # and there is nothing else to take
        worker_one.rollback()


def test_many_workers_never_take_the_same_job(db: Session, scratch_engine: Engine) -> None:
    jobs_queued = 40
    for number in range(jobs_queued):
        add_job(db, f"job-{number}")
    db.commit()

    taken: list[str] = []
    taken_lock = threading.Lock()
    start_together = threading.Barrier(6)

    def work() -> None:
        with Session(scratch_engine) as session:
            start_together.wait()
            while True:
                job = queue.claim_next(session, NOW)
                if job is None:
                    return
                with taken_lock:
                    taken.append(job.idempotency_key)

    threads = [threading.Thread(target=work) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert not any(thread.is_alive() for thread in threads)
    assert len(taken) == jobs_queued  # every job was taken...
    assert len(set(taken)) == jobs_queued  # ...exactly once
