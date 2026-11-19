"""Connecting a recruiter's Google account (functional.md > Schedule an interview).

The refresh token is the long-lived key to someone's calendar, so it is stored encrypted (Fernet,
keyed by TOKEN_ENCRYPTION_KEY) and appears nowhere else: not in a response, not in a log, not in the
audit row. Nothing Google does can break the app: every failure becomes a short code the screen can
show. The caller commits.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.auth import tokens
from app.config import GoogleSettings, get_google_settings
from app.integrations import google
from app.models import GoogleCalendarConnection, User
from app.services.audit import record_audit
from app.services.errors import CalendarNotConfigured

logger = logging.getLogger("ats.calendar")

# How long a person has to finish in Google's window before the way back stops working.
MAX_STATE_AGE = timedelta(minutes=10)


class CalendarCallbackError(Exception):
    """The way back from Google did not end in a connection. `reason` is one short code the
    calendar page turns into words; Google's own text is never passed on."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class CalendarStatus:
    configured: bool
    connected: bool
    connected_at: datetime | None


def encrypt_token(settings: GoogleSettings, token: str) -> str:
    return Fernet(settings.encryption_key.encode()).encrypt(token.encode()).decode()


def decrypt_token(settings: GoogleSettings, stored: str) -> str:
    """Raises `InvalidToken` if the key is not the one it was encrypted with (or it was changed)."""
    return Fernet(settings.encryption_key.encode()).decrypt(stored.encode()).decode()


def connection_status(db: Session, user: User) -> CalendarStatus:
    connection = db.get(GoogleCalendarConnection, user.id)
    return CalendarStatus(
        configured=get_google_settings() is not None,
        connected=connection is not None,
        connected_at=connection.connected_at if connection else None,
    )


def start_connection(user: User, now: datetime) -> str:
    """The address of Google's window, carrying a state made for exactly this person."""
    settings = get_google_settings()
    if settings is None:
        raise CalendarNotConfigured
    return google.authorization_url(
        settings, tokens.make_state(tokens.GOOGLE_CALENDAR, user.id, now)
    )


def finish_connection(
    db: Session,
    user: User,
    now: datetime,
    *,
    code: str | None,
    state: str | None,
    error: str | None,
) -> None:
    """What happens when Google sends the browser back. Raises `CalendarCallbackError` unless the
    person ends up connected."""
    settings = get_google_settings()
    if settings is None:
        raise CalendarCallbackError("not_configured")
    if error is not None:
        # They said no, or Google had a problem. Never repeat Google's words back.
        raise CalendarCallbackError("access_denied" if error == "access_denied" else "google_error")
    owner = tokens.read_state(tokens.GOOGLE_CALENDAR, state or "", now, MAX_STATE_AGE)
    if owner != user.id:
        # Missing, forged, too old, or made for somebody else who is not the one logged in now.
        raise CalendarCallbackError("bad_state")
    if not code:
        raise CalendarCallbackError("missing_code")

    try:
        grant = google.exchange_code(settings, code)
    except google.GoogleUnavailable:
        raise CalendarCallbackError("google_unavailable") from None
    except google.GoogleRefused:
        raise CalendarCallbackError("google_refused") from None

    connection = db.get(GoogleCalendarConnection, user.id)
    if connection is None:
        connection = GoogleCalendarConnection(user_id=user.id)
        db.add(connection)
    connection.refresh_token_encrypted = encrypt_token(settings, grant.refresh_token)
    connection.scopes = grant.scope
    connection.connected_at = now
    _audit(db, user, "calendar.connected", now)


def disconnect(db: Session, user: User, now: datetime) -> None:
    """Forget the person's token, and ask Google to as well. Always ends disconnected: if Google
    cannot be reached (or the settings are gone) the row is deleted all the same."""
    connection = db.get(GoogleCalendarConnection, user.id)
    if connection is None:
        return
    settings = get_google_settings()
    if settings is not None:
        try:
            google.revoke(settings, decrypt_token(settings, connection.refresh_token_encrypted))
        except (google.GoogleError, InvalidToken) as error:
            # Only the kind of error is logged: nothing that could echo a token.
            logger.warning("could not revoke at Google", extra={"error_type": type(error).__name__})
    db.delete(connection)
    _audit(db, user, "calendar.disconnected", now)


def _audit(db: Session, user: User, action: str, now: datetime) -> None:
    record_audit(
        db,
        actor=user,
        action=action,
        entity_type="calendar_connection",
        entity_id=user.id,
        old_value=None,
        new_value=None,  # nothing about the connection beyond the fact of it
        now=now,
    )
