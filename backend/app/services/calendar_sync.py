"""Keeping a recruiter's Google Calendar in step with their interviews (functional.md > Schedule an
interview).

Two halves, on either side of the transaction commit:

* `queue_calendar_sync` runs inside the request that changes the interview. It only records "this
  interview needs syncing" as a background job (and marks it `pending`); no call to Google is made
  in a request.
* `sync_interview_event` is the worker's handler. It reads the interview as it is *now* and makes
  Google match: an event for a scheduled interview, no event for a cancelled one. Deciding at run
  time (not from what the job says) is what makes a retry, or two jobs for the same interview, safe.

Google being down never blocks anything: the worker retries, and after the last attempt
`mark_sync_failed` records `failed` for the screen.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from cryptography.fernet import InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_google_settings
from app.emails.invitation import one_line
from app.integrations import google
from app.models import (
    Application,
    BackgroundJob,
    CalendarSyncStatus,
    GoogleCalendarConnection,
    Interview,
    InterviewParticipant,
    InterviewStatus,
    Job,
    User,
)
from app.services.audit import record_audit
from app.services.calendar import decrypt_token
from app.services.errors import CalendarNotConfigured
from app.worker.queue import enqueue

logger = logging.getLogger("ats.calendar")

JOB_TYPE = "calendar_event"


def queue_calendar_sync(db: Session, interview: Interview, now: datetime) -> None:
    """Ask for this interview's event to be brought up to date, if its recruiter has connected
    Google. Call it after the interview has changed (its version is already the new one).

    Someone who has not connected gets nothing queued and the status stays as it was. An interview
    that was cancelled before it ever reached the calendar has nothing to remove, so it is left
    alone as well.
    """
    if db.get(GoogleCalendarConnection, interview.scheduled_by) is None:
        return
    never_synced = (
        interview.google_event_id is None
        and interview.calendar_sync_status == CalendarSyncStatus.NOT_REQUESTED
    )
    if interview.status == InterviewStatus.CANCELLED and never_synced:
        return
    interview.calendar_sync_status = CalendarSyncStatus.PENDING
    enqueue(
        db,
        type=JOB_TYPE,
        # The version lets the final-failure hook tell whether this job is still the latest word.
        payload={"interview_id": str(interview.id), "version": interview.version},
        idempotency_key=f"{JOB_TYPE}:{interview.id}:{interview.version}",
        now=now,
    )


def _event_details(db: Session, interview: Interview) -> google.EventDetails:
    application = db.get(Application, interview.application_id)
    assert application is not None  # the foreign key guarantees it
    job = db.get(Job, application.job_id)
    candidate = db.get(User, application.candidate_id)
    assert job is not None and candidate is not None
    # Attendees are the interviewers who can still act; someone deactivated is not invited.
    emails = db.scalars(
        select(User.email)
        .join(InterviewParticipant, InterviewParticipant.interviewer_id == User.id)
        .where(InterviewParticipant.interview_id == interview.id, User.is_active.is_(True))
        .order_by(User.email)
    ).all()
    return google.EventDetails(
        title=f"Interview: {one_line(candidate.full_name)} - {one_line(job.title)}",
        description=f"Round: {one_line(interview.round_name)}",
        location=one_line(interview.location),
        starts_at=interview.scheduled_at,
        ends_at=interview.scheduled_at + timedelta(minutes=interview.duration_minutes),
        attendee_emails=tuple(emails),
    )


def _is_cancelled(interview: Interview) -> bool:
    return interview.status == InterviewStatus.CANCELLED


def _set_status(db: Session, interview: Interview, status: CalendarSyncStatus) -> None:
    interview.calendar_sync_status = status
    db.flush()


def sync_interview_event(db: Session, job: BackgroundJob) -> None:
    """Worker handler. Raises on a problem that may pass (the worker retries); finishes quietly when
    there is nothing more to do or retrying would not help."""
    interview = db.get(Interview, uuid.UUID(job.payload["interview_id"]))
    if interview is None:
        return
    connection = db.get(GoogleCalendarConnection, interview.scheduled_by)
    if connection is None:
        # They disconnected after this was queued. Nothing can be done for the event now.
        _set_status(db, interview, CalendarSyncStatus.FAILED)
        return
    settings = get_google_settings()
    if settings is None:
        raise CalendarNotConfigured
    try:
        refresh_token = decrypt_token(settings, connection.refresh_token_encrypted)
    except InvalidToken:
        # The encryption key was changed: the stored token cannot be read, so they must reconnect.
        _forget_connection(db, connection, interview, reason="unreadable_token")
        return
    try:
        access_token = google.refresh_access_token(settings, refresh_token)
    except google.GoogleRefused as error:
        if error.reason == "invalid_grant":  # they took our access away in their Google account
            _forget_connection(db, connection, interview, reason="access_revoked")
            return
        raise

    event_id = google.event_id_for(interview.id)
    if _is_cancelled(interview):
        google.delete_event(access_token, event_id)
    else:
        google.upsert_event(access_token, event_id, _event_details(db, interview))
        # A cancel may have been saved while we were talking to Google: look again, and take the
        # event back down rather than leave a cancelled interview on someone's calendar.
        db.refresh(interview)
        if _is_cancelled(interview):
            google.delete_event(access_token, event_id)
    interview.google_event_id = None if _is_cancelled(interview) else event_id
    _set_status(db, interview, CalendarSyncStatus.SYNCED)


def _forget_connection(
    db: Session, connection: GoogleCalendarConnection, interview: Interview, *, reason: str
) -> None:
    """The stored access is no good any more: remove it so the calendar page tells the truth, and
    record that this interview did not sync. Not retried: trying again cannot succeed."""
    owner = db.get(User, connection.user_id)
    db.delete(connection)
    _set_status(db, interview, CalendarSyncStatus.FAILED)
    if owner is not None:
        record_audit(
            db,
            actor=owner,
            action="calendar.disconnected",
            entity_type="calendar_connection",
            entity_id=owner.id,
            old_value=None,
            new_value={"reason": reason},
            now=datetime.now(UTC),
        )
    logger.warning("calendar connection removed", extra={"reason": reason})


def mark_sync_failed(db: Session, job: BackgroundJob) -> None:
    """Final-failure hook: every attempt failed, so say so, unless a newer change has since queued
    a newer job (that one has its own say)."""
    interview = db.get(Interview, uuid.UUID(job.payload["interview_id"]))
    if interview is None or interview.version != job.payload.get("version"):
        return
    if interview.calendar_sync_status == CalendarSyncStatus.PENDING:
        interview.calendar_sync_status = CalendarSyncStatus.FAILED
