"""Keeping Google Calendar in step with interviews (functional.md > Schedule an interview).

The rules under test: a change to an interview queues one sync, in the same transaction, only when
its recruiter has connected Google; the worker makes Google match the interview as it is when the
job runs (an event for a scheduled interview, none for a cancelled one); Google being down is
retried and, after the last try, shown as `failed` without ever blocking scheduling; revoked access
disconnects the recruiter; and no token or event text reaches a log. Google is always the fake one.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from app.config import get_google_settings
from app.integrations import google
from app.models import (
    Application,
    ApplicationStage,
    AuditLog,
    BackgroundJob,
    CalendarSyncStatus,
    GoogleCalendarConnection,
    Interview,
    InterviewStatus,
    JobStatus,
    PostingStatus,
    Role,
    User,
)
from app.services import interviews as interviews_service
from app.services.calendar import encrypt_token
from app.worker.handlers import FINAL_FAILURE_HOOKS, HANDLERS
from app.worker.runner import run_one_job
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
from tests.fake_google import FakeGoogle

REFRESH_TOKEN = "refresh-token-1"


@dataclass
class World:
    admin: User
    recruiter: User  # assigned to the job
    other_recruiter: User  # assigned to the job too
    ivy: User
    ian: User
    ghost: User  # an interviewer who has been deactivated
    cara: User
    application: Application


@pytest.fixture
def world(db: Session) -> World:
    acme = make_company(db, "Acme")
    admin = make_user(db, email="admin@acme.test", role=Role.COMPANY_ADMIN, company=acme)
    recruiter = make_user(db, email="rec@acme.test", role=Role.RECRUITER, company=acme)
    other_recruiter = make_user(db, email="rec2@acme.test", role=Role.RECRUITER, company=acme)
    ivy = make_user(db, email="ivy@acme.test", role=Role.INTERVIEWER, company=acme)
    ian = make_user(db, email="ian@acme.test", role=Role.INTERVIEWER, company=acme)
    ghost = make_user(db, email="ghost@acme.test", role=Role.INTERVIEWER, company=acme)
    ghost.is_active = False
    job = make_job(
        db,
        company=acme,
        department=make_department(db, acme),
        created_by=admin,
        recruiters=[recruiter, other_recruiter],
        status=PostingStatus.OPEN,
        title="Backend Engineer",
    )
    cara = make_candidate(db, email="cara@example.test", full_name="Cara Candidate")
    application = make_application(db, job=job, candidate=cara, stage=ApplicationStage.INTERVIEW)
    db.commit()
    return World(admin, recruiter, other_recruiter, ivy, ian, ghost, cara, application)


def connect(db: Session, fake: FakeGoogle, user: User, token: str = REFRESH_TOKEN) -> None:
    """The recruiter has connected Google (what the callback leaves behind)."""
    settings = get_google_settings()
    assert settings is not None
    fake.refresh_tokens.add(token)
    db.add(
        GoogleCalendarConnection(
            user_id=user.id,
            refresh_token_encrypted=encrypt_token(settings, token),
            scopes=google.SCOPE,
            connected_at=datetime.now(UTC),
        )
    )
    db.commit()


def in_days(days: int) -> datetime:
    return (datetime.now(UTC) + timedelta(days=days)).replace(microsecond=0)


def schedule(
    browser: Browser, world: World, interviewers: list[User] | None = None, **changes: Any
) -> str:
    body: dict[str, Any] = {
        "round_name": "Technical round",
        "scheduled_at": in_days(3).isoformat(),
        "duration_minutes": 45,
        "location": "Room 4",
        "interviewer_ids": [str(person.id) for person in (interviewers or [world.ivy, world.ian])],
        **changes,
    }
    response = browser.send(
        "POST", f"/api/applications/{world.application.id}/interviews", json=body
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def change(browser: Browser, interview_id: str, version: int, **changes: Any) -> None:
    response = browser.send(
        "PATCH", f"/api/interviews/{interview_id}", json={"version": version, **changes}
    )
    assert response.status_code == 200, response.text


def cancel(browser: Browser, interview_id: str, version: int) -> None:
    response = browser.send(
        "POST", f"/api/interviews/{interview_id}/cancel", json={"version": version}
    )
    assert response.status_code == 200, response.text


def stored(db: Session, interview_id: str) -> Interview:
    db.expire_all()
    return db.scalars(select(Interview).where(Interview.id == uuid.UUID(interview_id))).one()


def sync_jobs(db: Session) -> list[BackgroundJob]:
    db.expire_all()
    return list(
        db.scalars(
            select(BackgroundJob)
            .where(BackgroundJob.type == "calendar_event")
            .order_by(BackgroundJob.created_at, BackgroundJob.id)
        )
    )


def work(db: Session) -> None:
    """Run the worker until nothing is due, as days pass (so retries come round). The emails the
    same changes queue are run too, as they would be."""
    for day in range(1, 12):
        later = datetime.now(UTC) + timedelta(days=day)
        while run_one_job(db, HANDLERS, partial(lambda moment: moment, later), FINAL_FAILURE_HOOKS):
            pass
    db.expire_all()


def calls(fake: FakeGoogle, method: str) -> list[Any]:
    return [call for call in fake.calendar_calls() if call.method == method]


# ---- what Google is told -----------------------------------------------------------------------


def test_scheduling_creates_one_event_with_the_right_details(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle
) -> None:
    connect(db, fake_google, world.recruiter)
    when = in_days(3)

    interview_id = schedule(
        Browser(client, db, world.recruiter), world, scheduled_at=when.isoformat()
    )

    assert stored(db, interview_id).calendar_sync_status == CalendarSyncStatus.PENDING
    assert fake_google.calendar_calls() == []  # nothing is sent during the request
    work(db)
    assert list(fake_google.events) == [google.event_id_for(stored(db, interview_id).id)]
    event = next(iter(fake_google.events.values()))
    assert event["summary"] == "Interview: Cara Candidate - Backend Engineer"
    assert event["location"] == "Room 4" and "Technical round" in event["description"]
    assert event["start"] == {"dateTime": when.strftime("%Y-%m-%dT%H:%M:%SZ"), "timeZone": "UTC"}
    assert event["end"]["dateTime"] == (when + timedelta(minutes=45)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert event["attendees"] == [{"email": "ian@acme.test"}, {"email": "ivy@acme.test"}]
    interview = stored(db, interview_id)
    assert interview.calendar_sync_status == CalendarSyncStatus.SYNCED
    assert interview.google_event_id == google.event_id_for(interview.id)


def test_google_is_told_not_to_send_its_own_invitations_and_uses_a_fresh_token(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle
) -> None:
    connect(db, fake_google, world.recruiter)
    schedule(Browser(client, db, world.recruiter), world)

    work(db)

    call = calls(fake_google, "POST")[0]
    assert call.query == {"sendUpdates": "none"}
    assert call.headers["Authorization"] == "Bearer fresh-access-token"
    assert call.timeout == google.TIMEOUT_SECONDS
    assert call.url.startswith("https://")


def test_a_deactivated_interviewer_is_not_invited(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle
) -> None:
    connect(db, fake_google, world.recruiter)
    interview = make_interview(
        db,
        application=world.application,
        scheduled_by=world.recruiter,
        interviewers=[world.ivy, world.ghost],
    )
    db.commit()

    change(Browser(client, db, world.recruiter), str(interview.id), 1, location="Room 9")
    work(db)

    event = next(iter(fake_google.events.values()))
    assert event["attendees"] == [{"email": "ivy@acme.test"}]


def test_rescheduling_changes_the_same_event_instead_of_adding_another(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle
) -> None:
    connect(db, fake_google, world.recruiter)
    browser = Browser(client, db, world.recruiter)
    interview_id = schedule(browser, world)
    work(db)
    later = in_days(5)

    change(browser, interview_id, 1, scheduled_at=later.isoformat())
    assert stored(db, interview_id).calendar_sync_status == CalendarSyncStatus.PENDING
    work(db)

    assert len(fake_google.events) == 1
    event = next(iter(fake_google.events.values()))
    assert event["start"]["dateTime"] == later.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert [call.method for call in fake_google.calendar_calls()] == ["POST", "POST", "PATCH"]
    assert stored(db, interview_id).calendar_sync_status == CalendarSyncStatus.SYNCED


def test_changing_who_interviews_updates_the_attendees(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle
) -> None:
    connect(db, fake_google, world.recruiter)
    browser = Browser(client, db, world.recruiter)
    interview_id = schedule(browser, world, [world.ivy])
    work(db)

    change(browser, interview_id, 1, interviewer_ids=[str(world.ian.id)])
    work(db)

    event = next(iter(fake_google.events.values()))
    assert event["attendees"] == [{"email": "ian@acme.test"}]


def test_an_event_that_already_exists_is_changed_not_duplicated(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle
) -> None:
    """An earlier attempt created it and then failed before recording that: the retry must not
    leave two."""
    connect(db, fake_google, world.recruiter)
    interview_id = schedule(Browser(client, db, world.recruiter), world)
    fake_google.events[google.event_id_for(stored(db, interview_id).id)] = {"summary": "old"}

    work(db)

    assert len(fake_google.events) == 1
    assert next(iter(fake_google.events.values()))["summary"].startswith("Interview: Cara")
    assert [call.method for call in fake_google.calendar_calls()] == ["POST", "PATCH"]


def test_cancelling_removes_the_event(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle
) -> None:
    connect(db, fake_google, world.recruiter)
    browser = Browser(client, db, world.recruiter)
    interview_id = schedule(browser, world)
    work(db)

    cancel(browser, interview_id, 1)
    work(db)

    assert fake_google.events == {}
    interview = stored(db, interview_id)
    assert interview.google_event_id is None
    assert interview.calendar_sync_status == CalendarSyncStatus.SYNCED


def test_a_cancel_that_overtakes_the_create_never_creates_the_event(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle
) -> None:
    connect(db, fake_google, world.recruiter)
    browser = Browser(client, db, world.recruiter)
    interview_id = schedule(browser, world)
    cancel(browser, interview_id, 1)  # before the worker has done anything

    work(db)

    assert fake_google.events == {} and calls(fake_google, "POST") == []
    assert stored(db, interview_id).calendar_sync_status == CalendarSyncStatus.SYNCED


def test_an_event_already_deleted_in_google_is_not_an_error(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle
) -> None:
    connect(db, fake_google, world.recruiter)
    browser = Browser(client, db, world.recruiter)
    interview_id = schedule(browser, world)
    work(db)
    fake_google.events.clear()  # the person deleted it by hand in Google Calendar

    cancel(browser, interview_id, 1)
    work(db)

    assert stored(db, interview_id).calendar_sync_status == CalendarSyncStatus.SYNCED
    assert all(job.status == JobStatus.SUCCEEDED for job in sync_jobs(db))


@pytest.mark.parametrize("how", ["reject", "withdraw"])
def test_ending_the_application_takes_the_event_down(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle, how: str
) -> None:
    connect(db, fake_google, world.recruiter)
    interview_id = schedule(Browser(client, db, world.recruiter), world)
    work(db)

    if how == "reject":
        response = Browser(client, db, world.recruiter).send(
            "POST",
            f"/api/applications/{world.application.id}/reject",
            json={"version": 1, "reason": "skills_mismatch"},
        )
    else:
        response = Browser(client, db, world.cara).send(
            "POST", f"/api/applications/{world.application.id}/withdraw"
        )
    assert response.status_code == 200
    assert stored(db, interview_id).status == InterviewStatus.CANCELLED
    work(db)

    assert fake_google.events == {}
    assert stored(db, interview_id).calendar_sync_status == CalendarSyncStatus.SYNCED


# ---- who gets synced, and when it is queued ----------------------------------------------------


def test_nothing_is_queued_for_a_recruiter_who_has_not_connected(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle
) -> None:
    browser = Browser(client, db, world.recruiter)

    interview_id = schedule(browser, world)
    change(browser, interview_id, 1, location="Room 9")
    cancel(browser, interview_id, 2)
    work(db)

    assert sync_jobs(db) == [] and fake_google.calls == []
    assert stored(db, interview_id).calendar_sync_status == CalendarSyncStatus.NOT_REQUESTED


def test_the_scheduling_recruiters_connection_decides_not_the_one_who_changes_it(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle
) -> None:
    interview_id = schedule(Browser(client, db, world.recruiter), world)  # not connected
    connect(db, fake_google, world.other_recruiter)  # a colleague is

    change(Browser(client, db, world.other_recruiter), interview_id, 1, location="Room 9")

    assert sync_jobs(db) == []


def test_each_change_queues_exactly_one_sync_with_its_own_key(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle
) -> None:
    connect(db, fake_google, world.recruiter)
    browser = Browser(client, db, world.recruiter)

    interview_id = schedule(browser, world)
    change(browser, interview_id, 1, location="Room 9")
    cancel(browser, interview_id, 2)

    jobs = sync_jobs(db)
    assert [job.idempotency_key for job in jobs] == [
        f"calendar_event:{interview_id}:1",
        f"calendar_event:{interview_id}:2",
        f"calendar_event:{interview_id}:3",
    ]
    assert [job.payload for job in jobs] == [
        {"interview_id": interview_id, "version": 1},
        {"interview_id": interview_id, "version": 2},
        {"interview_id": interview_id, "version": 3},
    ]


def test_a_change_that_changes_nothing_queues_nothing(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle
) -> None:
    connect(db, fake_google, world.recruiter)
    browser = Browser(client, db, world.recruiter)
    interview_id = schedule(browser, world)

    change(browser, interview_id, 1, location="Room 4")  # what it already is

    assert len(sync_jobs(db)) == 1


def test_a_refused_change_leaves_no_job_behind(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle
) -> None:
    connect(db, fake_google, world.recruiter)
    browser = Browser(client, db, world.recruiter)
    interview_id = schedule(browser, world)

    stale = browser.send(
        "PATCH", f"/api/interviews/{interview_id}", json={"version": 9, "location": "Room 9"}
    )

    assert stale.status_code == 409 and len(sync_jobs(db)) == 1


def test_an_interview_cancelled_before_it_ever_reached_the_calendar_queues_nothing(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle
) -> None:
    browser = Browser(client, db, world.recruiter)
    interview_id = schedule(browser, world)  # scheduled before connecting
    connect(db, fake_google, world.recruiter)

    cancel(browser, interview_id, 1)

    assert sync_jobs(db) == []
    assert stored(db, interview_id).calendar_sync_status == CalendarSyncStatus.NOT_REQUESTED


def test_an_older_interview_is_synced_when_it_next_changes_after_connecting(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle
) -> None:
    browser = Browser(client, db, world.recruiter)
    interview_id = schedule(browser, world)
    connect(db, fake_google, world.recruiter)

    change(browser, interview_id, 1, location="Room 9")
    work(db)

    assert len(fake_google.events) == 1


# ---- when Google does not cooperate ------------------------------------------------------------


def test_a_failed_attempt_is_retried_and_the_interview_stays_pending(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle
) -> None:
    connect(db, fake_google, world.recruiter)
    interview_id = schedule(Browser(client, db, world.recruiter), world)
    fake_google.fail_next(status=503)

    later = datetime.now(UTC) + timedelta(days=1)
    assert run_one_job(db, HANDLERS, lambda: later, FINAL_FAILURE_HOOKS) is True
    db.expire_all()

    assert stored(db, interview_id).calendar_sync_status == CalendarSyncStatus.PENDING
    assert sync_jobs(db)[0].status == JobStatus.PENDING
    work(db)  # the retry succeeds
    assert stored(db, interview_id).calendar_sync_status == CalendarSyncStatus.SYNCED
    assert len(fake_google.events) == 1


def test_after_the_last_attempt_the_interview_shows_failed_and_scheduling_was_never_blocked(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle
) -> None:
    connect(db, fake_google, world.recruiter)
    interview_id = schedule(Browser(client, db, world.recruiter), world)
    for _ in range(5):
        fake_google.fail_next(status=503)

    work(db)

    interview = stored(db, interview_id)
    assert interview.calendar_sync_status == CalendarSyncStatus.FAILED
    assert interview.status == InterviewStatus.SCHEDULED  # the interview itself is fine
    assert sync_jobs(db)[0].status == JobStatus.FAILED and sync_jobs(db)[0].attempts == 5
    assert fake_google.events == {}


def test_google_refusing_for_another_reason_is_retried_then_failed(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle
) -> None:
    connect(db, fake_google, world.recruiter)
    interview_id = schedule(Browser(client, db, world.recruiter), world)
    for _ in range(5):  # a "no" that is not "access revoked" (that has its own test below)
        fake_google.fail_next(status=403, body=b'{"error": "access_denied"}')

    work(db)

    assert sync_jobs(db)[0].attempts == 5
    assert stored(db, interview_id).calendar_sync_status == CalendarSyncStatus.FAILED
    assert db.get(GoogleCalendarConnection, world.recruiter.id) is not None  # still connected


def test_revoked_access_disconnects_the_recruiter_and_marks_the_sync_failed(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle
) -> None:
    connect(db, fake_google, world.recruiter)
    interview_id = schedule(Browser(client, db, world.recruiter), world)
    fake_google.refresh_tokens.clear()  # Google no longer knows the token: invalid_grant

    work(db)

    assert sync_jobs(db)[0].attempts == 1  # not retried: trying again cannot succeed
    db.expire_all()
    assert db.get(GoogleCalendarConnection, world.recruiter.id) is None
    assert stored(db, interview_id).calendar_sync_status == CalendarSyncStatus.FAILED
    assert fake_google.calendar_calls() == []
    status = Browser(client, db, world.recruiter).get("/api/calendar").json()
    assert status["connected"] is False
    audit = db.scalars(select(AuditLog).where(AuditLog.action == "calendar.disconnected")).one()
    assert audit.new_value == {"reason": "access_revoked"}


def test_a_connection_removed_after_queueing_marks_the_sync_failed(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle
) -> None:
    connect(db, fake_google, world.recruiter)
    interview_id = schedule(Browser(client, db, world.recruiter), world)
    Browser(client, db, world.recruiter).send("DELETE", "/api/calendar/connection")
    fake_google.calls.clear()

    work(db)

    assert fake_google.calls == []
    assert stored(db, interview_id).calendar_sync_status == CalendarSyncStatus.FAILED


def test_a_token_that_can_no_longer_be_read_disconnects_the_recruiter(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle
) -> None:
    connect(db, fake_google, world.recruiter)
    interview_id = schedule(Browser(client, db, world.recruiter), world)
    connection = db.get(GoogleCalendarConnection, world.recruiter.id)
    assert connection is not None
    # As if TOKEN_ENCRYPTION_KEY had been replaced since it was stored.
    connection.refresh_token_encrypted = Fernet(Fernet.generate_key()).encrypt(b"x").decode()
    db.commit()

    work(db)

    db.expire_all()
    assert db.get(GoogleCalendarConnection, world.recruiter.id) is None
    assert stored(db, interview_id).calendar_sync_status == CalendarSyncStatus.FAILED
    assert fake_google.calls == []


def test_a_server_without_google_settings_fails_the_sync_without_blocking_anything(
    client: TestClient,
    db: Session,
    world: World,
    fake_google: FakeGoogle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connect(db, fake_google, world.recruiter)
    interview_id = schedule(Browser(client, db, world.recruiter), world)
    for name in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "TOKEN_ENCRYPTION_KEY"):
        monkeypatch.delenv(name)

    work(db)

    assert stored(db, interview_id).calendar_sync_status == CalendarSyncStatus.FAILED
    assert db.get(GoogleCalendarConnection, world.recruiter.id) is not None  # still theirs


def test_an_older_jobs_failure_does_not_overrule_a_newer_change(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle
) -> None:
    connect(db, fake_google, world.recruiter)
    browser = Browser(client, db, world.recruiter)
    interview_id = schedule(browser, world)
    change(browser, interview_id, 1, location="Room 9")  # version 2, status pending
    first_job = sync_jobs(db)[0]

    FINAL_FAILURE_HOOKS["calendar_event"](db, first_job)  # the version 1 job gave up
    db.commit()

    assert stored(db, interview_id).calendar_sync_status == CalendarSyncStatus.PENDING


def test_a_late_failure_does_not_undo_a_sync_that_has_since_worked(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle
) -> None:
    connect(db, fake_google, world.recruiter)
    interview_id = schedule(Browser(client, db, world.recruiter), world)
    work(db)  # synced
    job = sync_jobs(db)[0]

    FINAL_FAILURE_HOOKS["calendar_event"](db, job)
    db.commit()

    assert stored(db, interview_id).calendar_sync_status == CalendarSyncStatus.SYNCED


# ---- what must never be logged -----------------------------------------------------------------


def test_no_token_or_event_text_reaches_a_log(
    client: TestClient,
    db: Session,
    world: World,
    fake_google: FakeGoogle,
    caplog: pytest.LogCaptureFixture,
    google_env: str,
) -> None:
    connect(db, fake_google, world.recruiter, token="very-secret-refresh-token")
    schedule(Browser(client, db, world.recruiter), world)
    fake_google.fail_next(status=503, body=b"very-secret-refresh-token Cara Candidate")
    caplog.set_level(logging.DEBUG)

    work(db)

    text = "\n".join(
        f"{record.getMessage()} {record.__dict__}"
        for record in caplog.records
        if not record.name.startswith(("httpx", "httpcore"))
    )
    for secret in (
        "very-secret-refresh-token",
        "fresh-access-token",
        "Cara",
        "Backend Engineer",
        "ivy@acme.test",
        google_env,
    ):
        assert secret not in text


# ---- a cancel that lands while the worker is talking to Google ---------------------------------


def test_a_cancel_saved_while_the_event_is_being_created_takes_it_down_again(
    client: TestClient,
    db: Session,
    world: World,
    fake_google: FakeGoogle,
    scratch_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connect(db, fake_google, world.recruiter)
    interview_id = schedule(Browser(client, db, world.recruiter), world)
    real_upsert = google.upsert_event

    def upsert_then_cancel(access_token: str, event_id: str, details: google.EventDetails) -> None:
        real_upsert(access_token, event_id, details)
        with Session(scratch_engine) as other:  # the recruiter cancels at this very moment
            recruiter = other.get(User, world.recruiter.id)
            assert recruiter is not None
            interviews_service.cancel_interview(
                other, recruiter, uuid.UUID(interview_id), 1, datetime.now(UTC)
            )
            # The cancel's own sync job is dropped, so only the job already running can clean up.
            other.execute(
                delete(BackgroundJob).where(
                    BackgroundJob.idempotency_key.like("calendar_event:%:2")
                )
            )
            other.commit()

    monkeypatch.setattr(google, "upsert_event", upsert_then_cancel)
    attempt = datetime.now(UTC) + timedelta(days=1)
    queued_sync = sync_jobs(db)[0]
    queued_sync.run_at = attempt - timedelta(hours=1)
    db.commit()
    for _ in range(5):  # the emails are run too; only the sync job matters here
        run_one_job(db, HANDLERS, lambda: attempt, FINAL_FAILURE_HOOKS)

    assert fake_google.events == {}
    assert [call.method for call in fake_google.calendar_calls()] == ["POST", "DELETE"]
    interview = stored(db, interview_id)
    assert interview.google_event_id is None
    assert interview.calendar_sync_status == CalendarSyncStatus.SYNCED
